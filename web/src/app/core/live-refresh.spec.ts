// T-WEB-364..366: a page follows the change stream (R80) — silently while nothing is being
// edited, with a hint while something is, and with a fresh copy after a reconnect.
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LiveRefresh, liveRefresh } from './live-refresh';
import { ChangeTarget, LiveChange, LiveService } from './live.service';

const OWN: ChangeTarget = { action: 'day.update', type: 'day_log', id: '2026-09-12' };
const OTHER: ChangeTarget = { action: 'day.update', type: 'day_log', id: '2026-09-13' };

describe('LiveRefresh', () => {
  it('T-WEB-364: refreshes at once when nothing is being edited', () => {
    const refresh = vi.fn();
    const state = new LiveRefresh({ accepts: () => true, refresh, busy: () => false });
    state.arrived();
    expect(refresh).toHaveBeenCalledOnce();
    expect(state.pending()).toBe(false);
  });

  it('T-WEB-364: holds a change back while something is being edited, until asked or dismissed', () => {
    const refresh = vi.fn();
    const state = new LiveRefresh({ accepts: () => true, refresh, busy: () => true });
    state.arrived();
    expect(refresh).not.toHaveBeenCalled();
    expect(state.pending()).toBe(true);

    state.dismiss();
    expect(state.pending()).toBe(false);
    expect(refresh).not.toHaveBeenCalled(), 'not now means not now';

    state.arrived();
    expect(state.pending()).toBe(true), 'the next change brings the hint back';
    state.apply();
    expect(state.pending()).toBe(false);
    expect(refresh).toHaveBeenCalledOnce();
  });
});

describe('liveRefresh()', () => {
  const lastChange = signal<LiveChange | null>(null);
  const reconnects = signal(0);
  let refresh: ReturnType<typeof vi.fn<() => void>>;
  let busy: boolean;

  function wire(): LiveRefresh {
    return TestBed.runInInjectionContext(() =>
      liveRefresh({
        accepts: (targets) => targets.some((t) => t.id === OWN.id),
        refresh,
        busy: () => busy,
      }),
    );
  }

  beforeEach(() => {
    lastChange.set(null);
    reconnects.set(0);
    refresh = vi.fn<() => void>();
    busy = false;
    TestBed.configureTestingModule({
      providers: [{ provide: LiveService, useValue: { lastChange, reconnects } }],
    });
  });

  it('T-WEB-365: does nothing before a change arrives, or for a change without targets', () => {
    const state = wire();
    TestBed.tick();
    expect(refresh).not.toHaveBeenCalled();

    lastChange.set({ cursor: 1, targets: [] });
    TestBed.tick();
    expect(refresh).not.toHaveBeenCalled();
    expect(state.pending()).toBe(false);
  });

  it("T-WEB-365: ignores a batch about another page and refreshes on one about its own", () => {
    wire();
    TestBed.tick();
    lastChange.set({ cursor: 2, targets: [OTHER] });
    TestBed.tick();
    expect(refresh).not.toHaveBeenCalled();

    lastChange.set({ cursor: 3, targets: [OTHER, OWN] });
    TestBed.tick();
    expect(refresh).toHaveBeenCalledOnce();
  });

  it('T-WEB-365: raises the hint instead of refreshing when the page is busy', () => {
    const state = wire();
    TestBed.tick();
    busy = true;
    lastChange.set({ cursor: 4, targets: [OWN] });
    TestBed.tick();
    expect(refresh).not.toHaveBeenCalled();
    expect(state.pending()).toBe(true);
  });

  it('T-WEB-366: takes a fresh copy after a reconnect, but not while something is being edited', () => {
    wire();
    TestBed.tick();
    expect(refresh).not.toHaveBeenCalled(), 'no reconnect has happened yet';

    reconnects.set(1);
    TestBed.tick();
    expect(refresh).toHaveBeenCalledOnce();

    busy = true;
    reconnects.set(2);
    TestBed.tick();
    expect(refresh).toHaveBeenCalledOnce();
  });
});
