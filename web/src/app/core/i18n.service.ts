import { computed, Injectable, signal } from '@angular/core';
import { DE } from './i18n.de';

export const LANGUAGES = ['en', 'de'] as const;
export type Language = (typeof LANGUAGES)[number];

export const DEFAULT_LANGUAGE: Language = 'en';
const LANG_KEY = 'victus.language';

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
  t(text: string, params?: Record<string, string | number>): string {
    const dict = this.language() === 'de' ? DE : undefined;
    let out = dict?.[text] ?? text;
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        out = out.replaceAll(`{${key}}`, String(value));
      }
    }
    return out;
  }
}
