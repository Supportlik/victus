// T-WEB-378: the change stream's edges — a constructor that throws, the unnamed and ping
// messages, payloads that are not what they claim, and a stream that errors after sign-out.
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MockEventSource } from '../../testing/event-source.mock';
import { LiveService } from './live.service';

const COUNTS = { new_captures: 1, draft_days: 0, open_days: 0, pending_proposals: 0 };

function raw(stream: MockEventSource, type: string, data: unknown): void {
  for (const listener of stream.listeners.get(type) ?? []) listener(new MessageEvent(type, { data }));
}

describe('T-WEB-378: LiveService (coverage)', () => {
  let live: LiveService;

  beforeEach(() => {
    vi.useFakeTimers();
    MockEventSource.install();
    TestBed.configureTestingModule({});
    live = TestBed.inject(LiveService);
  });

  afterEach(() => {
    live.stop();
    MockEventSource.restore();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('T-WEB-378: a stream the browser refuses to construct is retried with backoff', () => {
    const holder = globalThis as Record<string, unknown>;
    holder['EventSource'] = class {
      constructor() {
        throw new Error('blocked by CSP');
      }
    };
    live.start();
    expect(live.state()).toBe('connecting');

    holder['EventSource'] = MockEventSource;
    vi.advanceTimersByTime(1_000);
    expect(MockEventSource.instances).toHaveLength(1);
    MockEventSource.last.emit('hello', { cursor: 1, counts: COUNTS });
    expect(live.state()).toBe('live');
    expect(live.reconnects()).toBe(0), 'it had never stood, so this is not a reconnect';
  });

  it('T-WEB-378: an unnamed message or a ping is proof of life', () => {
    live.start();
    MockEventSource.last.emit('message', { counts: COUNTS });
    expect(live.state()).toBe('live');
    expect(live.counts()).toEqual(COUNTS);

    live.stop();
    live.start();
    const stream = MockEventSource.last;
    for (const l of stream.listeners.get('ping') ?? []) l(new Event('ping'));
    expect(live.state()).toBe('live');
  });

  it('T-WEB-378: a change keeps only well-formed targets and defaults a missing cursor', () => {
    live.start();
    const stream = MockEventSource.last;
    stream.emit('change', {
      targets: [{ action: 'x', type: 'meal', id: '4' }, { type: 'meal' }, null, 'day_log'],
    });
    expect(live.lastChange()).toEqual({ cursor: 0, targets: [{ action: 'x', type: 'meal', id: '4' }] });

    stream.emit('change', { cursor: 5, targets: 'not a list' });
    expect(live.lastChange()).toEqual({ cursor: 5, targets: [] });
    expect(live.counts()).toBeNull(), 'no counts were sent';
  });

  it('T-WEB-378: payloads that are empty, not text or not an object are dropped', () => {
    live.start();
    const stream = MockEventSource.last;
    stream.emit('change', { cursor: 2, targets: [] });
    for (const data of ['', '   ', 42, '"just a string"', 'null']) raw(stream, 'change', data);
    expect(live.lastChange()?.cursor).toBe(2);
  });

  it('T-WEB-378: a pending retry is dropped when the old stream speaks again', () => {
    live.start();
    const stream = MockEventSource.last;
    stream.fail(true);
    stream.fail(true);
    expect(live.state()).toBe('connecting');
    // the retry was scheduled once; a second error does not stack another
    stream.emit('hello', { cursor: 1, counts: COUNTS });
    vi.advanceTimersByTime(30_000);
    expect(MockEventSource.instances).toHaveLength(1);
    expect(live.state()).toBe('live');
  });

  it('T-WEB-378: an error after sign-out and a close that throws change nothing', () => {
    live.start();
    const stream = MockEventSource.last;
    vi.spyOn(stream, 'close').mockImplementation(() => {
      throw new Error('already gone');
    });
    expect(() => live.stop()).not.toThrow();
    stream.fail(true);
    expect(live.state()).toBe('offline');
    vi.advanceTimersByTime(60_000);
    expect(MockEventSource.instances).toHaveLength(1);
  });
});
