// T-WEB-047: the products page pages through the catalogue instead of showing its first
// window, so a product the reader cannot name is still reachable from here.
// T-WEB-060: a listed correction carries the value it replaces and the value it proposes,
// the product's other numbers beside them, and the buttons to decide it.
// T-WEB-061: a new product the agent met links to the day and the meal it was eaten in.
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it } from 'vitest';
import { Product, ProductProposal, ProductUsage } from '../../api';
import { ProductsPage } from './products-page';

/** A correction to one macro of a product that exists. */
const CORRECTION = {
  id: 'pr-1',
  product_id: 7,
  kind: 'update',
  product_name: 'Chia seeds',
  changes: { carbs: 8 },
  current: { carbs: 42 },
  rationale: 'the label says 8 g, net of fibre',
  source: 'label photo',
  status: 'pending',
  created_at: '2026-09-09T18:30:00Z',
} as unknown as ProductProposal;

/** A food nobody had logged before: no product yet, but already eaten on a day. */
const NEW_PRODUCT = {
  id: 'pr-2',
  product_id: null,
  kind: 'new',
  consumable_id: 99,
  product_name: 'Protein bar',
  changes: {
    name: 'Protein bar',
    brand: 'Foodspring',
    reference_amount: 100,
    reference_unit: 'g',
    kcal: 380,
    protein: 30,
    carbs: 28,
    fat: 14,
    fiber: 6,
    salt: 1,
    portions: [{ unit_code: 'bar', label: 'bar', amount: 60, amount_unit: 'g' }],
  },
  current: {},
  status: 'pending',
  created_at: '2026-09-09T20:00:00Z',
} as unknown as ProductProposal;

/** "The recipe changed on this date": approving opens a version, it does not rewrite one. */
const VERSION = {
  id: 'pr-3',
  product_id: 7,
  kind: 'version',
  product_name: 'Chia seeds',
  changes: { valid_from: '2026-09-01', kcal: 470 },
  current: { kcal: 486 },
  rationale: 'the new packaging declares 470 kcal',
  source: 'label photo',
  status: 'pending',
  created_at: '2026-09-09T19:00:00Z',
} as unknown as ProductProposal;

const CHIA = {
  id: 7,
  name: 'Chia seeds',
  brand: 'Davert',
  reference_amount: 100,
  reference_unit: 'g',
  verified: true,
  kcal: 486,
  protein: 17,
  carbs: 42,
  fat: 31,
  fiber: 34,
  salt: 1,
  portions: [],
} as unknown as Product;

function usage(id: number, entries: ProductUsage['entries'], itemCount: number): ProductUsage {
  return {
    product_id: id,
    entries,
    days: entries.length,
    total_base_amount: 0,
    total_kcal: 0,
    item_count: itemCount,
  };
}

/** The page with both kinds of proposal pending, every request answered. */
async function withProposals(http: HttpTestingController): Promise<HTMLElement> {
  const f = TestBed.createComponent(ProductsPage);
  f.detectChanges();
  http.expectOne((r) => r.url === '/api/v1/products').flush([CHIA]);
  http.expectOne((r) => r.url === '/api/v1/proposals').flush([CORRECTION, NEW_PRODUCT]);
  http.expectOne((r) => r.url === '/api/v1/products/7').flush(CHIA);
  http.expectOne((r) => r.url === '/api/v1/products/7/usage').flush(usage(7, [], 12));
  http.expectOne((r) => r.url === '/api/v1/products/99/usage').flush(
    usage(
      99,
      [
        {
          date: '2026-09-09',
          day_status: 'open',
          meal: 'Breakfast',
          line_item_id: 5,
          amount: 60,
          unit_code: 'g',
          base_amount: 60,
          base_unit: 'g',
          is_draft: true,
          estimated: false,
          kcal: 228,
          protein: 18,
        },
      ],
      1,
    ),
  );
  f.detectChanges();
  await f.whenStable();
  return f.nativeElement as HTMLElement;
}

function flat(el: Element | null): string {
  return (el?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

function page(from: number, count: number): Product[] {
  return Array.from({ length: count }, (_, i) => ({
    id: from + i,
    name: `Product ${String(from + i).padStart(3, '0')}`,
    reference_amount: 100,
    reference_unit: 'g',
    verified: true,
    portions: [],
  })) as unknown as Product[];
}

function rowNames(el: HTMLElement): string[] {
  return Array.from(el.querySelectorAll('.recent tbody tr td:first-child')).map((td) => td.textContent?.trim() ?? '');
}

function loadMore(el: HTMLElement): HTMLButtonElement | null {
  return el.querySelector('.paging button');
}

describe('ProductsPage', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])] });
    http = TestBed.inject(HttpTestingController);
  });

  it('asks for the next page and appends it', async () => {
    const f = TestBed.createComponent(ProductsPage);
    f.detectChanges();
    const first = http.expectOne((r) => r.url === '/api/v1/products');
    expect(first.request.params.get('limit')).toBe('50');
    expect(first.request.params.get('offset')).toBe('0');
    first.flush(page(1, 50));
    http.match(() => true).forEach((r) => r.flush([]));
    f.detectChanges();
    await f.whenStable();

    const el = f.nativeElement as HTMLElement;
    expect(rowNames(el)).toHaveLength(50);
    // a full page means there may be more, so the page offers to fetch it
    const button = loadMore(el);
    expect(button?.textContent?.trim()).toBe('Load more');

    button!.click();
    const next = http.expectOne((r) => r.url === '/api/v1/products');
    expect(next.request.params.get('offset')).toBe('50');
    next.flush(page(51, 20));
    f.detectChanges();
    await f.whenStable();

    expect(rowNames(el)).toHaveLength(70);
    expect(rowNames(el)[69]).toContain('Product 070');
    // a short page was the last one: nothing left to offer, and the count says so
    expect(loadMore(el)).toBeNull();
    expect(el.querySelector('.paging')?.textContent).toContain('70 products, the whole catalogue');
    http.verify();
  });

  it('says the catalogue is complete when the first page is short', async () => {
    const f = TestBed.createComponent(ProductsPage);
    f.detectChanges();
    http.expectOne((r) => r.url === '/api/v1/products').flush(page(1, 3));
    http.match(() => true).forEach((r) => r.flush([]));
    f.detectChanges();
    await f.whenStable();

    const el = f.nativeElement as HTMLElement;
    expect(loadMore(el)).toBeNull();
    expect(el.querySelector('.paging')?.textContent).toContain('3 products, the whole catalogue');
    http.verify();
  });

  it('lists a correction with both values, the other numbers and its buttons', async () => {
    const el = await withProposals(http);
    const proposal = el.querySelector('.proposal')!;

    // the field name alone said nothing: what carbs is now and what it would become
    const change = flat(proposal.querySelector('.changes li'));
    expect(change).toContain('carbs');
    expect(change).toMatch(/42\s*→\s*8 g/);
    // the five numbers that do not change are what make the sixth judgeable
    const facts = flat(proposal.querySelector('.facts'));
    expect(facts).toContain('per 100 g');
    expect(facts).toContain('kcal 486');
    expect(facts).toContain('protein 17');
    expect(facts).toContain('fiber 34');
    expect(flat(proposal)).toContain('12 line items use it');

    // the decision sits next to the values, and the link opens this proposal, not the page
    expect(proposal.querySelectorAll('button')).toHaveLength(2);
    const deeper = Array.from(proposal.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(deeper).toContain('/products/7#proposal-pr-1');
    http.verify();
  });

  // T-WEB-063: approving a version keeps every earlier day as it was; approving a
  // correction rewrites them. Both used to render as a list of changed fields, with the
  // date sitting among the values as though the day were one of them.
  it('says a version proposal opens a version, and does not list the date as a value', async () => {
    const f = TestBed.createComponent(ProductsPage);
    f.detectChanges();
    http.expectOne((r) => r.url === '/api/v1/products').flush([CHIA]);
    http.expectOne((r) => r.url === '/api/v1/proposals').flush([VERSION]);
    http.expectOne((r) => r.url === '/api/v1/products/7').flush(CHIA);
    http.expectOne((r) => r.url === '/api/v1/products/7/usage').flush(usage(7, [], 12));
    f.detectChanges();
    await f.whenStable();

    const proposal = (f.nativeElement as HTMLElement).querySelector('.proposal')!;
    expect(flat(proposal.querySelector('.from'))).toContain('Opens a new version from');
    expect(flat(proposal.querySelector('.from'))).toContain('keeps what it counted');

    // the values still read as values; the day is not one of them
    const changes = Array.from(proposal.querySelectorAll('.changes li')).map(flat);
    expect(changes.some((c) => /486\s*→\s*470/.test(c))).toBe(true);
    expect(changes.some((c) => c.includes('valid_from') || c.includes('2026-09-01'))).toBe(false);

    // and the button says what it will do, with no field-by-field link: a version is one act
    const labels = Array.from(proposal.querySelectorAll('button')).map((b) => flat(b));
    expect(labels).toContain('Open the version');
    expect(labels).not.toContain('Approve all');
    expect(proposal.querySelectorAll('a.v-btn')).toHaveLength(0);
    http.verify();
  });

  it('links a new product to the day and meal it was already eaten in', async () => {
    const el = await withProposals(http);
    const entry = el.querySelector('.new-product')!;

    // a `new` proposal has no product page; the day it was logged on is the evidence
    expect(entry.querySelector('.ate a')?.getAttribute('href')).toBe('/days/2026-09-09');
    const text = flat(entry);
    expect(text).toContain('Breakfast');
    expect(text).toContain('60 g');
    expect(text).toContain('draft');
    // what it is, next to where it came from
    expect(flat(entry.querySelector('.facts'))).toContain('kcal 380');
    expect(text).toContain('Foodspring');
    expect(text).toContain('bar 60 g');
    http.verify();
  });
});
