// T-WEB-379: the language choice with blocked storage, and a server sentence without params.
import { TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it } from 'vitest';
import { blockLocalStorage } from '../../testing/blocked-storage';
import { DEFAULT_LANGUAGE, I18nService, storedLanguage } from './i18n.service';

describe('T-WEB-379: I18nService (coverage)', () => {
  let unblock: (() => void) | null = null;

  afterEach(() => {
    unblock?.();
    unblock = null;
  });

  it('T-WEB-379: starts in the language the browser remembered', () => {
    localStorage.setItem('victus.language', 'fr');
    expect(storedLanguage()).toBe('fr');
    expect(TestBed.inject(I18nService).language()).toBe('fr');
  });

  it('T-WEB-379: blocked storage starts in English and still switches this session', () => {
    unblock = blockLocalStorage();
    expect(storedLanguage()).toBe(DEFAULT_LANGUAGE);
    const i18n = TestBed.inject(I18nService);
    expect(() => i18n.adopt('de')).not.toThrow();
    expect(i18n.isGerman()).toBe(true);
    expect(i18n.t('Weight')).toBe('Gewicht');
  });

  it('T-WEB-379: a server sentence without parameters is translated as it is', () => {
    const i18n = TestBed.inject(I18nService);
    i18n.adopt('de');
    expect(i18n.msg({ key: 'Weight' } as never)).toBe('Gewicht');
    expect(i18n.msg(undefined)).toBe('');
    expect(i18n.msg('')).toBe('');
  });
});
