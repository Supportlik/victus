import { computed, Injectable, signal } from '@angular/core';
import type { Message } from '../api/models';
import { storedLocale } from './format.service';
import { DE } from './i18n.de';
import { ES } from './i18n.es';
import { FR } from './i18n.fr';

export const LANGUAGES = ['en', 'de', 'es', 'fr'] as const;
export type Language = (typeof LANGUAGES)[number];

export const DEFAULT_LANGUAGE: Language = 'en';
const LANG_KEY = 'victus.language';

/** English has no dictionary: it is what the templates already say. */
const DICTS: Partial<Record<Language, Record<string, string>>> = { de: DE, es: ES, fr: FR };

/** Read the mirrored choice before Angular boots, where injection is unavailable. */
export function storedLanguage(): Language {
  try {
    const found = localStorage.getItem(LANG_KEY);
    return (LANGUAGES as readonly string[]).includes(found ?? '')
      ? (found as Language)
      : DEFAULT_LANGUAGE;
  } catch {
    return DEFAULT_LANGUAGE;
  }
}

/**
 * The interface language, switchable at runtime (R78).
 *
 * The English string is its own key. That keeps the templates readable and makes a missing
 * translation fall back to correct English rather than showing a key, which is the failure
 * mode people actually notice. `scripts/check_translations.py` reports what is missing, so
 * the fallback does not quietly become permanent.
 *
 * Read `t()` from templates rather than through a pipe: it touches the language signal, so
 * a switch re-renders exactly the views that use it.
 */
@Injectable({ providedIn: 'root' })
export class I18nService {
  readonly language = signal<Language>(storedLanguage());
  readonly isGerman = computed(() => this.language() === 'de');

  /** Called after the settings are read, so the next load starts in the right language. */
  adopt(language: string | undefined): void {
    const wanted = (LANGUAGES as readonly string[]).includes(language ?? '')
      ? (language as Language)
      : DEFAULT_LANGUAGE;
    this.language.set(wanted);
    try {
      localStorage.setItem(LANG_KEY, wanted);
    } catch {
      /* storage blocked: this session is still translated */
    }
  }

  /**
   * Translate one string. `params` fills `{name}` placeholders.
   *
   * An unknown string is returned as it came in, so a template that has not been
   * translated yet reads as English instead of breaking.
   */
  /**
   * A sentence the server left to us: its key and the values that belong in it.
   *
   * The server no longer writes these out — "79 days left" could only ever be English.
   * Three details: a frozen snapshot still holds the old formatted sentence, which passes
   * through as it is rather than showing as a missing key; a parameter that is one of our
   * own words (a macro name, a unit) is translated too, so "protein: 102.5 declared" does
   * not stay half English; and a number is written the way this tenant writes numbers,
   * because the server has no business deciding between 1,560 and 1.560 (R69).
   */
  msg(message: Message | string | null | undefined): string {
    if (!message) return '';
    if (typeof message === 'string') return this.t(message);
    const params = Object.fromEntries(
      Object.entries(message.params ?? {}).map(([key, value]) => [
        key,
        typeof value === 'string'
          ? this.t(value)
          : value.toLocaleString(storedLocale(), { maximumFractionDigits: 2 }),
      ]),
    );
    return this.t(message.key, params);
  }

  t(text: string, params?: Record<string, string | number>): string {
    const dict = DICTS[this.language()];
    let out = dict?.[text] ?? text;
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        out = out.replaceAll(`{${key}}`, String(value));
      }
    }
    return out;
  }
}
