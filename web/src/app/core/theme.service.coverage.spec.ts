// T-WEB-380: the appearance switch — the full scheme cycle, the no-transition class while
// every colour changes at once, and blocked storage.
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { blockLocalStorage } from '../../testing/blocked-storage';
import { ThemeService } from './theme.service';

describe('T-WEB-380: ThemeService (coverage)', () => {
  const root = document.documentElement;
  let unblock: (() => void) | null = null;

  beforeEach(() => {
    delete root.dataset['scheme'];
    delete root.dataset['palette'];
    root.classList.remove('v-switching');
  });

  afterEach(() => {
    unblock?.();
    unblock = null;
    vi.restoreAllMocks();
  });

  it('T-WEB-380: cycles system, light, dark and back to system', () => {
    const theme = TestBed.inject(ThemeService);
    const seen = [theme.scheme()];
    for (let i = 0; i < 3; i++) {
      theme.cycleScheme();
      seen.push(theme.scheme());
    }
    expect(seen).toEqual(['system', 'light', 'dark', 'system']);
  });

  it('T-WEB-380: suspends transitions for the frame in which the colours switch', () => {
    const frames: FrameRequestCallback[] = [];
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
      frames.push(cb);
      return frames.length;
    });
    const theme = TestBed.inject(ThemeService);
    TestBed.tick();
    expect(root.classList.contains('v-switching')).toBe(false), 'the first paint is not a switch';

    theme.scheme.set('dark');
    TestBed.tick();
    expect(root.dataset['scheme']).toBe('dark');
    expect(root.classList.contains('v-switching')).toBe(true);
    frames.forEach((cb) => cb(0));
    expect(root.classList.contains('v-switching')).toBe(false);

    // setting the value it already has is not a switch
    frames.length = 0;
    theme.palette.set('graphite');
    theme.scheme.set('dark');
    TestBed.tick();
    expect(frames).toHaveLength(0);
  });

  it('T-WEB-380: blocked storage uses the defaults and still applies a choice', () => {
    unblock = blockLocalStorage();
    const theme = TestBed.inject(ThemeService);
    expect(theme.scheme()).toBe('system');
    expect(theme.palette()).toBe('graphite');
    theme.palette.set('ocean');
    expect(() => TestBed.tick()).not.toThrow();
    expect(root.dataset['palette']).toBe('ocean');
  });
});
