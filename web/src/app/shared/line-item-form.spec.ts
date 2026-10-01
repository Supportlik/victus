// T-WEB-200…204: the edit panel offers every value the agent suggested as an input — the
// product (alternatives and a search), the meal, the portions of a pending proposal — and a
// refresh never throws away what was typed (R84, R83).
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LineItem, Product, ProductProposal, Unit } from '../api';
import { LineItemForm } from './line-item-form';

const UNITS: Unit[] = [
  { code: 'g', singular: 'g', plural: 'g', unit_type: 'mass' },
  { code: 'ml', singular: 'ml', plural: 'ml', unit_type: 'volume' },
  { code: 'piece', singular: 'piece', plural: 'pieces', unit_type: 'count' },
] as unknown as Unit[];

const MEALS = [
  { id: 1, name: 'Breakfast' },
  { id: 2, name: 'Lunch' },
];

const DRAFT: LineItem = {
  id: 31, meal_id: 1, position: 1, consumable_id: 5, consumable_name: 'Skyr natural', consumable_kind: 'product',
  amount: 1, unit_code: 'tub', portion_id: 9, base_amount: 400, base_unit: 'g', estimated: false, amount_estimated: true,
  is_draft: true, kcal: 252,
  alternatives: [
    { consumable_id: 5, name: 'Skyr natural', kind: 'product', tier: 3, score: 0.9 },
    { consumable_id: 6, name: 'Skyr vanilla', kind: 'product', tier: 3, score: 0.6 },
  ],
};

const SKYR: Product = {
  id: 5, name: 'Skyr natural', reference_amount: 100, reference_unit: 'g', verified: true, kcal: 63,
  portions: [{ id: 9, product_id: 5, unit_code: 'tub', label: 'tub', amount: 400, amount_unit: 'g', is_default: true }],
} as unknown as Product;

const QUARK: Product = {
  id: 8, name: 'Low-fat quark', reference_amount: 100, reference_unit: 'g', verified: true, kcal: 67, portions: [],
} as unknown as Product;

/** Logged against a food that has no product yet: a one-off with a pending proposal. */
const ONE_OFF: LineItem = {
  id: 32, meal_id: 2, position: 1, consumable_id: 77, consumable_name: 'Oat bar', consumable_kind: 'ad_hoc',
  amount: 50, unit_code: 'g', base_amount: 50, base_unit: 'g', estimated: true, amount_estimated: true,
  is_draft: true, kcal: 200,
};

const NEW_BAR = {
  id: 'pr-5', kind: 'new', consumable_id: 77, product_id: null, product_name: 'Oat bar', status: 'pending',
  changes: { name: 'Oat bar', kcal: 400, portions: [{ op: 'add', unit_code: 'piece', label: 'bar', amount: 45, amount_unit: 'g' }] },
  current: {}, created_at: '2026-01-05T08:00:00Z',
} as unknown as ProductProposal;

function text(el: Element | null): string {
  return (el?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

function button(el: Element, label: string): HTMLButtonElement {
  return Array.from(el.querySelectorAll('button')).find((b) => text(b) === label) as HTMLButtonElement;
}

describe('LineItemForm', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])] });
    http = TestBed.inject(HttpTestingController);
  });

  async function mount(item: LineItem, day: string | null = '2026-01-05'): Promise<ComponentFixture<LineItemForm>> {
    const f = TestBed.createComponent(LineItemForm);
    f.componentRef.setInput('item', item);
    f.componentRef.setInput('units', UNITS);
    f.componentRef.setInput('meals', MEALS);
    f.componentRef.setInput('day', day);
    f.detectChanges();
    await f.whenStable();
    return f;
  }

  it('T-WEB-200: changes the product from the agent’s alternatives or from a search', async () => {
    const f = await mount(DRAFT);
    http.expectOne('/api/v1/products/5').flush(SKYR);
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    button(el, 'Change product').click();
    f.detectChanges();
    // the alternative already chosen is not offered again
    const alts = Array.from(el.querySelectorAll('.alts button')).map(text);
    expect(alts).toEqual(['Skyr vanilla (60 %)']);

    // a search hit replaces it; the old product's portion does not carry over
    f.componentInstance.pickProduct(QUARK);
    f.detectChanges();
    http.expectOne('/api/v1/products/8').flush(QUARK);
    f.detectChanges();
    expect(text(el.querySelector('.picked .name'))).toBe('Low-fat quark');
    expect(f.componentInstance.unitCode()).toBe('g');
    f.componentInstance.amount = 250;
    const saved = vi.fn();
    f.componentInstance.saved.subscribe(saved);
    button(el, 'Save').click();
    const req = http.expectOne('/api/v1/line-items/31');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({
      amount: 250, unit_code: 'g', portion_id: null, estimated: false, amount_estimated: true, consumable_id: 8,
    });
    req.flush({ ...DRAFT, consumable_id: 8 });
    expect(saved).toHaveBeenCalled();

    // the alternative works the same way
    f.componentInstance.pickAlternative(6, 'Skyr vanilla', 'product');
    http.expectOne('/api/v1/products/6').flush({ ...QUARK, id: 6, name: 'Skyr vanilla' });
    expect(f.componentInstance.consumableId()).toBe(6);
    http.verify();
  });

  it('T-WEB-201: moves the item to another meal of its day, or to a new one', async () => {
    const f = await mount(DRAFT);
    http.expectOne('/api/v1/products/5').flush(SKYR);
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    const meal = el.querySelector('[aria-label="Meal"]') as HTMLSelectElement;
    expect(Array.from(meal.options).map(text)).toEqual(['Breakfast', 'Lunch', 'new meal…']);
    expect(f.componentInstance.dirty()).toBe(false);

    f.componentInstance.meal = 2;
    expect(f.componentInstance.dirty()).toBe(true);
    button(el, 'Save').click();
    const moved = http.expectOne('/api/v1/line-items/31');
    expect(moved.request.body).toMatchObject({ meal_id: 2, unit_code: 'tub', portion_id: 9 });
    moved.flush(DRAFT);

    // a new meal is created on the item's day first, then the item moves into it
    f.componentInstance.meal = 'new';
    f.detectChanges();
    expect(f.componentInstance.ready()).toBe(false);
    f.componentInstance.newMeal = 'Snack';
    // a plain field does not mark an OnPush view; the handler is what matters here
    f.componentInstance.save();
    const created = http.expectOne('/api/v1/days/2026-01-05/meals');
    expect(created.request.body).toEqual({ name: 'Snack' });
    created.flush({ id: 3, position: 3, name: 'Snack', line_items: [], totals: {} });
    expect(http.expectOne('/api/v1/line-items/31').request.body).toMatchObject({ meal_id: 3 });
    http.verify();
  });

  it('T-WEB-202: offers the portions a pending proposal brings for a one-off item', async () => {
    const f = await mount(ONE_OFF);
    const asked = http.expectOne((r) => r.url === '/api/v1/proposals');
    expect(asked.request.params.get('consumable_id')).toBe('77');
    asked.flush([NEW_BAR]);
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    const groups = Array.from(el.querySelectorAll('optgroup')).map((g) => g.getAttribute('label'));
    expect(groups).toEqual(['Weight and volume', 'Portions the proposal brings']);
    expect(Array.from(el.querySelectorAll('option')).map(text)).toContain('bar (45 g)');

    f.componentInstance.unitCode.set('proposed:0');
    f.componentInstance.amount = 2;
    f.detectChanges();
    // there is no portion row yet, so the piece weight becomes the weight
    expect(text(el.querySelector('.hint'))).toContain('Saved as 90 g until the product is approved.');
    button(el, 'Save').click();
    expect(http.expectOne('/api/v1/line-items/32').request.body).toEqual({
      amount: 90, unit_code: 'g', portion_id: null, estimated: true, amount_estimated: true,
    });

    // without a proposal, or when it cannot be read, a one-off has grams only
    const g = await mount({ ...ONE_OFF, id: 33, consumable_id: 78 });
    http.expectOne((r) => r.url === '/api/v1/proposals').flush('down', { status: 503, statusText: 'Unavailable' });
    g.detectChanges();
    expect(g.componentInstance.proposedPortions()).toEqual([]);
    http.match(() => true).forEach((r) => r.flush({}));
  });

  it('T-WEB-203: a refresh of the item keeps what was typed, and takes it when nothing was', async () => {
    const f = await mount(DRAFT);
    http.expectOne('/api/v1/products/5').flush(SKYR);
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    const amount = el.querySelector('[aria-label="Amount"]') as HTMLInputElement;
    amount.value = '2';
    amount.dispatchEvent(new Event('input'));
    f.detectChanges();

    // the same item, newer on the server: the panel keeps the typed 2 and says so
    f.componentRef.setInput('item', { ...DRAFT, amount: 3 });
    f.detectChanges();
    await f.whenStable();
    expect(f.componentInstance.amount).toBe(2);
    expect(text(el.querySelector('.kept'))).toContain('What you typed is kept');
    http.expectNone('/api/v1/products/5');

    // nothing typed: the newer values are simply shown
    const g = await mount(DRAFT);
    http.expectOne('/api/v1/products/5').flush(SKYR);
    g.componentRef.setInput('item', { ...DRAFT, amount: 3, estimated: true });
    g.detectChanges();
    await g.whenStable();
    http.expectOne('/api/v1/products/5').flush(SKYR);
    expect(g.componentInstance.amount).toBe(3);
    expect(g.componentInstance.estimated).toBe(true);
    expect(g.componentInstance.kept()).toBe(false);
    http.verify();
  });

  it('T-WEB-219: the echo of its own save is not a change made meanwhile', async () => {
    const f = await mount(DRAFT);
    http.expectOne('/api/v1/products/5').flush(SKYR);
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    const amount = el.querySelector('[aria-label="Amount"]') as HTMLInputElement;
    amount.value = '2';
    amount.dispatchEvent(new Event('input'));
    f.detectChanges();
    expect(f.componentInstance.dirty()).toBe(true);

    button(el, 'Save').click();
    const saved = { ...DRAFT, amount: 2, kcal: 504 };
    http.expectOne((r) => r.method === 'PATCH' && r.url === '/api/v1/line-items/31').flush(saved);
    await f.whenStable();
    expect(f.componentInstance.dirty()).toBe(false);

    // the live refresh brings the same item back: no warning, nothing held back
    f.componentRef.setInput('item', saved);
    f.detectChanges();
    await f.whenStable();
    http.match('/api/v1/products/5').forEach((r) => r.flush(SKYR));
    f.detectChanges();
    expect(f.componentInstance.kept()).toBe(false);
    expect(el.querySelector('.kept')).toBeNull();
    expect(f.componentInstance.amount).toBe(2);
  });

  it('T-WEB-204: shows a refusal of the save or of the new meal, and stays open', async () => {
    const f = await mount(DRAFT);
    http.expectOne('/api/v1/products/5').flush(SKYR);
    f.detectChanges();
    const el = f.nativeElement as HTMLElement;
    f.componentInstance.meal = 2;
    button(el, 'Save').click();
    http.expectOne('/api/v1/line-items/31').flush(
      { title: 'Validation failed', status: 422, detail: 'meal 2 is not part of 2026-01-05' },
      { status: 422, statusText: 'Unprocessable' },
    );
    f.detectChanges();
    expect(text(el.querySelector('.v-error'))).toContain('meal 2 is not part of 2026-01-05');
    expect(f.componentInstance.busy()).toBe(false);

    f.componentInstance.meal = 'new';
    f.componentInstance.newMeal = 'Snack';
    // a plain field does not mark an OnPush view; the handler is what matters here
    f.componentInstance.save();
    http.expectOne('/api/v1/days/2026-01-05/meals').flush(
      { title: 'Forbidden', status: 403, detail: "scope 'write' required" },
      { status: 403, statusText: 'Forbidden' },
    );
    f.detectChanges();
    expect(text(el.querySelector('.v-error'))).toContain("scope 'write' required");
    http.expectNone('/api/v1/line-items/31');

    // embedded, the panel has no buttons of its own: its host offers Save and Accept
    f.componentRef.setInput('embedded', true);
    f.detectChanges();
    expect(button(el, 'Save')).toBeUndefined();
    http.verify();
  });
});
