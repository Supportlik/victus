import { computed, Injectable, signal } from '@angular/core';
import { API_BASE } from '../api';

/** Where the stream stands. `offline` means it is not running, not that the API is down. */
export type LiveState = 'connecting' | 'live' | 'offline';

/** The four numbers the navigation badges show. Every stream message carries them. */
export interface LiveCounts {
  new_captures: number;
  draft_days: number;
  open_days: number;
  pending_proposals: number;
}

/**
 * One thing that changed, as the server names it.
 *
 * `id` is the entity's own id; for a `day_log` that is the ISO date, which is what lets a
 * day view tell a change of its own day from a change of the one next to it.
 */
export interface ChangeTarget {
  /** What happened, e.g. `day.update`. */
  action: string;
  /** What it happened to, e.g. `day_log`, `meal`, `line_item`, `capture`, `agent_run`. */
  type: string;
  id: string;
}

/** One `change` message: a cursor and everything that changed in that transaction. */
export interface LiveChange {
  cursor: number;
  targets: ChangeTarget[];
}

const STREAM_URL = `${API_BASE}/events`;
const MIN_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 30_000;
/**
 * A stream that has said nothing for this long is treated as gone. The server sends a
 * heartbeat every ~20 s, so silence past a minute is a connection a proxy is holding open
 * after it died — the browser reports no error for that and would wait forever.
 */
const SILENCE_MS = 60_000;

/** `EventSource.CLOSED`, spelled out because the constructor may be a stub in a test. */
const CLOSED = 2;

function isTarget(value: unknown): value is ChangeTarget {
  const t = value as Record<string, unknown> | null;
  return !!t && typeof t === 'object' && typeof t['type'] === 'string' && typeof t['id'] === 'string';
}

/**
 * The server's change stream (`GET /api/v1/events`, Server-Sent Events).
 *
 * The session cookie authenticates it — it is same-origin, so no header is involved and no
 * token has to be handed to the browser. `hello` arrives once with the current counts,
 * `change` arrives with every write and names what it touched.
 *
 * Everything here is best-effort by design. A browser without `EventSource`, a proxy that
 * refuses the stream, a payload that does not parse: each of those leaves `state` away from
 * `live` and the app on the polling it did before. Nothing in the application depends on
 * the stream being there; it only makes the same data arrive sooner.
 */
@Injectable({ providedIn: 'root' })
export class LiveService {
  readonly state = signal<LiveState>('offline');
  readonly counts = signal<LiveCounts | null>(null);
  /**
   * The last change that arrived. Read it from an `effect`, or through `liveRefresh()`.
   *
   * Coalescing is deliberate: two changes that land before the effect flushes are seen as
   * one, and every reader answers a change by re-fetching, which is idempotent.
   */
  readonly lastChange = signal<LiveChange | null>(null);
  /**
   * Raised each time the stream comes back after a break.
   *
   * What happened during the break is unknown — a manual reconnect does not resume from
   * `Last-Event-ID` — so a reader that cares takes a fresh copy when it sees this move.
   */
  readonly reconnects = signal(0);
  /**
   * Whether the stream has ever stood in this session.
   *
   * It separates "connecting for the first time" from "reconnecting", which is the
   * difference between a page that is still starting and one that has lost its connection.
   */
  readonly wasLive = signal(false);
  readonly connected = computed(() => this.state() === 'live');

  private source: EventSource | null = null;
  private attempt = 0;
  private retry: ReturnType<typeof setTimeout> | null = null;
  private watchdog: ReturnType<typeof setInterval> | null = null;
  private lastMessageAt = 0;
  /** Whether the stream should be running at all: set by sign-in, cleared by sign-out. */
  private wanted = false;

  /** Open the stream. Called once the session exists and is not a recovery session. */
  start(): void {
    if (this.wanted) return;
    this.wanted = true;
    this.open();
  }

  /** Close it and forget what it said. Called on sign-out. */
  stop(): void {
    this.wanted = false;
    this.clearTimers();
    this.close();
    this.attempt = 0;
    this.wasLive.set(false);
    this.state.set('offline');
    this.counts.set(null);
    this.lastChange.set(null);
  }

  private open(): void {
    if (!this.wanted) return;
    this.close();
    const Ctor = (globalThis as { EventSource?: typeof EventSource }).EventSource;
    if (!Ctor) {
      // No EventSource in this browser: the app keeps the polling it had before.
      this.state.set('offline');
      return;
    }
    let source: EventSource;
    try {
      source = new Ctor(STREAM_URL);
    } catch {
      // A blocked stream (an extension, a strict CSP) throws here rather than erroring.
      this.state.set('connecting');
      this.scheduleRetry();
      return;
    }
    this.source = source;
    this.lastMessageAt = Date.now();
    this.state.set('connecting');
    source.addEventListener('hello', (e) => this.onMessage(e as MessageEvent, false));
    source.addEventListener('change', (e) => this.onMessage(e as MessageEvent, true));
    // The server's heartbeat is `event: heartbeat` and carries the cursor. A named event
    // reaches no listener but its own, so without this line a stream that is merely quiet
    // looks dead to the watchdog and is torn down and reopened once a minute, for ever.
    source.addEventListener('heartbeat', (e) => this.onMessage(e as MessageEvent, false));
    // Unnamed or `ping` are accepted too; either is proof of life.
    source.addEventListener('message', (e) => this.onMessage(e as MessageEvent, false));
    source.addEventListener('ping', () => this.alive());
    source.addEventListener('error', () => this.onError());
    this.ensureWatchdog();
  }

  private onMessage(event: MessageEvent, isChange: boolean): void {
    this.alive();
    const data = this.parse(event.data);
    if (!data) return;
    const counts = data['counts'];
    if (counts && typeof counts === 'object') this.counts.set(counts as LiveCounts);
    if (!isChange) return;
    const targets = Array.isArray(data['targets']) ? data['targets'].filter(isTarget) : [];
    this.lastChange.set({
      cursor: typeof data['cursor'] === 'number' ? data['cursor'] : 0,
      targets,
    });
  }

  /** A payload that does not parse is dropped: it is a broken message, not a broken app. */
  private parse(raw: unknown): Record<string, unknown> | null {
    if (typeof raw !== 'string' || !raw.trim()) return null;
    try {
      const value: unknown = JSON.parse(raw);
      return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
    } catch {
      return null;
    }
  }

  /** Something arrived: the stream stands, and the backoff starts from the beginning again. */
  private alive(): void {
    this.lastMessageAt = Date.now();
    this.attempt = 0;
    if (this.retry) {
      clearTimeout(this.retry);
      this.retry = null;
    }
    if (this.state() === 'live') return;
    this.state.set('live');
    if (this.wasLive()) this.reconnects.update((n) => n + 1);
    this.wasLive.set(true);
  }

  /**
   * EventSource retries by itself while it is `CONNECTING`, and gives up at `CLOSED`.
   *
   * Both have to be handled: leaving the browser to it loses the stream for good on the
   * errors it treats as fatal, and reopening on every error fights its own retry.
   */
  private onError(): void {
    if (!this.wanted) return;
    this.state.set('connecting');
    if (this.source && this.source.readyState !== CLOSED) return;
    this.close();
    this.scheduleRetry();
  }

  private scheduleRetry(): void {
    if (!this.wanted || this.retry) return;
    const base = Math.min(MAX_BACKOFF_MS, MIN_BACKOFF_MS * 2 ** this.attempt);
    this.attempt += 1;
    // Jitter, so every tab and every client does not return at the same instant on a
    // server that has just come back and is at its weakest.
    const delay = base / 2 + Math.random() * (base / 2);
    this.retry = setTimeout(() => {
      this.retry = null;
      this.open();
    }, delay);
  }

  private ensureWatchdog(): void {
    if (this.watchdog) return;
    this.watchdog = setInterval(() => {
      if (!this.wanted || Date.now() - this.lastMessageAt < SILENCE_MS) return;
      this.state.set('connecting');
      this.close();
      this.scheduleRetry();
    }, SILENCE_MS / 2);
  }

  private close(): void {
    try {
      this.source?.close();
    } catch {
      /* already gone */
    }
    this.source = null;
  }

  private clearTimers(): void {
    if (this.retry) clearTimeout(this.retry);
    this.retry = null;
    if (this.watchdog) clearInterval(this.watchdog);
    this.watchdog = null;
  }
}
