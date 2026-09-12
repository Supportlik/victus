/**
 * A stand-in for the browser's `EventSource`, for the specs around `LiveService`.
 *
 * jsdom ships none at all, and a real one would open a socket to whatever answers on the
 * test host — which is the one thing a unit test must not do. This records what was opened
 * and lets a spec deliver `hello`, `change`, a heartbeat or a failure by hand.
 *
 * Only what `LiveService` uses is implemented: `addEventListener`, `close` and
 * `readyState`. Installing it casts, because the real interface carries a dozen members
 * that would be dead weight here.
 */
type Listener = (event: Event) => void;

/** The three `EventSource.readyState` values, spelled out. */
export const CONNECTING = 0;
export const OPEN = 1;
export const CLOSED = 2;

export class MockEventSource {
  /** Every instance opened since `install()`, oldest first. */
  static readonly instances: MockEventSource[] = [];
  private static original: unknown = undefined;
  private static installed = false;

  readonly listeners = new Map<string, Listener[]>();
  readyState = CONNECTING;

  constructor(readonly url: string) {
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  removeEventListener(type: string, listener: Listener): void {
    this.listeners.set(type, (this.listeners.get(type) ?? []).filter((l) => l !== listener));
  }

  close(): void {
    this.readyState = CLOSED;
  }

  /** Deliver one named message with a JSON payload, the way the server sends it. */
  emit(type: string, data: unknown): void {
    this.readyState = OPEN;
    this.dispatch(type, new MessageEvent(type, { data: JSON.stringify(data) }));
  }

  /**
   * The stream failed.
   *
   * `fatal` is the case the browser gives up on and leaves `CLOSED`; without it the
   * browser is still retrying by itself, which the service has to leave alone.
   */
  fail(fatal = false): void {
    this.readyState = fatal ? CLOSED : CONNECTING;
    this.dispatch('error', new Event('error'));
  }

  private dispatch(type: string, event: Event): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }

  /** The stream opened last; every spec here works on one at a time. */
  static get last(): MockEventSource {
    const found = MockEventSource.instances[MockEventSource.instances.length - 1];
    if (!found) throw new Error('no EventSource was opened');
    return found;
  }

  static install(): void {
    const holder = globalThis as Record<string, unknown>;
    if (!MockEventSource.installed) {
      MockEventSource.original = holder['EventSource'];
      MockEventSource.installed = true;
    }
    MockEventSource.instances.length = 0;
    holder['EventSource'] = MockEventSource;
  }

  static restore(): void {
    const holder = globalThis as Record<string, unknown>;
    if (MockEventSource.installed) {
      if (MockEventSource.original === undefined) delete holder['EventSource'];
      else holder['EventSource'] = MockEventSource.original;
      MockEventSource.installed = false;
    }
    MockEventSource.instances.length = 0;
  }
}
