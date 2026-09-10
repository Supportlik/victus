// T-WEB-062: a proposal's timestamp is written on the tenant's clock rather than sliced out
// of the stored ISO string, which showed the wrong hour and, after midnight, the wrong day.
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
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
});
