// T-WEB-032: the inbox screen carries captures and drafts together; a drafted item shows the
// capture it came from and can be accepted on its own.
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it } from 'vitest';
import { Capture, DraftListEntry } from '../../api';
import { InboxPage } from './inbox-page';

const CAPTURES: Capture[] = [
  { id: 'c_audio', kind: 'audio', captured_at: '2026-01-05T07:41:00Z', target_date: '2026-01-05', text: null, status: 'assigned', transcript: 'a whole tub of skyr', attachment_id: 'att1', attachment_mime: 'audio/ogg' },
  { id: 'c_open', kind: 'text', captured_at: '2026-01-05T09:00:00Z', target_date: null, text: '20 g ham', status: 'new', transcript: null, attachment_id: null, attachment_mime: null },
];
const DRAFTS: DraftListEntry[] = [
  { date: '2026-01-05', status: 'draft', draft_items: 1, kcal: 252, estimated_items: 0, created_by: 'agent' },
];
const SUMMARY = {
  date: '2026-01-05',
  markdown: '### 2026-01-05\n\n| Meal | Item |\n|---|---|\n| Breakfast | Skyr |\n',
  day: {
    date: '2026-01-05',
    status: 'draft',
    reliable: null,
    training_type: null,
    macros: { kcal: 252, protein: 44, carbs: 16, fat: 1, fiber: 0, salt: 0.4 },
    has_drafts: true,
    weight_kg: null,
    weekday: 'Monday',
    meals: [
      {
        id: 1,
        position: 1,
        name: 'Breakfast',
        time: null,
        totals: { kcal: 252, protein: 44, carbs: 16, fat: 1, fiber: 0, salt: 0.4 },
        line_items: [
          {
            id: 11, meal_id: 1, position: 1, consumable_id: 42, consumable_name: 'Skyr natural',
            consumable_kind: 'product', amount: 1, unit_code: 'tub', base_amount: 400, base_unit: 'g',
            estimated: false, amount_estimated: false, is_draft: true, confidence: 0.95,
            rationale: 'always the whole tub', alternatives: [], raw_text: 'a whole tub of skyr',
            source_capture_id: 'c_audio', source_kind: 'transcript', category: 'Grundzutaten & Frisches',
            kcal: 252, protein: 44, carbs: 16, fat: 1, fiber: 0, salt: 0.4,
          },
        ],
      },
    ],
    target_band: null,
    zones: {},
    findings: [],
    notes: null,
  },
};

/** The page and the badge service both load captures and drafts; answer all of them. */
function flush(http: HttpTestingController): void {
  http.match((r) => r.url === '/api/v1/captures').forEach((r) => r.flush(CAPTURES));
  http.match((r) => r.url === '/api/v1/drafts').forEach((r) => r.flush(DRAFTS));
  http.match(() => true).forEach((r) => r.flush([]));
}

describe('InboxPage', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])] });
    http = TestBed.inject(HttpTestingController);
  });

  it('shows the drafted item with its source capture and open captures below', async () => {
    const f = TestBed.createComponent(InboxPage);
    f.detectChanges();
    flush(http);
    f.detectChanges();
    await f.whenStable();
    http.match((r) => r.url === '/api/v1/drafts/2026-01-05/summary').forEach((r) => r.flush(SUMMARY));
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    const row = el.querySelector('[data-item="11"]')!;
    expect(row.textContent).toContain('Skyr natural');
    expect(row.textContent).toContain('always the whole tub');
    // the capture that produced the item is shown next to it, read-only
    expect(row.querySelector('[data-capture="c_audio"] audio')?.getAttribute('src')).toBe('/api/v1/attachments/att1');
    expect(row.querySelector('[data-capture="c_audio"] .actions')).toBeNull();
    // the still unassigned capture appears in the capture list with its actions
    expect(el.querySelector('.cards [data-capture="c_open"] .actions')).not.toBeNull();
  });

  it('accepts a single drafted item', async () => {
    const f = TestBed.createComponent(InboxPage);
    f.detectChanges();
    flush(http);
    f.detectChanges();
    await f.whenStable();
    http.match((r) => r.url === '/api/v1/drafts/2026-01-05/summary').forEach((r) => r.flush(SUMMARY));
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    const accept = Array.from(el.querySelectorAll('[data-item="11"] button')).find((b) => b.textContent?.trim() === 'Accept') as HTMLButtonElement;
    accept.click();
    const req = http.expectOne('/api/v1/line-items/11/approve');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({});
    req.flush({ ...SUMMARY.day.meals[0].line_items[0], is_draft: false });
    f.detectChanges();
    http.match(() => true).forEach((r) => r.flush([]));
  });
});
