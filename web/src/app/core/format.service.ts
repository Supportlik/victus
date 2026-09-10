import { Injectable, signal } from '@angular/core';

/** Locales the interface ships formatting data for; anything else falls back to the default. */
export const SUPPORTED_LOCALES = ['de-DE', 'en-GB', 'en-US'] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: SupportedLocale = 'de-DE';
export const DEFAULT_TIMEZONE = 'Europe/Berlin';

const LOCALE_KEY = 'victus.locale';
const TZ_KEY = 'victus.timezone';

/** Read the mirrored choice before Angular boots, where injection is not available yet. */
export function storedLocale(): SupportedLocale {
  try {
    const found = localStorage.getItem(LOCALE_KEY);
    return (SUPPORTED_LOCALES as readonly string[]).includes(found ?? '')
      ? (found as SupportedLocale)
      : DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}

export function storedTimezone(): string {
  try {
    return localStorage.getItem(TZ_KEY) || DEFAULT_TIMEZONE;
  } catch {
    return DEFAULT_TIMEZONE;
  }
}

/**
 * Today as an ISO day in the configured zone.
 *
 * `new Date().toISOString()` is UTC, so between midnight and the offset it names yesterday.
 * A free function, because routes and services outside an injection context need it too.
 */
export function todayLocal(timezone: string = storedTimezone()): string {
  return isoDayIn(new Date(), timezone);
}

/** An instant as the ISO day it falls on in `timezone`. */
export function isoDayIn(at: Date, timezone: string = storedTimezone()): string {
  try {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: timezone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(at);
    const get = (t: string) => parts.find((p) => p.type === t)?.value ?? '';
    const [y, m, d] = [get('year'), get('month'), get('day')];
    if (y && m && d) return `${y}-${m}-${d}`;
  } catch {
    /* an unusable zone falls through to UTC below */
  }
  return at.toISOString().slice(0, 10);
}

/**
 * How numbers and dates are written, and which zone a day is read in (R69).
 *
 * The truth lives in the tenant settings, but `LOCALE_ID` is fixed when Angular boots, so
 * the choice is mirrored into browser storage: the pipes pick it up on the next load, this
 * service applies it at once.
 */
@Injectable({ providedIn: 'root' })
export class FormatService {
  readonly locale = signal<SupportedLocale>(storedLocale());
  readonly timezone = signal(storedTimezone());

  /** Called after the settings are read, so the next load starts with the right locale. */
  adopt(locale: string | undefined, timezone: string | undefined): void {
    const wanted = (SUPPORTED_LOCALES as readonly string[]).includes(locale ?? '')
      ? (locale as SupportedLocale)
      : DEFAULT_LOCALE;
    this.locale.set(wanted);
    this.timezone.set(timezone || DEFAULT_TIMEZONE);
    try {
      localStorage.setItem(LOCALE_KEY, wanted);
      localStorage.setItem(TZ_KEY, this.timezone());
    } catch {
      /* storage blocked: this session is still formatted correctly */
    }
  }

  /** A number in the tenant's convention: 1.234,5 in German, 1,234.5 in English. */
  number(value: number, digits = 0): string {
    return value.toLocaleString(this.locale(), {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  /** A length of audio as a clock reading: `0:42`, `1:05:03`.
   *
   * The same everywhere, in every locale: a running time is read as a clock, not as a
   * localised number of seconds. */
  duration(seconds: number): string {
    const total = Math.max(0, Math.round(seconds));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor(total / 60) % 60;
    const pad = (n: number) => String(n).padStart(2, '0');
    return hours
      ? `${hours}:${pad(minutes)}:${pad(total % 60)}`
      : `${minutes}:${pad(total % 60)}`;
  }

  /** An ISO day (yyyy-mm-dd) written the way the tenant writes dates. */
  day(iso: string): string {
    const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
    if (!y || !m || !d) return iso;
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(this.locale(), { timeZone: 'UTC' });
  }

  /** The time of day of a stored UTC timestamp, on the tenant's clock. */
  clock(iso: string): string {
    const at = new Date(iso);
    if (Number.isNaN(at.getTime())) return iso;
    return at.toLocaleTimeString(this.locale(), {
      timeZone: this.timezone(),
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  /** A stored UTC timestamp, shown as the wall clock of the tenant's zone.
   *
   * To the minute: the seconds of a capture or a run are noise in a list of them. */
  moment(iso: string): string {
    const at = new Date(iso);
    if (Number.isNaN(at.getTime())) return iso;
    return at.toLocaleString(this.locale(), {
      timeZone: this.timezone(),
      dateStyle: 'short',
      timeStyle: 'short',
    });
  }
}
