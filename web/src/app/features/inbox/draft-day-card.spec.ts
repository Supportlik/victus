// T-WEB-205…208: a drafted day in the inbox can be corrected, not only taken or left —
// unit, portion, estimate marks, product and meal are inputs, Save is separate from Accept,
// Accept all keeps every correction, and a refresh never undoes one (R84, R83).
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, TestRequest, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DraftListEntry, DraftSummary, LineItem, Product, Unit } from '../../api';
import { LineItemForm } from '../../shared/line-item-form';
import { DraftDayCard } from './draft-day-card';
import { By } from '@angular/platform-browser';

const UNITS: Unit[] = [
  { code: 'g', singular: 'g', plural: 'g', unit_type: 'mass' },
  { code: 'ml', singular: 'ml', plural: 'ml', unit_type: 'volume' },
  { code: 'tub', singular: 'tub', plural: 'tubs', unit_type: 'count' },
] as unknown as Unit[];

const ENTRY: DraftListEntry = { date: '2026-01-05', status: 'draft', draft_items: 2, kcal: 600, estimated_items: 1, created_by: 'agent' };

function item(id: number, consumable: number, name: string, meal: number): LineItem {
  return {
    id, meal_id: meal, position: 1, consumable_id: consumable, consumable_name: name, consumable_kind: 'product',
    amount: 100, unit_code: 'g', base_amount: 100, base_unit: 'g', estimated: true, amount_estimated: true,
    is_draft: true, confidence: 0.8, kcal: 300,
  };
}

const SUMMARY: DraftSummary = {
  date: '2026-01-05',
  markdown: 'two items',
  day: {
    date: '2026-01-05', status: 'draft', reliable: true, training_type: null, macros: { kcal: 600 }, target_band: null, findings: [],
    meals: [
      { id: 1, position: 1, name: 'Breakfast', totals: { kcal: 300 }, line_items: [item(41, 5, 'Skyr natural', 1)] },
      { id: 2, position: 2, name: 'Lunch', totals: { kcal: 300 }, line_items: [item(42, 6, 'Rice', 2)] },
    ],
  },
} as unknown as DraftSummary;

const PRODUCT = (id: number): Product =>
  ({ id, name: `product ${id}`, reference_amount: 100, reference_unit: 'g', verified: true, portions: [] }) as unknown as Product;

function text(el: Element | null): string {
  return (el?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

function button(el: Element, label: string): HTMLButtonElement {
  return Array.from(el.querySelectorAll('button')).find((b) => text(b) === label) as HTMLButtonElement;
}

describe('DraftDayCard', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])] });
    http = TestBed.inject(HttpTestingController);
  });

  /** The summary, then each row's product for its units. */
  function answer(f: ComponentFixture<DraftDayCard>, summary: DraftSummary = SUMMARY): void {
    http.expectOne('/api/v1/drafts/2026-01-05/summary').flush(summary);
    f.detectChanges();
    http.match((r) => /\/api\/v1\/products\/\d+$/.test(r.url)).forEach((r) => r.flush(PRODUCT(Number(r.request.url.split('/').pop()))));
    f.detectChanges();
  }

  async function mount(): Promise<ComponentFixture<DraftDayCard>> {
    const f = TestBed.createComponent(DraftDayCard);
    f.componentRef.setInput('entry', ENTRY);
    f.componentRef.setInput('units', UNITS);
    f.detectChanges();
    answer(f);
    await f.whenStable();
    return f;
  }

  function forms(f: ComponentFixture<DraftDayCard>): LineItemForm[] {
    return f.debugElement.queryAll(By.directive(LineItemForm)).map((d) => d.componentInstance as LineItemForm);
  }

  function row(f: ComponentFixture<DraftDayCard>, id: number): HTMLElement {
    return (f.nativeElement as HTMLElement).querySelector(`[data-item="${id}"]`) as HTMLElement;
  }

  it('T-WEB-205: offers unit, marks, product and meal as inputs, and saves without accepting', async () => {
    const f = await mount();
    const r = row(f, 41);
    // every value the agent suggested is a control on the card
    expect(r.querySelector('[aria-label="Unit"]')).not.toBeNull();
    expect(r.querySelector('[aria-label="Meal"]')).not.toBeNull();
    expect(r.querySelectorAll('input[type=checkbox]')).toHaveLength(2);
    expect(button(r, 'Change product')).toBeDefined();
    // nothing touched, nothing to save
    expect(button(r, 'Save').disabled).toBe(true);

    const form = forms(f)[0];
    form.estimated = false;
    form.unitCode.set('ml');
    f.componentRef.changeDetectorRef.markForCheck();
    f.detectChanges();
    expect(f.componentInstance.dirty()).toBe(true);
    const changed = vi.fn();
    f.componentInstance.changed.subscribe(changed);
    button(r, 'Save').click();
    const patch = http.expectOne('/api/v1/line-items/41');
    expect(patch.request.method).toBe('PATCH');
    expect(patch.request.body).toEqual({ amount: 100, unit_code: 'ml', portion_id: null, estimated: false, amount_estimated: true });
    patch.flush({});
    // saved, not accepted: no approval was asked for, and the card reads the draft again
    http.expectNone('/api/v1/line-items/41/approve');
    answer(f);
    expect(changed).not.toHaveBeenCalled();
    http.verify();
  });

  it('T-WEB-206: accepts one item with its corrections written first', async () => {
    const f = await mount();
    const form = forms(f)[1];
    form.amount = 180;
    form.meal = 1;
    const changed = vi.fn();
    f.componentInstance.changed.subscribe(changed);
    f.componentInstance.approve(f.componentInstance.rows()[1]);
    const patch = http.expectOne('/api/v1/line-items/42');
    expect(patch.request.body).toMatchObject({ amount: 180, meal_id: 1 });
    patch.flush({});
    const approve = http.expectOne('/api/v1/line-items/42/approve');
    expect(approve.request.body).toEqual({});
    approve.flush({});
    expect(changed).toHaveBeenCalledTimes(1);

    // untouched, Accept is one request, as before
    f.componentInstance.approve(f.componentInstance.rows()[0]);
    http.expectNone('/api/v1/line-items/41');
    http.expectOne('/api/v1/line-items/41/approve').flush({});
    http.verify();
  });

  it('T-WEB-207: Accept all keeps every correction, the meal included, and stops on a refusal', async () => {
    const f = await mount();
    const [first, second] = forms(f);
    first.meal = 2;
    second.amountEstimated = false;
    f.componentInstance.approveAll();
    const patches: TestRequest[] = http.match((r) => r.method === 'PATCH');
    expect(patches.map((p) => p.request.url).sort()).toEqual(['/api/v1/line-items/41', '/api/v1/line-items/42']);
    expect(patches.find((p) => p.request.url.endsWith('41'))!.request.body).toMatchObject({ meal_id: 2 });
    expect(patches.find((p) => p.request.url.endsWith('42'))!.request.body).toMatchObject({ amount_estimated: false });
    // one refusal: nothing is approved, and the card says why
    patches[0].flush({ title: 'Validation failed', status: 422, detail: 'another day' }, { status: 422, statusText: 'Unprocessable' });
    expect(patches[1].cancelled).toBe(true);
    http.expectNone('/api/v1/drafts/2026-01-05/approve');
    f.detectChanges();
    expect(text((f.nativeElement as HTMLElement).querySelector('.v-error'))).toContain('another day');
    expect(f.componentInstance.busy()).toBe(false);

    f.componentInstance.approveAll();
    http.match((r) => r.method === 'PATCH').forEach((p) => p.flush({}));
    const day = http.expectOne('/api/v1/drafts/2026-01-05/approve');
    expect(day.request.body).toEqual({ corrections: [], close: false });
    day.flush({});

    // an unfinished correction (a new meal without a name) is said before anything is sent
    first.meal = 'new';
    f.componentInstance.approveAll();
    http.expectNone((r) => r.method === 'PATCH');
    f.detectChanges();
    expect(text((f.nativeElement as HTMLElement).querySelector('.v-error'))).toContain('Complete the correction of Skyr natural first.');
    http.verify();
  });

  it('T-WEB-208: follows a newer entry unless a row was touched, and keeps the typing then', async () => {
    const f = await mount();
    // a refresh of the inbox hands the card a newer entry for the same day: it reads again
    f.componentRef.setInput('entry', { ...ENTRY, kcal: 650 });
    f.detectChanges();
    await f.whenStable();
    const newer = structuredClone(SUMMARY);
    newer.day.meals[0].line_items[0].amount = 120;
    answer(f, newer);
    expect(forms(f)[0].amount).toBe(120);

    // now a correction is typed, and the next entry leaves the card alone
    forms(f)[0].amount = 90;
    f.componentRef.setInput('entry', { ...ENTRY, kcal: 700 });
    f.detectChanges();
    await f.whenStable();
    http.expectNone('/api/v1/drafts/2026-01-05/summary');
    expect(forms(f)[0].amount).toBe(90);

    // a failing summary is shown, not swallowed
    f.componentInstance.load();
    http.expectOne('/api/v1/drafts/2026-01-05/summary').flush({ title: 'Not found', status: 404, detail: 'no draft' }, { status: 404, statusText: 'Not Found' });
    f.detectChanges();
    expect(text((f.nativeElement as HTMLElement).querySelector('.v-error'))).toContain('no draft');
    http.verify();
  });
});
