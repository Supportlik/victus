// T-WEB-070: the change stream — what it publishes, when it reopens itself, and what it
// leaves behind in a browser that has no EventSource at all.
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CLOSED, MockEventSource } from '../../testing/event-source.mock';
import { LiveService } from './live.service';

const COUNTS = { new_captures: 2, draft_days: 1, open_days: 3, pending_proposals: 0 };
const TARGET = { action: 'day.update', type: 'day_log', id: '2026-09-12' };

describe('LiveService', () => {
  let live: LiveService;

  beforeEach(() => {
    MockEventSource.install();
    TestBed.configureTestingModule({});
    live = TestBed.inject(LiveService);
  });

  afterEach(() => {
    live.stop();
    MockEventSource.restore();
    vi.useRealTimers();
  });

  it('opens one stream and reads the counts out of hello', () => {
    live.start();
    expect(MockEventSource.instances).toHaveLength(1);
    expect(MockEventSource.last.url).toBe('/api/v1/events');
    expect(live.state()).toBe('connecting');

    MockEventSource.last.emit('hello', { cursor: 7, counts: COUNTS });
    expect(live.state()).toBe('live');
    expect(live.connected()).toBe(true);
    expect(live.counts()).toEqual(COUNTS);

    // starting again while it is running would leave two streams on one session
    live.start();
    expect(MockEventSource.instances).toHaveLength(1);
  });

  it('publishes what a change names, and drops a payload that does not parse', () => {
    live.start();
    const stream = MockEventSource.last;
    stream.emit('change', { cursor: 8, counts: COUNTS, targets: [TARGET] });
    expect(live.lastChange()).toEqual({ cursor: 8, targets: [TARGET] });
    expect(live.counts()).toEqual(COUNTS);

    // a broken message is a broken message, not a broken page: the last good one stands
    for (const listener of stream.listeners.get('change') ?? []) {
      listener(new MessageEvent('change', { data: 'not json' }));
    }
    expect(live.lastChange()?.cursor).toBe(8);
  });

  it('lets the browser retry, and takes over once it has given up', () => {
    vi.useFakeTimers();
    live.start();
    MockEventSource.last.emit('hello', { cursor: 1, counts: COUNTS });

    // still CONNECTING: the browser is retrying by itself, and a second stream opened
    // here would fight its own reconnect
    MockEventSource.last.fail(false);
    expect(live.state()).toBe('connecting');
    vi.advanceTimersByTime(5_000);
    expect(MockEventSource.instances).toHaveLength(1);

    // CLOSED: it has given up, and nothing else in the app would ever reopen the stream
    MockEventSource.last.fail(true);
    vi.advanceTimersByTime(1_000);
    expect(MockEventSource.instances).toHaveLength(2);

    MockEventSource.last.emit('hello', { cursor: 9, counts: COUNTS });
    expect(live.state()).toBe('live');
    expect(live.reconnects()).toBe(1), 'what happened during the break is unknown';
  });

  it('reopens a stream that has gone silent past the heartbeat', () => {
    vi.useFakeTimers();
    live.start();
    MockEventSource.last.emit('hello', { cursor: 1, counts: COUNTS });
    // A proxy that holds a dead socket open reports no error at all. Without this the page
    // would sit on a stream that says nothing and call itself live.
    vi.advanceTimersByTime(70_000);
    expect(MockEventSource.instances.length).toBeGreaterThan(1);
    expect(live.state()).toBe('connecting');
  });

  // T-WEB-070: the server names its heartbeat `heartbeat`, and a named SSE event reaches no
  // listener but its own. The first build of this service listened for `message` and `ping`,
  // so a stream that was merely quiet looked dead: torn down and reopened once a minute, for
  // ever, on every open tab.
  it('counts the named heartbeat as proof of life', () => {
    vi.useFakeTimers();
    live.start();
    const stream = MockEventSource.last;
    stream.emit('hello', { cursor: 1, counts: COUNTS });
    const opened = MockEventSource.instances.length;
    vi.advanceTimersByTime(40_000);
    stream.emit('heartbeat', { cursor: 1 });
    vi.advanceTimersByTime(40_000);
    // 80 s have passed and nothing changed, but the beat at 40 s was heard
    expect(MockEventSource.instances.length).toBe(opened);
    expect(live.state()).toBe('live');
  });

  it('leaves the app on its polling where the browser has no EventSource', () => {
    MockEventSource.restore();
    live.start();
    expect(live.state()).toBe('offline');
    expect(live.connected()).toBe(false);
    expect(live.counts()).toBeNull();
  });

  it('closes the stream and forgets its counts on sign-out', () => {
    live.start();
    const stream = MockEventSource.last;
    stream.emit('change', { cursor: 4, counts: COUNTS, targets: [TARGET] });

    live.stop();
    expect(stream.readyState).toBe(CLOSED);
    expect(live.state()).toBe('offline');
    expect(live.counts()).toBeNull();
    expect(live.lastChange()).toBeNull();
  });
});
