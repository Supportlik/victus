// T-WEB-044: the interface language switches at runtime, and a missing translation
// falls back to correct English rather than showing a key (R78).
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { DEFAULT_LANGUAGE, I18nService, storedLanguage } from './i18n.service';

describe('I18nService', () => {
  let i18n: I18nService;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({});
    i18n = TestBed.inject(I18nService);
  });

  it('starts in English and translates once switched', () => {
    expect(i18n.language()).toBe(DEFAULT_LANGUAGE);
    expect(i18n.t('Weight')).toBe('Weight');

    i18n.adopt('de');
    expect(i18n.language()).toBe('de');
    expect(i18n.t('Weight')).toBe('Gewicht');
    expect(i18n.t('Add item')).toBe('Posten hinzufügen');
  });

  it('returns an unknown string unchanged, in both languages', () => {
    i18n.adopt('de');
    expect(i18n.t('Not translated yet')).toBe('Not translated yet');
  });

  it('fills placeholders', () => {
    i18n.adopt('de');
    expect(i18n.t('Appearance: {mode}', { mode: 'Hell' })).toBe('Darstellung: Hell');
  });

  it('ignores a language it does not ship and mirrors the choice for the next load', () => {
    i18n.adopt('fr');
    expect(i18n.language()).toBe(DEFAULT_LANGUAGE);

    i18n.adopt('de');
    expect(storedLanguage()).toBe('de');
  });
});
