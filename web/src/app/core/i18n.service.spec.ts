// T-WEB-044: the interface language switches at runtime, and a missing translation
// falls back to correct English rather than showing a key (R78).
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { FormatService } from './format.service';
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

  // T-WEB-046: the server sends a key and its parameters, never a finished sentence, so
  // the interface can say it in its own language and with its own number format (R78).
  it('says a server sentence in the tenant language', () => {
    i18n.adopt('de');
    const format = TestBed.inject(FormatService);
    format.adopt('de-DE', 'Europe/Berlin');

    expect(i18n.msg({ key: '{n} days left', params: { n: 79 } })).toBe('79 Tage übrig');
    // a parameter that is one of our own words is translated with the sentence
    expect(
      i18n.msg({
        key: '{macro}: {source} declared, {balance} in the balance',
        params: { macro: 'protein', source: 102.5, balance: 113.1 },
      }),
    ).toBe('Eiweiß: 102,5 angegeben, 113,1 in der Bilanz');
    // and a number follows the tenant's convention, not the server's
    expect(
      i18n.msg({
        key: 'the items add up to {sum} kcal, the balance says {balance}',
        params: { sum: 1560, balance: 1902 },
      }),
    ).toBe('die Posten ergeben 1.560 kcal, die Bilanz sagt 1.902');
  });

  it('lets a frozen snapshot keep the sentence it was frozen with', () => {
    i18n.adopt('de');
    // Snapshots taken before this change hold the English sentence the server wrote; it
    // is shown as it is rather than as a missing key.
    expect(i18n.msg('79 days left')).toBe('79 days left');
    expect(i18n.msg(null)).toBe('');
  });

  it('translates the languages it ships', () => {
    i18n.adopt('es');
    expect(i18n.t('Today')).toBe('Hoy');

    i18n.adopt('fr');
    expect(i18n.t('Today')).toBe('Aujourd’hui');
  });

  it('ignores a language it does not ship and mirrors the choice for the next load', () => {
    i18n.adopt('kl');
    expect(i18n.language()).toBe(DEFAULT_LANGUAGE);

    i18n.adopt('de');
    expect(storedLanguage()).toBe('de');
  });
});
