// T-WEB-377: the badge read itself — which four requests go out, what each count is taken
// from, and that a failing one leaves the others (and the page) alone.
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MockEventSource } from '../../testing/event-source.mock';
import { BadgesService } from './badges.service';
import { LiveService } from './live.service';

describe('T-WEB-377: BadgesService (coverage)', () => {
  let badges: BadgesService;
  let http: HttpTestingController;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-12T10:00:00Z'));
    localStorage.setItem('victus.timezone', 'UTC');
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    badges = TestBed.inject(BadgesService);
  });

  afterEach(() => {
    badges.stop();
    TestBed.inject(LiveService).stop();
    MockEventSource.restore();
    vi.useRealTimers();
  });

  it('T-WEB-377: counts new captures, draft days, pending proposals and open days before today', () => {
    badges.refresh();
    const captures = http.expectOne((r) => r.url === '/api/v1/captures');
    expect(captures.request.params.get('status')).toBe('new');
    captures.flush([{ id: 'a' }, { id: 'b' }, { id: 'c' }]);
    http.expectOne('/api/v1/drafts').flush([{ date: '2026-09-10' }]);
    http.expectOne((r) => r.url === '/api/v1/proposals').flush([{ id: 'p1' }, { id: 'p2' }]);
    const days = http.expectOne((r) => r.url === '/api/v1/days');
    expect(days.request.params.get('from')).toBe('2026-07-14'), 'sixty days back';
    expect(days.request.params.get('to')).toBe('2026-09-12');
    expect(days.request.params.get('status')).toBe('open');
    // today is still being logged, so an open today is not overdue
    days.flush([{ date: '2026-09-01' }, { date: '2026-09-11' }, { date: '2026-09-12' }]);

    expect(badges.newCaptures()).toBe(3);
    expect(badges.draftDays()).toBe(1);
    expect(badges.pendingProposals()).toBe(2);
    expect(badges.openDays()).toBe(2);
  });

  it('T-WEB-377: a failing read keeps its last count and does not throw', () => {
    badges.newCaptures.set(7);
    badges.refresh();
    const problem = { title: 'Server Error' };
    const status = { status: 500, statusText: 'Server Error' };
    http.expectOne((r) => r.url === '/api/v1/captures').flush(problem, status);
    http.expectOne('/api/v1/drafts').flush(problem, status);
    http.expectOne((r) => r.url === '/api/v1/proposals').flush(problem, status);
    http.expectOne((r) => r.url === '/api/v1/days').error(new ProgressEvent('error'));
    expect(badges.newCaptures()).toBe(7);
    expect(badges.draftDays()).toBe(0);
  });

  it('T-WEB-377: starting twice runs one poll, and stopping twice is harmless', () => {
    badges.start();
    badges.start();
    expect(http.match(() => true).length).toBe(4);
    badges.stop();
    badges.stop();
    vi.advanceTimersByTime(120_000);
    http.expectNone(() => true);
  });

  it('T-WEB-377: counts from a stream that is not live are not taken', () => {
    MockEventSource.install();
    const live = TestBed.inject(LiveService);
    live.counts.set({ new_captures: 9, draft_days: 9, open_days: 9, pending_proposals: 9 });
    TestBed.inject(ApplicationRef).tick();
    expect(badges.newCaptures()).toBe(0);
    expect(live.connected()).toBe(false);
  });
});
