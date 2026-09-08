import { TestBed } from '@angular/core/testing';
import { describe, expect, it, beforeEach } from 'vitest';
import { ThemeService } from './theme.service';

describe('ThemeService', () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset['scheme'];
    delete document.documentElement.dataset['palette'];
  });

  it('applies scheme and palette to <html> and persists them', () => {
    const svc = TestBed.inject(ThemeService);
    TestBed.tick();
    expect(document.documentElement.dataset['scheme']).toBe('system');
    expect(document.documentElement.dataset['palette']).toBe('graphite');
    svc.palette.set('forest');
    svc.cycleScheme();
    TestBed.tick();
    expect(document.documentElement.dataset['palette']).toBe('forest');
    expect(document.documentElement.dataset['scheme']).toBe('light');
    expect(localStorage.getItem('victus.palette')).toBe('forest');
    expect(localStorage.getItem('victus.scheme')).toBe('light');
  });

  it('falls back to the default palette for unknown stored values', () => {
    localStorage.setItem('victus.palette', 'neon');
    TestBed.inject(ThemeService);
    TestBed.tick();
    expect(document.documentElement.dataset['palette']).toBe('graphite');
  });
});
