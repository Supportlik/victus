// T-WEB-073: the navigation badges follow the change stream while it is live, and fall
// back to the minute poll when it is not.
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MockEventSource } from '../../testing/event-source.mock';
import { BadgesService } from './badges.service';
import { LiveService } from './live.service';

const COUNTS = { new_captures: 4, draft_days: 2, open_days: 5, pending_proposals: 1 };

describe('BadgesService', () => {
  let badges: BadgesService;
  let live: LiveService;
  let http: HttpTestingController;

  /** Answer every request waiting, and say how many there were. A poll makes four. */
  function answerAll(): number {
    const open = http.match(() => true);
    open.forEach((r) => r.flush([]));
    return open.length;
  }

  beforeEach(() => {
    MockEventSource.install();
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    live = TestBed.inject(LiveService);
    badges = TestBed.inject(BadgesService);
    vi.useFakeTimers();
  });

  afterEach(() => {
    badges.stop();
    live.stop();
    vi.useRealTimers();
    MockEventSource.restore();
  });

  it('takes the four numbers from the stream instead of asking for them', () => {
    badges.start();
    expect(answerAll()).toBe(4), 'the one read start() always makes';

    live.start();
    MockEventSource.last.emit('hello', { cursor: 1, counts: COUNTS });
    TestBed.inject(ApplicationRef).tick();
    expect(badges.newCaptures()).toBe(4);
    expect(badges.draftDays()).toBe(2);
    expect(badges.openDays()).toBe(5);
    expect(badges.pendingProposals()).toBe(1);

    // the stream carries the counts with every message, so the poll has nothing to add
    vi.advanceTimersByTime(60_000);
    http.expectNone(() => true);
  });

  it('keeps polling when there is no stream', () => {
    badges.start();
    expect(answerAll()).toBe(4);
    vi.advanceTimersByTime(60_000);
    expect(answerAll()).toBe(4), 'the behaviour the app had before the stream existed';
  });

  it('picks the poll back up when the stream drops', () => {
    badges.start();
    answerAll();
    live.start();
    MockEventSource.last.emit('hello', { cursor: 1, counts: COUNTS });
    vi.advanceTimersByTime(60_000);
    http.expectNone(() => true);

    MockEventSource.last.fail(true);
    vi.advanceTimersByTime(60_000);
    expect(answerAll()).toBe(4);
  });
});
