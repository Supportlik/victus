// T-WEB-367..371: numbers, days and clocks read the way the tenant writes them (R69), and the
// choice survives a reload through browser storage — or costs nothing when storage is blocked.
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { blockLocalStorage } from '../../testing/blocked-storage';
import {
  DEFAULT_LOCALE,
  DEFAULT_TIMEZONE,
  FormatService,
  isoDayIn,
  storedLocale,
  storedTimezone,
  todayLocal,
} from './format.service';

describe('format.service free functions', () => {
  let unblock: (() => void) | null = null;

  afterEach(() => {
    unblock?.();
    unblock = null;
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('T-WEB-367: reads the mirrored locale and zone, and falls back to the defaults', () => {
    expect(storedLocale()).toBe(DEFAULT_LOCALE);
    expect(storedTimezone()).toBe(DEFAULT_TIMEZONE);

    localStorage.setItem('victus.locale', 'en-GB');
    localStorage.setItem('victus.timezone', 'America/New_York');
    expect(storedLocale()).toBe('en-GB');
    expect(storedTimezone()).toBe('America/New_York');

    localStorage.setItem('victus.locale', 'xx-YY');
    localStorage.setItem('victus.timezone', '');
    expect(storedLocale()).toBe(DEFAULT_LOCALE), 'a locale the app ships no data for';
    expect(storedTimezone()).toBe(DEFAULT_TIMEZONE);
  });

  it('T-WEB-367: blocked storage yields the defaults instead of an error', () => {
    unblock = blockLocalStorage();
    expect(storedLocale()).toBe(DEFAULT_LOCALE);
    expect(storedTimezone()).toBe(DEFAULT_TIMEZONE);
  });

  it('T-WEB-368: names the day in the configured zone, not in UTC', () => {
    const lateUtc = new Date('2026-03-01T23:30:00Z');
    expect(isoDayIn(lateUtc, 'Europe/Berlin')).toBe('2026-03-02');
    expect(isoDayIn(lateUtc, 'America/New_York')).toBe('2026-03-01');
    expect(isoDayIn(lateUtc, 'UTC')).toBe('2026-03-01');
  });

  it('T-WEB-368: an unusable zone, or a formatter that says nothing, falls back to UTC', () => {
    const at = new Date('2026-03-01T23:30:00Z');
    expect(isoDayIn(at, 'Not/AZone')).toBe('2026-03-01');

    vi.spyOn(Intl.DateTimeFormat.prototype, 'formatToParts').mockReturnValue([]);
    expect(isoDayIn(at, 'Europe/Berlin')).toBe('2026-03-01');
  });

  it("T-WEB-368: today and the default zone come from the stored choice", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-30T22:30:00Z'));
    expect(todayLocal()).toBe('2026-07-01'), 'Berlin is already past midnight';
    expect(isoDayIn(new Date())).toBe('2026-07-01');
    localStorage.setItem('victus.timezone', 'UTC');
    expect(todayLocal()).toBe('2026-06-30');
    expect(todayLocal('Asia/Tokyo')).toBe('2026-07-01');
  });
});

describe('FormatService', () => {
  let format: FormatService;
  let unblock: (() => void) | null = null;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    format = TestBed.inject(FormatService);
  });

  afterEach(() => {
    unblock?.();
    unblock = null;
  });

  it('T-WEB-369: adopts a supported locale and zone and mirrors both for the next load', () => {
    format.adopt('en-US', 'America/New_York');
    expect(format.locale()).toBe('en-US');
    expect(format.timezone()).toBe('America/New_York');
    expect(localStorage.getItem('victus.locale')).toBe('en-US');
    expect(localStorage.getItem('victus.timezone')).toBe('America/New_York');
  });

  it('T-WEB-369: an unknown or missing choice falls back to the defaults', () => {
    format.adopt('tlh', undefined);
    expect(format.locale()).toBe(DEFAULT_LOCALE);
    expect(format.timezone()).toBe(DEFAULT_TIMEZONE);
    format.adopt(undefined, '');
    expect(format.locale()).toBe(DEFAULT_LOCALE);
    expect(format.timezone()).toBe(DEFAULT_TIMEZONE);
  });

  it('T-WEB-369: blocked storage still formats this session correctly', () => {
    unblock = blockLocalStorage();
    expect(() => format.adopt('en-GB', 'UTC')).not.toThrow();
    expect(format.locale()).toBe('en-GB');
    expect(format.timezone()).toBe('UTC');
  });

  it('T-WEB-370: writes numbers in the tenant convention', () => {
    format.adopt('de-DE', 'UTC');
    expect(format.number(1234.5, 1)).toBe('1.234,5');
    expect(format.number(1234.56)).toBe('1.235');
    format.adopt('en-GB', 'UTC');
    expect(format.number(1234.5, 1)).toBe('1,234.5');
  });

  it('T-WEB-370: writes a length of audio as a clock reading', () => {
    expect(format.duration(0)).toBe('0:00');
    expect(format.duration(42)).toBe('0:42');
    expect(format.duration(65.4)).toBe('1:05');
    expect(format.duration(3903)).toBe('1:05:03');
    expect(format.duration(-5)).toBe('0:00'), 'never a negative running time';
  });

  it('T-WEB-371: writes a day, a clock time and a moment in the tenant locale and zone', () => {
    format.adopt('en-GB', 'Europe/Berlin');
    expect(format.day('2026-09-12')).toBe('12/09/2026');
    expect(format.day('2026-09-12T10:00:00Z')).toBe('12/09/2026');
    expect(format.clock('2026-09-12T06:05:00Z')).toBe('08:05');
    expect(format.moment('2026-09-12T06:05:00Z')).toBe('12/09/2026, 08:05');

    format.adopt('de-DE', 'UTC');
    expect(format.day('2026-09-12')).toBe('12.9.2026');
    expect(format.clock('2026-09-12T06:05:00Z')).toBe('06:05');
  });

  it('T-WEB-371: hands back what it cannot read instead of printing "Invalid Date"', () => {
    expect(format.day('someday')).toBe('someday');
    expect(format.clock('not a time')).toBe('not a time');
    expect(format.moment('not a time')).toBe('not a time');
  });
});
