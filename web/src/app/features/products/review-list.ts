import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import { ApiClient, LineItem, Product } from '../../api';
import { I18nService } from '../../core/i18n.service';
import { describeError } from '../../core/problem';
import { isoDate, MacroPipe, shiftDate } from '../../shared/format';
import { ProductSearch } from '../../shared/product-search';

interface ReviewRow {
  date: string;
  meal: string;
  item: LineItem;
}

/**
 * Unlinked items: line items that point at an ad_hoc consumable.
 * Re-assigning keeps the quantity; nutrients follow the product from now on.
 */
@Component({
  selector: 'v-review-list',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, MacroPipe, ProductSearch],
  template: `
    <div class="v-page">
      <header class="v-page-head">
        <div><h2>{{ i18n.t('Review list') }}</h2><p class="sub">{{ i18n.t('Items that are not linked to a product yet. Assign them; the quantity stays, the nutrients follow the product.') }}</p></div>
        <div class="v-actions v-small v-muted">{{ i18n.t('Scanning {from} to {to}', { from, to }) }}</div>
      </header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
      @if (rows().length === 0 && !loading()) {
        <div class="v-empty">{{ i18n.t('Nothing to review. Every item in this range points at a product or a batch.') }}</div>
      }
      @if (target(); as t) {
        <div class="v-panel assign">
          <p>{{ i18n.t('Assign to a product:') }} <strong>{{ t.item.consumable_name }}</strong> <span class="v-small v-muted">({{ t.date }}, {{ t.meal }})</span></p>
          <v-product-search (picked)="assign(t, $event)" />
          <button type="button" class="v-btn quiet" (click)="target.set(null)">{{ i18n.t('Cancel') }}</button>
        </div>
      }
      <div class="v-scroll-x">
        <table class="v-table">
          <thead><tr><th>{{ i18n.t('Day') }}</th><th>{{ i18n.t('Meal') }}</th><th>{{ i18n.t('Item as logged') }}</th><th class="num">{{ i18n.t('Amount') }}</th><th class="num">kcal</th><th></th></tr></thead>
          <tbody>
            @for (r of rows(); track r.item.id) {
              <tr>
                <td><a [routerLink]="['/days', r.date]">{{ r.date }}</a></td><td>{{ r.meal }}</td>
                <td>{{ r.item.consumable_name }} <span class="v-small v-muted">{{ r.item.raw_text }}</span></td>
                <td class="num">{{ r.item.amount ?? r.item.base_amount }} {{ r.item.unit_code ?? r.item.base_unit }}</td>
                <td class="num">{{ r.item.kcal | macro: 'kcal' }}</td>
                <td><button type="button" class="v-btn small" (click)="target.set(r)">{{ i18n.t('Assign') }}</button></td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    </div>
  `,
  styles: `.assign { margin-bottom: 1rem; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.5rem; }`,
})
export class ReviewList {
  private readonly api = inject(ApiClient);
  readonly i18n = inject(I18nService);
  readonly to = isoDate(new Date());
  readonly from = shiftDate(this.to, -180);
  readonly rows = signal<ReviewRow[]>([]);
  readonly target = signal<ReviewRow | null>(null);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);

  constructor() {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.api.days(this.from, this.to).subscribe({
      next: (days) => {
        if (!days.length) {
          this.rows.set([]);
          this.loading.set(false);
          return;
        }
        forkJoin(days.map((d) => this.api.day(d.date))).subscribe({
          next: (full) => {
            const rows: ReviewRow[] = [];
            for (const d of full) for (const m of d.meals) for (const it of m.line_items) if (it.consumable_kind === 'ad_hoc') rows.push({ date: d.date, meal: m.name, item: it });
            this.rows.set(rows.sort((a, b) => (a.date < b.date ? 1 : -1)));
            this.loading.set(false);
          },
          error: (e: unknown) => {
            this.error.set(describeError(e));
            this.loading.set(false);
          },
        });
      },
      error: (e: unknown) => {
        this.error.set(describeError(e));
        this.loading.set(false);
      },
    });
  }

  assign(r: ReviewRow, p: Product): void {
    this.api.updateLineItem(r.item.id, { consumable_id: p.id }).subscribe({
      next: () => {
        this.rows.update((list) => list.filter((x) => x.item.id !== r.item.id));
        this.target.set(null);
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }
}
