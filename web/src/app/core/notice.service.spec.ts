import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NoticeService } from './notice.service';

describe('NoticeService', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('lets a success disappear on its own', () => {
    const svc = TestBed.inject(NoticeService);
    svc.ok('Saved as version 3.');
    expect(svc.notices()).toHaveLength(1);
    vi.advanceTimersByTime(4000);
    expect(svc.notices()).toEqual([]);
  });

  it('keeps an error until it is dismissed', () => {
    const svc = TestBed.inject(NoticeService);
    svc.error('Request failed (500).');
    vi.advanceTimersByTime(60_000);
    expect(svc.notices()).toHaveLength(1);

    svc.dismiss(svc.notices()[0].id);
    expect(svc.notices()).toEqual([]);
  });

  it('keeps at most three messages, dropping the oldest', () => {
    const svc = TestBed.inject(NoticeService);
    svc.error('first');
    svc.error('second');
    svc.error('third');
    svc.error('fourth');
    expect(svc.notices().map((n) => n.text)).toEqual(['second', 'third', 'fourth']);
  });
});
