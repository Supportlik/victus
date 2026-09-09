// T-WEB-033: one capture, one form. Text alone is a capture, and there is no second
// way to save text next to the photo and voice buttons (R65).
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { CaptureInput } from './capture-input';

function saveButton(f: ComponentFixture<CaptureInput>): HTMLButtonElement {
  const el = f.nativeElement as HTMLElement;
  const found = Array.from(el.querySelectorAll('button')).filter((b) =>
    b.textContent?.trim().startsWith('Save capture'),
  );
  expect(found).toHaveLength(1);
  return found[0] as HTMLButtonElement;
}

describe('CaptureInput', () => {
  let http: HttpTestingController;
  let f: ComponentFixture<CaptureInput>;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    f = TestBed.createComponent(CaptureInput);
    f.componentRef.setInput('targetDate', '2026-01-05');
    f.detectChanges();
  });

  it('offers a single text box and nothing to save while it is empty', () => {
    const el = f.nativeElement as HTMLElement;
    expect(el.querySelectorAll('textarea')).toHaveLength(1);
    expect(saveButton(f).disabled).toBe(true);
  });

  it('sends text on its own as one capture for the day', () => {
    const area = (f.nativeElement as HTMLElement).querySelector('textarea')!;
    area.value = 'lunch, 400 g quark with berries';
    area.dispatchEvent(new Event('input'));
    f.detectChanges();

    const save = saveButton(f);
    expect(save.disabled).toBe(false);
    save.click();

    const req = http.expectOne('/api/v1/captures');
    const body = req.request.body as FormData;
    expect(body.get('text')).toBe('lunch, 400 g quark with berries');
    expect(body.get('target_date')).toBe('2026-01-05');
    expect(body.getAll('file')).toHaveLength(0);

    req.flush({
      id: 'c1', kind: 'text', captured_at: '2026-01-05T12:00:00Z', target_date: '2026-01-05',
      text: 'lunch, 400 g quark with berries', status: 'new', transcript: null,
      attachment_id: null, attachment_mime: null, attachments: [], created: true,
    });
    f.detectChanges();
    // the form is empty again, so the same note cannot be sent twice by accident
    expect((f.nativeElement as HTMLElement).querySelector('textarea')!.value).toBe('');
    expect(saveButton(f).disabled).toBe(true);
  });
});
