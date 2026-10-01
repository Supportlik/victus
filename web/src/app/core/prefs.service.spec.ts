// T-WEB-372, T-WEB-373: the landing page and the rail state are remembered per browser, and a
// blocked store only means they are not remembered.
import { TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { blockLocalStorage } from '../../testing/blocked-storage';
import { LANDINGS, PrefsService } from './prefs.service';

describe('PrefsService', () => {
  let unblock: (() => void) | null = null;

  afterEach(() => {
    unblock?.();
    unblock = null;
    vi.useRealTimers();
  });

  it('T-WEB-372: opens on today with the rail expanded, and remembers a change', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-12T10:00:00Z'));
    localStorage.setItem('victus.timezone', 'UTC');
    const prefs = TestBed.inject(PrefsService);
    expect(prefs.landing()).toBe('today');
    expect(prefs.railCollapsed()).toBe(false);
    expect(prefs.landingUrl()).toBe('/days/2026-09-12');

    prefs.landing.set('reports');
    prefs.railCollapsed.set(true);
    TestBed.tick();
    expect(localStorage.getItem('victus.landing')).toBe('reports');
    expect(localStorage.getItem('victus.railCollapsed')).toBe('1');

    prefs.railCollapsed.set(false);
    TestBed.tick();
    expect(localStorage.getItem('victus.railCollapsed')).toBe('0');
  });

  it('T-WEB-372: starts from what the browser remembered', () => {
    localStorage.setItem('victus.landing', 'inbox');
    localStorage.setItem('victus.railCollapsed', '1');
    const prefs = TestBed.inject(PrefsService);
    expect(prefs.landing()).toBe('inbox');
    expect(prefs.railCollapsed()).toBe(true);
  });

  it('T-WEB-372: every landing the settings offer has its own URL', () => {
    const prefs = TestBed.inject(PrefsService);
    const urls = Object.fromEntries(
      LANDINGS.map((l) => {
        prefs.landing.set(l.id);
        return [l.id, prefs.landingUrl()];
      }),
    );
    expect(urls['days']).toBe('/days');
    expect(urls['inbox']).toBe('/inbox');
    expect(urls['reports']).toBe('/reports');
    expect(urls['today']).toMatch(/^\/days\/\d{4}-\d{2}-\d{2}$/);
  });

  it('T-WEB-373: blocked storage leaves the defaults and does not throw on a change', () => {
    unblock = blockLocalStorage();
    const prefs = TestBed.inject(PrefsService);
    expect(prefs.landing()).toBe('today');
    expect(prefs.railCollapsed()).toBe(false);
    prefs.landing.set('days');
    expect(() => TestBed.tick()).not.toThrow();
    expect(prefs.landingUrl()).toBe('/days');
  });
});
