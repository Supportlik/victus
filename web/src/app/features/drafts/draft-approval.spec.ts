// T-WEB-003: draft approval — only changed items become corrections; close flag is sent.
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';
import { DraftSummary } from '../../api';
import { DraftApproval } from './draft-approval';

const summary: DraftSummary = {
  date: '2026-01-02',
  markdown: '## Draft\n| Meal | Item |\n|---|---|\n| Dinner | Chicken |',
  day: {
    date: '2026-01-02', status: 'draft', reliable: true, training_type: null, macros: { kcal: 900 }, target_band: null, findings: [],
    meals: [
      {
        id: 1, position: 1, name: 'Dinner', totals: { kcal: 900 },
        line_items: [
          { id: 21, meal_id: 1, position: 1, consumable_id: 5, consumable_name: 'Chicken', consumable_kind: 'product', amount: 400, unit_code: 'g', base_amount: 400, base_unit: 'g', estimated: true, amount_estimated: true, is_draft: true, confidence: 0.62, rationale: 'photo', kcal: 420,
            alternatives: [{ consumable_id: 8, name: 'Chicken breast raw', kind: 'product', tier: 3, score: 0.41 }] },
          { id: 22, meal_id: 1, position: 2, consumable_id: 6, consumable_name: 'Rice', consumable_kind: 'product', amount: 150, unit_code: 'g', base_amount: 150, base_unit: 'g', estimated: false, amount_estimated: false, is_draft: true, confidence: 0.95, kcal: 195 },
          { id: 23, meal_id: 1, position: 3, consumable_id: 7, consumable_name: 'Ketchup', consumable_kind: 'product', amount: 30, unit_code: 'g', base_amount: 30, base_unit: 'g', estimated: false, amount_estimated: false, is_draft: true, confidence: 0.9, kcal: 30 },
        ],
      },
    ],
  },
};

describe('DraftApproval', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DraftApproval],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
  });

  it('builds corrections only for edited, re-assigned or removed items and sends close', async () => {
    const fixture = TestBed.createComponent(DraftApproval);
    fixture.componentRef.setInput('date', '2026-01-02');
    await fixture.whenStable();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/api/v1/drafts/2026-01-02/summary').flush(summary);
    await fixture.whenStable();

    const cmp = fixture.componentInstance;
    expect(cmp.rows().length).toBe(3);
    cmp.rows()[0].amount = 300; // quantity corrected
    cmp.rows()[0].consumableId = 8; // other candidate chosen
    cmp.rows()[2].remove = true; // dropped
    cmp.close = true;

    expect(cmp.buildRequest()).toEqual({
      corrections: [
        { line_item_id: 21, amount: 300, consumable_id: 8 },
        { line_item_id: 23, delete: true },
      ],
      close: true,
    });

    vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    cmp.approve();
    const req = http.expectOne('/api/v1/drafts/2026-01-02/approve');
    expect(req.request.method).toBe('POST');
    expect(req.request.body.close).toBe(true);
    expect(req.request.body.corrections.length).toBe(2);
    req.flush(summary.day);
  });

  // T-WEB-056: the same edit panel as on the day, on the page where "the agent guessed,
  // I know better" happens most — and it has to work inside the approve form.
  it('corrects an item in place before the draft is taken over', async () => {
    const fixture = TestBed.createComponent(DraftApproval);
    fixture.componentRef.setInput('date', '2026-01-02');
    await fixture.whenStable();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/api/v1/units').flush([{ code: 'g', singular: 'g', plural: 'g', unit_type: 'mass' }]);
    http.expectOne('/api/v1/drafts/2026-01-02/summary').flush(summary);
    await fixture.whenStable();

    const el = fixture.nativeElement as HTMLElement;
    const row = [...el.querySelectorAll('tbody tr')].find((r) => r.textContent?.includes('Chicken'))!;
    ([...row.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'edit') as HTMLButtonElement).click();
    fixture.detectChanges();
    http.expectOne('/api/v1/products/5').flush({ id: 5, name: 'Chicken', reference_amount: 100, reference_unit: 'g', verified: false, portions: [] });
    await fixture.whenStable();

    const panel = el.querySelector('v-line-item-form')!;
    const boxes = [...panel.querySelectorAll('input[type=checkbox]')] as HTMLInputElement[];
    expect(boxes.map((b) => b.checked)).toEqual([true, true]);
    // the nutrients came off a label after all; the portion is still a guess
    boxes[0].click();
    fixture.detectChanges();
    ([...panel.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Save') as HTMLButtonElement).click();

    const req = http.expectOne('/api/v1/line-items/21');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ amount: 400, unit_code: 'g', portion_id: null, estimated: false, amount_estimated: true });
    req.flush({});
    // the panel closes and the corrections are rebuilt from the item as it now stands
    http.expectOne('/api/v1/drafts/2026-01-02/summary').flush(summary);
    await fixture.whenStable();
    expect(el.querySelector('v-line-item-form')).toBeNull();
  });

  it('renders the agent summary as HTML and alternatives as a select', async () => {
    const fixture = TestBed.createComponent(DraftApproval);
    fixture.componentRef.setInput('date', '2026-01-02');
    await fixture.whenStable();
    TestBed.inject(HttpTestingController).expectOne('/api/v1/drafts/2026-01-02/summary').flush(summary);
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.summary table')).not.toBeNull();
    expect(el.querySelectorAll('tbody select').length).toBe(1);
    expect(el.textContent).toContain('62 %');
  });
});
