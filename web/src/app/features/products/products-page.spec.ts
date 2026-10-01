// T-WEB-047: the products page pages through the catalogue instead of showing its first
// window, so a product the reader cannot name is still reachable from here.
// T-WEB-060: a listed correction carries the value it replaces and the value it proposes,
// the product's other numbers beside them, and the buttons to decide it.
// T-WEB-061: a new product the agent met links to the day and the meal it was eaten in.
// T-WEB-074: a proposal filed while the page is open appears on it, off the change stream.
// T-WEB-210…213: every proposed value is an input; Save amends, Approve sends `changes`,
// and a refresh never takes a typed correction away (R84).
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it } from 'vitest';
import { Product, ProductProposal, ProductUsage } from '../../api';
import { LiveService } from '../../core/live.service';
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

function inputOf(row: Element): HTMLInputElement {
  return row.querySelector('td:last-child input, td:last-child select') as HTMLInputElement;
}

/** The value of the editor's input for one field, found by its label. */
function valueOf(el: Element, field: string): string {
  return (el.querySelector(`v-proposal-editor [aria-label="${field}"]`) as HTMLInputElement).value;
}

/** Type into an input the way a person does, so ngModel takes it. */
function type(input: HTMLInputElement, value: string): void {
  input.value = value;
  input.dispatchEvent(new Event('input'));
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

    // the field name alone said nothing: what carbs is now and what it would become, the
    // proposed value an input a person can correct before deciding
    const row = proposal.querySelector('v-proposal-editor tbody tr')!;
    expect(flat(row)).toContain('carbs');
    expect(flat(row)).toContain('42');
    expect(inputOf(row).value).toBe('8');
    // the five numbers that do not change are what make the sixth judgeable
    const facts = flat(proposal.querySelector('.facts'));
    expect(facts).toContain('per 100 g');
    expect(facts).toContain('kcal 486');
    expect(facts).toContain('protein 17');
    expect(facts).toContain('fiber 34');
    expect(flat(proposal)).toContain('12 line items use it');

    // the decision sits next to the values, and the link opens this proposal, not the page
    expect(Array.from(proposal.querySelectorAll('button')).map(flat)).toEqual(['Approve all', 'Save corrections', 'Reject']);
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

    // the values still read as values; the day is not one of them, but its own input
    const rows = Array.from(proposal.querySelectorAll('v-proposal-editor tbody tr'));
    expect(rows.map(flat)).toEqual([expect.stringContaining('486')]);
    expect(inputOf(rows[0]).value).toBe('470');
    expect(rows.some((r) => flat(r).includes('valid_from'))).toBe(false);
    expect((proposal.querySelector('.valid-from input') as HTMLInputElement).value).toBe('2026-09-01');

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
    // what it is, next to where it came from — as inputs, since it has no product page
    expect(valueOf(entry, 'kcal')).toBe('380');
    expect(valueOf(entry, 'brand')).toBe('Foodspring');
    const portion = entry.querySelector('[data-portion="0"]')!;
    expect(Array.from(portion.querySelectorAll('input')).map((i) => i.value)).toEqual(['bar', 'bar', '60']);
    http.verify();
  });

  // A proposal the agent files while this page is open belongs on it. Finding out about it
  // by reloading the page is exactly what the change stream exists to replace.
  it('takes a proposal filed while the page is open off the stream', async () => {
    const f = TestBed.createComponent(ProductsPage);
    f.detectChanges();
    http.expectOne((r) => r.url === '/api/v1/products').flush([CHIA]);
    http.expectOne((r) => r.url === '/api/v1/proposals').flush([]);
    f.detectChanges();
    await f.whenStable();
    const el = f.nativeElement as HTMLElement;
    expect(el.querySelector('.pending')).toBeNull();

    TestBed.inject(LiveService).lastChange.set({
      cursor: 2,
      targets: [{ action: 'proposal.create', type: 'product_proposal', id: 'pr-1' }],
    });
    await f.whenStable();
    http.expectOne((r) => r.url === '/api/v1/products').flush([CHIA]);
    http.expectOne((r) => r.url === '/api/v1/proposals').flush([CORRECTION]);
    f.detectChanges();
    await f.whenStable();
    http.expectOne((r) => r.url === '/api/v1/products/7').flush(CHIA);
    http.expectOne((r) => r.url === '/api/v1/products/7/usage').flush(usage(7, [], 12));
    f.detectChanges();
    await f.whenStable();

    // nothing was being decided here, so it simply appeared: no notice, no reload
    expect(flat(el.querySelector('.pending'))).toContain('Chia seeds');
    expect(el.querySelector('.stale')).toBeNull();
    http.verify();
  });
  it('T-WEB-210: approves a correction with the value a person typed as changes', async () => {
    const f = TestBed.createComponent(ProductsPage);
    f.detectChanges();
    http.expectOne((r) => r.url === '/api/v1/products').flush([CHIA]);
    http.expectOne((r) => r.url === '/api/v1/proposals').flush([CORRECTION]);
    http.expectOne((r) => r.url === '/api/v1/products/7').flush(CHIA);
    http.expectOne((r) => r.url === '/api/v1/products/7/usage').flush(usage(7, [], 12));
    f.detectChanges();
    await f.whenStable();
    const el = f.nativeElement as HTMLElement;
    type(el.querySelector('v-proposal-editor [aria-label="carbs"]') as HTMLInputElement, '7.5');
    f.detectChanges();
    const approve = Array.from(el.querySelectorAll('v-proposal-editor button')).find((b) => flat(b) === 'Approve with corrections') as HTMLButtonElement;
    approve.click();
    const req = http.expectOne('/api/v1/proposals/pr-1/approve');
    expect(req.request.body).toEqual({ changes: { carbs: 7.5 } });
    req.flush({ ...CORRECTION, status: 'approved', changes: { carbs: 7.5 }, proposed: { carbs: 8 } });
    // the decided proposal leaves the list, and the catalogue is read again
    http.expectOne((r) => r.url === '/api/v1/products').flush([CHIA]);
    f.detectChanges();
    await f.whenStable();
    expect(el.querySelector('.proposal')).toBeNull();
    http.verify();
  });

  it('T-WEB-211: saves a new product’s corrected values without deciding, and shows a refusal', async () => {
    const f = TestBed.createComponent(ProductsPage);
    f.detectChanges();
    http.expectOne((r) => r.url === '/api/v1/products').flush([CHIA]);
    http.expectOne((r) => r.url === '/api/v1/proposals').flush([NEW_PRODUCT]);
    http.expectOne((r) => r.url === '/api/v1/products/99/usage').flush(usage(99, [], 0));
    f.detectChanges();
    await f.whenStable();
    const el = f.nativeElement as HTMLElement;
    const entry = el.querySelector('.new-product')!;
    type(entry.querySelector('[aria-label="name"]') as HTMLInputElement, 'Protein bar crunchy');
    type(entry.querySelector('[aria-label="salt"]') as HTMLInputElement, '');
    type(entry.querySelector('[data-portion="0"] [aria-label="Weight"]') as HTMLInputElement, '55');
    f.detectChanges();
    const save = Array.from(entry.querySelectorAll('button')).find((b) => flat(b) === 'Save corrections') as HTMLButtonElement;
    save.click();
    const req = http.expectOne('/api/v1/proposals/pr-2');
    expect(req.request.method).toBe('PATCH');
    // only what changed; a cleared field is withdrawn with null
    expect(req.request.body).toEqual({
      changes: {
        name: 'Protein bar crunchy',
        salt: null,
        portions: [{ unit_code: 'bar', label: 'bar', amount: 55, amount_unit: 'g' }],
      },
    });
    req.flush({ title: 'Validation failed', status: 422, detail: 'salt must be zero or more' }, { status: 422, statusText: 'Unprocessable' });
    f.detectChanges();
    expect(flat(entry.querySelector('.v-error'))).toContain('salt must be zero or more');
    // nothing was decided: the proposal is still listed, with what was typed
    expect(valueOf(entry, 'name')).toBe('Protein bar crunchy');

    save.click();
    const again = http.expectOne('/api/v1/proposals/pr-2');
    const amended = {
      ...NEW_PRODUCT,
      product_name: 'Protein bar crunchy',
      changes: { ...again.request.body.changes, brand: 'Foodspring' },
      proposed: NEW_PRODUCT.changes,
    } as ProductProposal;
    delete (amended.changes as Record<string, unknown>)['salt'];
    again.flush(amended);
    f.detectChanges();
    await f.whenStable();
    expect(flat(el.querySelector('.new-product strong'))).toBe('Protein bar crunchy');
    // the agent's own reading stays beside the corrected field
    expect(flat(entry)).toContain('agent: Protein bar');
    http.verify();
  });

  it('T-WEB-212: rejects from the editor, and keeps the proposal when the rejection fails', async () => {
    const f = TestBed.createComponent(ProductsPage);
    f.detectChanges();
    http.expectOne((r) => r.url === '/api/v1/products').flush([CHIA]);
    http.expectOne((r) => r.url === '/api/v1/proposals').flush([NEW_PRODUCT]);
    http.expectOne((r) => r.url === '/api/v1/products/99/usage').flush(usage(99, [], 0));
    f.detectChanges();
    await f.whenStable();
    const el = f.nativeElement as HTMLElement;
    const reject = Array.from(el.querySelectorAll('.new-product button')).find((b) => flat(b) === 'Reject') as HTMLButtonElement;
    reject.click();
    http.expectOne('/api/v1/proposals/pr-2/reject').flush({ title: 'Conflict', status: 409, detail: 'already approved' }, { status: 409, statusText: 'Conflict' });
    f.detectChanges();
    expect(flat(el.querySelector('.new-product .v-error'))).toContain('already approved');
    reject.click();
    http.expectOne('/api/v1/proposals/pr-2/reject').flush({ ...NEW_PRODUCT, status: 'rejected' });
    f.detectChanges();
    await f.whenStable();
    expect(el.querySelector('.new-product')).toBeNull();
    http.verify();
  });

  it('T-WEB-213: holds a refresh back while a correction is typed, and keeps the typing when shown', async () => {
    const f = TestBed.createComponent(ProductsPage);
    f.detectChanges();
    http.expectOne((r) => r.url === '/api/v1/products').flush([CHIA]);
    http.expectOne((r) => r.url === '/api/v1/proposals').flush([CORRECTION]);
    http.expectOne((r) => r.url === '/api/v1/products/7').flush(CHIA);
    http.expectOne((r) => r.url === '/api/v1/products/7/usage').flush(usage(7, [], 12));
    f.detectChanges();
    await f.whenStable();
    const el = f.nativeElement as HTMLElement;
    type(el.querySelector('v-proposal-editor [aria-label="carbs"]') as HTMLInputElement, '7');
    f.detectChanges();

    TestBed.inject(LiveService).lastChange.set({
      cursor: 3,
      targets: [{ action: 'proposal.amend', type: 'product_proposal', id: 'pr-1' }],
    });
    await f.whenStable();
    f.detectChanges();
    http.expectNone((r) => r.url === '/api/v1/proposals');
    expect(flat(el.querySelector('.stale'))).toContain('There is newer data.');

    const show = Array.from(el.querySelectorAll('.stale button')).find((b) => flat(b) === 'Show it') as HTMLButtonElement;
    show.click();
    http.expectOne((r) => r.url === '/api/v1/products').flush([CHIA]);
    http.expectOne((r) => r.url === '/api/v1/proposals').flush([{ ...CORRECTION, changes: { carbs: 9 } }]);
    http.match((r) => r.url.startsWith('/api/v1/products/7')).forEach((r) => r.flush(r.request.url.endsWith('usage') ? usage(7, [], 12) : CHIA));
    f.detectChanges();
    await f.whenStable();
    f.detectChanges();
    // the typed 7 survives the newer 9, and the editor says that it kept it
    expect(valueOf(el, 'carbs')).toBe('7');
    expect(flat(el.querySelector('v-proposal-editor'))).toContain('What you typed is kept');
    http.verify();
  });
});
