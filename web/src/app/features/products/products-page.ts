import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiClient, Product, ProductProposal } from '../../api';
import { I18nService } from '../../core/i18n.service';
import { describeError } from '../../core/problem';
import { MacroPipe } from '../../shared/format';
import { FoodIcon } from '../../shared/food-icon';
import { ProductSearch } from '../../shared/product-search';

@Component({
  selector: 'v-products-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, FormsModule, MacroPipe, ProductSearch, FoodIcon],
  template: `
    <div class="v-page">
      <header class="v-page-head">
        <div><h2>{{ i18n.t('Products') }}</h2><p class="sub">{{ i18n.t('Nutrients per 100 g or 100 ml. A corrected label fixes every day that used it.') }}</p></div>
        <div class="v-actions">
          <a class="v-btn" routerLink="/products/review">{{ i18n.t('Review list') }}</a>
          <a class="v-btn primary" routerLink="/products/new">{{ i18n.t('New product') }}</a>
        </div>
      </header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
      @if (corrections().length) {
        <section class="v-panel pending">
          <h3>{{ i18n.t('Waiting for your approval') }}</h3>
          <ul>
            @for (pr of corrections(); track pr.id) {
              <li><a [routerLink]="['/products', pr.product_id]">{{ pr.product_name ?? i18n.t('product {id}', { id: pr.product_id ?? '' }) }}</a> <span class="v-muted v-small">— {{ keys(pr).join(', ') }} · {{ pr.source }}</span></li>
            }
          </ul>
        </section>
      }
      @if (newProducts().length) {
        <section class="v-panel pending">
          <h3>{{ i18n.t('New products the agent met') }}</h3>
          <p class="v-small v-muted">{{ i18n.t('Already logged on the day it was eaten. Approve it to add it to your products; reject it and the meal keeps its values but nothing joins the catalogue.') }}</p>
          @for (pr of newProducts(); track pr.id) {
            <div class="new-product">
              <div><strong>{{ pr.product_name }}</strong> <span class="v-muted v-small">{{ values(pr) }}</span></div>
              @if (pr.rationale) { <p class="v-small">{{ pr.rationale }}</p> }
              @if (pr.source) { <p class="v-small v-muted">{{ pr.source }}</p> }
              <div class="v-actions">
                <button type="button" class="v-btn primary" (click)="decide(pr, true)" [disabled]="deciding()">{{ i18n.t('Approve') }}</button>
                <button type="button" class="v-btn" (click)="decide(pr, false)" [disabled]="deciding()">{{ i18n.t('Reject') }}</button>
              </div>
            </div>
          }
        </section>
      }
      <v-product-search (picked)="open($event)" />
      <section class="recent">
        <h3>{{ i18n.t('All products (A–Z)') }}</h3>
        @if (recent().length === 0) {
          <div class="v-empty">{{ i18n.t('Search above to find a product, or create one.') }}</div>
        } @else {
          <div class="v-scroll-x">
            <table class="v-table">
              <thead><tr><th>{{ i18n.t('Product') }}</th><th>{{ i18n.t('Brand') }}</th><th class="num">kcal</th><th class="num">P</th><th class="num">C</th><th class="num">F</th><th class="num">Fi</th><th class="num">S</th><th>{{ i18n.t('Source') }}</th></tr></thead>
              <tbody>
                @for (p of recent(); track p.id) {
                  <tr>
                    <td><v-food-icon [name]="p.name" [category]="p.category ?? null" kind="product" [icon]="p.icon" /> <a [routerLink]="['/products', p.id]">{{ p.name }}</a></td>
                    <td class="v-muted">{{ p.brand }}</td>
                    <td class="num">{{ p.kcal | macro: 'kcal' }}</td><td class="num">{{ p.protein | macro: 'protein' }}</td><td class="num">{{ p.carbs | macro: 'carbs' }}</td><td class="num">{{ p.fat | macro: 'fat' }}</td><td class="num">{{ p.fiber | macro: 'fiber' }}</td><td class="num">{{ p.salt | macro: 'salt' }}</td>
                    <td>
                      <span class="src">
                        @if (p.verified) { <span class="v-tag ok">{{ i18n.t('label') }}</span> } @else { <span class="v-tag warn">{{ i18n.t('estimate') }}</span> }
                        @if (p.source) { <span class="v-small v-muted">{{ p.source }}</span> }
                      </span>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      </section>
    </div>
  `,
  styles: `.src { display: inline-flex; align-items: center; gap: 0.45rem; }
    .recent { margin-top: 1.5rem; } .recent h3 { margin-bottom: 0.5rem; } .pending { margin-bottom: 1rem; border-color: var(--v-agent); } .pending ul { margin: 0.25rem 0 0; padding-left: 1.1rem; }
    .new-product { display: grid; gap: 0.35rem; padding-top: 0.5rem; border-top: 1px dashed var(--v-line); }
    .new-product .v-actions { justify-content: flex-start; }`,
})
export class ProductsPage {
  private readonly api = inject(ApiClient);
  readonly i18n = inject(I18nService);
  readonly recent = signal<Product[]>([]);
  readonly proposals = signal<ProductProposal[]>([]);
  readonly error = signal<string | null>(null);
  readonly deciding = signal(false);
  constructor() {
    this.api.products('', { limit: 25 }).subscribe({ next: (p) => this.recent.set(p), error: (e: unknown) => this.error.set(describeError(e)) });
    this.api.proposals().subscribe({ next: (p) => this.proposals.set(p), error: () => undefined });
  }
  keys(pr: ProductProposal): string[] {
    return Object.keys(pr.changes);
  }
  /** Proposals that change a product that already exists. */
  corrections(): ProductProposal[] {
    return this.proposals().filter((pr) => pr.kind !== 'new');
  }
  /** Proposals that would add a product; there is no product page to send you to yet. */
  newProducts(): ProductProposal[] {
    return this.proposals().filter((pr) => pr.kind === 'new');
  }
  values(pr: ProductProposal): string {
    const per = `${pr.changes['reference_amount'] ?? 100} ${pr.changes['reference_unit'] ?? 'g'}`;
    const shown = ['kcal', 'protein', 'carbs', 'fat', 'fiber', 'salt']
      .filter((k) => pr.changes[k] != null)
      .map((k) => `${k} ${pr.changes[k]}`)
      .join(' · ');
    return shown ? `— ${this.i18n.t('per {amount}', { amount: per })}: ${shown}` : '';
  }
  decide(pr: ProductProposal, approve: boolean): void {
    this.deciding.set(true);
    const call = approve ? this.api.approveProposal(pr.id) : this.api.rejectProposal(pr.id);
    call.subscribe({
      next: () => {
        this.proposals.update((all) => all.filter((x) => x.id !== pr.id));
        this.deciding.set(false);
        if (approve) {
          this.api.products('', { limit: 25 }).subscribe({ next: (p) => this.recent.set(p), error: () => undefined });
        }
      },
      error: (e: unknown) => {
        this.error.set(describeError(e));
        this.deciding.set(false);
      },
    });
  }
  open(p: Product): void {
    window.location.assign(`/products/${p.id}`);
  }
}
