// T-WEB-062: a proposal's timestamp is written on the tenant's clock rather than sliced out
// of the stored ISO string, which showed the wrong hour and, after midnight, the wrong day.
// T-WEB-066: the density is on the page, so a reader can see whether this product has one.
// T-WEB-067: a portion refused for its unit offers the density field instead of naming it.
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it } from 'vitest';
import { Product, ProductProposal, Unit } from '../../api';
import { FormatService } from '../../core/format.service';
import { ProductDetail } from './product-detail';

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

/** Half past ten at night in London is half past midnight the next day in Berlin. */
const LATE_PROPOSAL = {
  id: 'pr-1',
  product_id: 7,
  kind: 'update',
  product_name: 'Chia seeds',
  changes: { carbs: 8 },
  current: { carbs: 42 },
  source: 'label photo',
  status: 'pending',
  created_at: '2026-09-09T22:30:00Z',
} as unknown as ProductProposal;

/** The proposal that arrived four times over MCP: an egg size written where a unit belongs. */
const BAD_PORTION = {
  id: 'pr-2',
  product_id: 7,
  kind: 'update',
  product_name: 'Chia seeds',
  changes: { portions: [{ op: 'add', unit_code: 'piece_s', label: 'Egg size S', amount: 44 }] },
  current: {},
  portion_plan: [
    {
      op: 'add',
      portion_id: null,
      values: { unit_code: 'piece_s', label: 'Egg size S', amount: 44, amount_unit: 'g' },
      current: null,
      used_by: 0,
      blocked: "there is no unit 'piece_s'; a size belongs in the portion's label; did you mean 'piece'?",
      reason: null,
    },
  ],
  source: 'voice note',
  status: 'pending',
  created_at: '2026-09-09T12:00:00Z',
} as unknown as ProductProposal;

/** A delete a person can approve: the row it removes, and how much depends on it. */
const GOOD_PORTION = {
  id: 'pr-3',
  product_id: 7,
  kind: 'update',
  product_name: 'Chia seeds',
  changes: { portions: [{ op: 'delete', portion_id: 12, reason: 'duplicates the pouch' }] },
  current: {},
  portion_plan: [
    {
      op: 'delete',
      portion_id: 12,
      values: {},
      current: { id: 12, product_id: 7, unit_code: 'tbsp', label: 'tbsp', amount: 750,
                 amount_unit: 'g', is_default: false },
      used_by: 0,
      blocked: null,
      reason: 'duplicates the pouch',
    },
  ],
  source: 'catalogue check',
  status: 'pending',
  created_at: '2026-09-09T12:05:00Z',
} as unknown as ProductProposal;

/** Sold by volume, spooned out by weight: the product the density exists for (R75). */
const SYRUP = {
  id: 9,
  name: 'Maple syrup',
  brand: 'Clarks',
  reference_amount: 100,
  reference_unit: 'ml',
  verified: true,
  kcal: 260,
  protein: 0,
  carbs: 65,
  fat: 0,
  fiber: 0,
  salt: 0.02,
  portions: [],
} as unknown as Product;

/** What the API answers a portion in the other unit with: the sentence and the field. */
const REFUSED = {
  type: 'about:blank',
  title: 'Validation failed',
  status: 422,
  detail:
    "this product's values are per 100 ml, so a portion must be in ml. Set a density to allow g.",
  errors: [{ field: 'density_g_per_ml', message: 'set it to convert g into ml' }],
};

/** The page with one product loaded; every request it fires on the way is answered. */
async function open(
  http: HttpTestingController,
  product: Product,
): Promise<ComponentFixture<ProductDetail>> {
  const f = TestBed.createComponent(ProductDetail);
  f.componentRef.setInput('id', String(product.id));
  f.componentInstance.units.set([
    { code: 'piece', singular: 'piece', plural: 'pieces', unit_type: 'count' },
  ] as unknown as Unit[]);
  f.detectChanges();
  http.expectOne((r) => r.url === `/api/v1/products/${product.id}`).flush(product);
  http.expectOne((r) => r.url === `/api/v1/products/${product.id}/versions`).flush([product]);
  http.expectOne((r) => r.url === `/api/v1/products/${product.id}/usage`).flush({
    product_id: product.id,
    entries: [],
    days: 0,
    total_base_amount: 0,
    total_kcal: 0,
    item_count: 0,
  });
  http.expectOne((r) => r.url === '/api/v1/captures').flush([]);
  http.expectOne((r) => r.url === '/api/v1/proposals').flush([]);
  f.detectChanges();
  await f.whenStable();
  return f;
}

function text(el: Element | null): string {
  return (el?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

describe('ProductDetail', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  it('writes the proposal timestamp on the tenant clock and anchors the proposal', async () => {
    TestBed.inject(FormatService).adopt('de-DE', 'Europe/Berlin');
    const f = TestBed.createComponent(ProductDetail);
    f.componentRef.setInput('id', '7');
    // the loader fetches units only when it holds none, and it reads that signal inside the
    // effect: seeded here, the page loads once instead of once per answer that arrives
    f.componentInstance.units.set([
      { code: 'g', singular: 'g', plural: 'g', unit_type: 'mass' },
    ] as unknown as Unit[]);
    f.detectChanges();

    http.expectOne((r) => r.url === '/api/v1/products/7').flush(CHIA);
    http.expectOne((r) => r.url === '/api/v1/captures').flush([]);
    http.expectOne((r) => r.url === '/api/v1/proposals').flush([LATE_PROPOSAL]);
    http.expectOne((r) => r.url === '/api/v1/products/7/versions').flush([CHIA]);
    http.expectOne((r) => r.url === '/api/v1/products/7/usage').flush({
      product_id: 7,
      entries: [],
      days: 0,
      total_base_amount: 0,
      total_kcal: 0,
      item_count: 0,
    });
    f.detectChanges();
    await f.whenStable();

    const el = f.nativeElement as HTMLElement;
    // the proposal is addressable, so the products list can link to this one
    const proposal = el.querySelector('#proposal-pr-1')!;
    expect(proposal).not.toBeNull();

    const stamp = proposal.querySelector('time')!;
    expect(stamp.getAttribute('datetime')).toBe('2026-09-09T22:30:00Z');
    const shown = stamp.textContent ?? '';
    // the zone moves it past midnight: the 10th at 00:30, not the 9th at 22:30
    expect(shown).toContain('00:30');
    expect(shown).toMatch(/10\.09\.(20)?26/);
    expect(shown).not.toContain('22:30');
    expect(shown).not.toContain('2026-09-09');
    http.verify();
  });
  // T-WEB-068: the server has read every line of a portion proposal against the catalogue
  // since 1.2.0, and the page showed none of it — a raw list of objects with an Apply
  // button and no reason, which is how four proposals naming units that do not exist came
  // to look ready to approve.
  it('shows what a portion proposal would do, and refuses to offer a blocked one', async () => {
    const f = TestBed.createComponent(ProductDetail);
    f.componentRef.setInput('id', '7');
    f.detectChanges();
    http.expectOne((r) => r.url === '/api/v1/products/7').flush(CHIA);
    http.expectOne((r) => r.url === '/api/v1/products/7/versions').flush([CHIA]);
    http.expectOne((r) => r.url === '/api/v1/products/7/usage').flush({
      product_id: 7, entries: [], days: 0, total_base_amount: 0, total_kcal: 0, item_count: 0,
    });
    http.expectOne((r) => r.url === '/api/v1/captures').flush([]);
    http.expectOne((r) => r.url === '/api/v1/proposals').flush([BAD_PORTION, GOOD_PORTION]);
    f.detectChanges();
    await f.whenStable();
    // the unit list is fetched for the portion editor, which this test does not open
    http.match((r) => r.url === '/api/v1/units').forEach((r) => r.flush([]));

    const el = f.nativeElement as HTMLElement;
    const blocked = el.querySelector('.plan li.blocked');
    expect(blocked).not.toBeNull();
    expect(text(blocked)).toContain('Egg size S');
    expect(text(blocked)).toContain("no unit 'piece_s'");
    expect(text(blocked)).toContain('cannot be approved');

    // the row it would remove is named, with the reason the actor gave
    const lines = Array.from(el.querySelectorAll('.plan li')).map(text);
    expect(lines.some((l) => l.includes('tbsp') && l.includes('750'))).toBe(true);
    expect(lines.some((l) => l.includes('duplicates the pouch'))).toBe(true);

    // and the button does not offer what the server would refuse
    const approve = Array.from(el.querySelectorAll('button')).filter((b) =>
      /Apply/.test(text(b)),
    );
    expect(approve.length).toBeGreaterThanOrEqual(2);
    expect((approve[0] as HTMLButtonElement).disabled).toBe(true);
    expect((approve[1] as HTMLButtonElement).disabled).toBe(false);
    http.verify();
  });

  it('says on the page whether the product carries a density', async () => {
    // the number is written in the tenant's convention, so the test fixes one
    TestBed.inject(FormatService).adopt('en-GB', 'Europe/London');
    const withOne = await open(http, { ...SYRUP, density_g_per_ml: 1.32 });
    const shown = text((withOne.nativeElement as HTMLElement).querySelector('.facts .density'));
    // the number as it is on the label, and what it is there for
    expect(shown).toContain('1.32 g/ml');
    expect(shown).toContain('converted');
    // and not among the six: the definition list holds nutrients only
    const facts = Array.from(
      (withOne.nativeElement as HTMLElement).querySelectorAll('.facts dl dt'),
    ).map((dt) => text(dt));
    expect(facts).toHaveLength(6);
    expect(facts.join(' ')).not.toContain('g/ml');
    http.verify();

    const without = await open(http, SYRUP);
    // the absence is a fact of its own: it is why grams will be refused below
    expect(text((without.nativeElement as HTMLElement).querySelector('.facts .density'))).toContain(
      'No density',
    );
    http.verify();
  });

  it('offers the density field when a portion is refused for its unit', async () => {
    const f = await open(http, SYRUP);
    const el = f.nativeElement as HTMLElement;

    f.componentInstance.np = {
      label: 'tbsp',
      unit_code: 'piece',
      amount: 20,
      amount_unit: 'g',
      is_default: false,
      weight_source: 'weighed',
    };
    f.componentInstance.addPortion();
    http
      .expectOne((r) => r.method === 'POST' && r.url === '/api/v1/products/9/portions')
      .flush(REFUSED, { status: 422, statusText: 'Unprocessable Content' });
    f.detectChanges();
    await f.whenStable();

    // the refusal is not a sentence about a field somewhere: it is the way there
    const offer = el.querySelector<HTMLButtonElement>('.needs-density button');
    expect(offer).not.toBeNull();
    expect(text(offer)).toBe('Set a density');
    expect(el.querySelector('.v-error.needs-density')).not.toBeNull();

    offer!.click();
    // the editor is what holds the field, so it opens on it
    f.detectChanges();
    http.expectOne((r) => r.url === '/api/v1/categories').flush([]);
    f.detectChanges();
    await f.whenStable();

    const field = el.querySelector<HTMLInputElement>('input[name="density_g_per_ml"]');
    expect(field).not.toBeNull();
    expect(document.activeElement).toBe(field);
    // and the refusal has nothing left to say once its remedy is on screen
    expect(el.querySelector('.needs-density')).toBeNull();
    http.verify();
  });
});
