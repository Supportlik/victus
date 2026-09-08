// T-WEB-032: the inbox lists open captures as cards with media, and the card actions
// (set day, discard, restore/delete) go through the API; typed text becomes a capture.
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it } from 'vitest';
import { Capture } from '../../api';
import { CapturesPage } from './captures-page';

const CAPTURES: Capture[] = [
  { id: 'c_audio', kind: 'audio', captured_at: '2026-01-05T07:41:00Z', target_date: null, text: null, status: 'new', transcript: 'a whole tub of skyr', attachment_id: 'att1', attachment_mime: 'audio/ogg' },
  { id: 'c_img', kind: 'image', captured_at: '2026-01-05T12:02:00Z', target_date: '2026-01-05', text: null, status: 'processed', transcript: null, attachment_id: 'att2', attachment_mime: 'image/jpeg' },
  { id: 'c_gone', kind: 'text', captured_at: '2026-01-04T12:02:00Z', target_date: null, text: 'old', status: 'discarded', transcript: null, attachment_id: null, attachment_mime: null },
];

function flushList(http: HttpTestingController): void {
  http.expectOne((r) => r.url === '/api/v1/captures' && r.method === 'GET').flush(CAPTURES);
  http.match(() => true).forEach((r) => r.flush([]));
}

function chip(el: HTMLElement, label: string): HTMLButtonElement {
  return Array.from(el.querySelectorAll('.chip')).find((b) => b.textContent?.trim().startsWith(label)) as HTMLButtonElement;
}

describe('CapturesPage', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])] });
    http = TestBed.inject(HttpTestingController);
  });

  it('shows open captures by default with transcript and audio, processed ones read-only under All', () => {
    const f = TestBed.createComponent(CapturesPage);
    f.detectChanges();
    flushList(http);
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    const audio = el.querySelector('[data-capture="c_audio"]')!;
    expect(audio.textContent).toContain('a whole tub of skyr');
    expect(audio.querySelector('audio')?.getAttribute('src')).toBe('/api/v1/attachments/att1');
    expect(el.querySelector('[data-capture="c_img"]')).toBeNull();
    chip(el, 'All').click();
    f.detectChanges();
    const img = el.querySelector('[data-capture="c_img"]')!;
    expect(img.querySelector('img')?.getAttribute('src')).toBe('/api/v1/attachments/att2');
    expect(img.querySelector('.actions')).toBeNull();
  });

  it('re-targets, discards and deletes through the card', () => {
    const f = TestBed.createComponent(CapturesPage);
    f.detectChanges();
    flushList(http);
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    const card = () => el.querySelector('[data-capture="c_audio"]')!;
    const button = (label: string) => Array.from(card().querySelectorAll('button')).find((b) => b.textContent?.trim().startsWith(label)) as HTMLButtonElement;
    button('Set day').click();
    f.detectChanges();
    const dateInput = card().querySelector('input[type="date"]') as HTMLInputElement;
    dateInput.value = '2026-01-05';
    dateInput.dispatchEvent(new Event('input'));
    f.detectChanges();
    button('Save').click();
    const patch = http.expectOne('/api/v1/captures/c_audio');
    expect(patch.request.method).toBe('PATCH');
    expect(patch.request.body).toEqual({ target_date: '2026-01-05' });
    patch.flush({ ...CAPTURES[0], target_date: '2026-01-05' });
    f.detectChanges();
    http.match(() => true).forEach((r) => r.flush([]));
    expect(card().querySelector('a[href="/days/2026-01-05"]')).not.toBeNull();

    button('Discard').click();
    const discard = http.expectOne('/api/v1/captures/c_audio');
    expect(discard.request.body).toEqual({ status: 'discarded' });
    discard.flush({ ...CAPTURES[0], target_date: '2026-01-05', status: 'discarded' });
    f.detectChanges();
    http.match(() => true).forEach((r) => r.flush([]));
    chip(el, 'Discarded').click();
    f.detectChanges();
    expect(card().textContent).toContain('deleted automatically after one day');
    button('Delete').click();
    f.detectChanges();
    button('Yes, delete').click();
    const del = http.expectOne('/api/v1/captures/c_audio');
    expect(del.request.method).toBe('DELETE');
    del.flush(null, { status: 204, statusText: 'No Content' });
    f.detectChanges();
    http.match(() => true).forEach((r) => r.flush([]));
    expect(el.querySelector('[data-capture="c_audio"]')).toBeNull();
  });

  it('defaults the day picker to today and reports a duplicate typed capture', () => {
    const f = TestBed.createComponent(CapturesPage);
    f.detectChanges();
    flushList(http);
    f.detectChanges();
    const cmp = f.componentInstance;
    expect(cmp.targetDate).toBe(new Date().toISOString().slice(0, 10));
    cmp.text = 'lunch: skyr';
    cmp.upload();
    const req = http.expectOne('/api/v1/captures');
    expect(req.request.method).toBe('POST');
    expect((req.request.body as FormData).get('text')).toBe('lunch: skyr');
    req.flush({ ...CAPTURES[2], id: 'c_new', status: 'new', text: 'lunch: skyr', created: false });
    f.detectChanges();
    expect((f.nativeElement as HTMLElement).querySelector('.v-notice')?.textContent).toContain('already exists');
  });
});
