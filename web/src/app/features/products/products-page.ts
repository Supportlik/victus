import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiClient, Product, ProductProposal, ProductUsage, ProductUsageEntry } from '../../api';
import { FormatService } from '../../core/format.service';
import { I18nService } from '../../core/i18n.service';
import { describeError } from '../../core/problem';
import { formatAmount, MacroPipe } from '../../shared/format';
import { FoodIcon } from '../../shared/food-icon';
import { ProductSearch } from '../../shared/product-search';

/** Rows per request. Large enough that most catalogues arrive in one or two. */
const PAGE_SIZE = 50;

/** Occurrences listed under a proposal: enough to recognise the meal, not a history. */
const USAGE_SHOWN = 5;

/** The numbers a label carries, in the order it carries them. */
const MACROS = ['kcal', 'protein', 'carbs', 'fat', 'fiber', 'salt'] as const;

/** One field a correction changes, with the value it would replace. */
interface Change {
  field: string;
  label: string;
  before: string;
  after: string;
  unit: string;
}

/** One of the subject's own numbers, translated and formatted for a single line. */
interface Fact {
  label: string;
  value: string;
}

/** The unit a field is stated in; the field name already says "kcal". */
function unitOf(field: string, referenceUnit: string): string {
  if ((MACROS as readonly string[]).includes(field)) return field === 'kcal' ? '' : 'g';
  return field === 'reference_amount' ? referenceUnit : '';
}

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
          <p class="v-small v-muted">{{ i18n.t('Approve writes every value below. To decide field by field, open the product.') }}</p>
          @for (pr of corrections(); track pr.id) {
            <div class="proposal">
              <div class="subject">
                <a [routerLink]="['/products', pr.product_id]" [fragment]="'proposal-' + pr.id">{{ pr.product_name ?? i18n.t('product {id}', { id: pr.product_id ?? '' }) }}</a>
                @if (brandOf(pr); as brand) { <span class="v-muted v-small">{{ brand }}</span> }
                @if (pr.source) { <span class="v-muted v-small">{{ pr.source }}</span> }
                <time class="v-muted v-small" [attr.datetime]="pr.created_at">{{ format.moment(pr.created_at) }}</time>
              </div>
              <ul class="changes">
                @for (c of changes(pr); track c.field) {
                  <li><span class="v-muted">{{ c.label }}</span> <span class="before">{{ c.before }}</span> → <strong>{{ c.after }}</strong>@if (c.unit) { <span class="v-muted"> {{ c.unit }}</span> }</li>
                }
              </ul>
              <p class="facts v-small"><span class="v-muted">{{ perText(pr) }}</span>@for (f of facts(pr); track f.label) {<span class="fact"><span class="v-muted">{{ f.label }}</span> {{ f.value }}</span>}</p>
              <p class="v-small v-muted">{{ countText(pr) }}</p>
              @if (pr.rationale) { <p class="v-small">{{ pr.rationale }}</p> }
              <div class="v-actions">
                <button type="button" class="v-btn primary" (click)="decide(pr, true)" [disabled]="deciding()">{{ i18n.t('Approve all') }}</button>
                <button type="button" class="v-btn" (click)="decide(pr, false)" [disabled]="deciding()">{{ i18n.t('Reject') }}</button>
                <a class="v-btn quiet" [routerLink]="['/products', pr.product_id]" [fragment]="'proposal-' + pr.id">{{ i18n.t('Decide field by field…') }}</a>
              </div>
            </div>
          }
        </section>
      }
      @if (newProducts().length) {
        <section class="v-panel pending">
          <h3>{{ i18n.t('New products the agent met') }}</h3>
          <p class="v-small v-muted">{{ i18n.t('Already logged on the day it was eaten. Approve it to add it to your products; reject it and the meal keeps its values but nothing joins the catalogue.') }}</p>
          @for (pr of newProducts(); track pr.id) {
            <div class="new-product">
              <div class="subject">
                <strong>{{ pr.product_name }}</strong>
                @if (brandOf(pr); as brand) { <span class="v-muted v-small">{{ brand }}</span> }
                @if (pr.source) { <span class="v-muted v-small">{{ pr.source }}</span> }
                <time class="v-muted v-small" [attr.datetime]="pr.created_at">{{ format.moment(pr.created_at) }}</time>
              </div>
              <p class="facts v-small"><span class="v-muted">{{ perText(pr) }}</span>@for (f of facts(pr); track f.label) {<span class="fact"><span class="v-muted">{{ f.label }}</span> {{ f.value }}</span>}</p>
              @if (portions(pr).length) {
                <p class="v-small v-muted">{{ i18n.t('Portions') }}: {{ portions(pr).join(' · ') }}</p>
              }
              @if (usageOf(pr); as u) {
                @if (u.entries.length) {
                  <p class="v-small v-muted">{{ i18n.t('Where it was logged') }}</p>
                  <ul class="ate">
                    @for (e of u.entries; track e.line_item_id) {
                      <li>
                        <a [routerLink]="['/days', e.date]">{{ format.day(e.date) }}</a>
                        <span class="v-muted">{{ e.meal }}</span> {{ amountText(e) }}
                        @if (e.is_draft) { <span class="v-tag draft">{{ i18n.t('draft') }}</span> }
                      </li>
                    }
                  </ul>
                } @else {
                  <p class="v-small v-muted">{{ i18n.t('Not logged yet.') }}</p>
                }
              }
              @if (pr.rationale) { <p class="v-small">{{ pr.rationale }}</p> }
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
          <div class="paging">
            @if (more()) {
              <button type="button" class="v-btn" (click)="loadMore()" [disabled]="loading()">
                @if (loading()) { {{ i18n.t('Loading…') }} } @else { {{ i18n.t('Load more') }} }
              </button>
              <span class="v-muted v-small">{{ i18n.t('{n} products so far', { n: recent().length }) }}</span>
            } @else {
              <span class="v-muted v-small">{{ i18n.t('{n} products, the whole catalogue', { n: recent().length }) }}</span>
            }
          </div>
        }
      </section>
    </div>
  `,
  styles: `.src { display: inline-flex; align-items: center; gap: 0.45rem; }
    .recent { margin-top: 1.5rem; } .recent h3 { margin-bottom: 0.5rem; } .pending { margin-bottom: 1rem; border-color: var(--v-agent); } .pending ul { margin: 0.25rem 0 0; padding-left: 1.1rem; }
    .proposal, .new-product { display: grid; gap: 0.35rem; padding-top: 0.5rem; border-top: 1px dashed var(--v-line); }
    .proposal .v-actions, .new-product .v-actions { justify-content: flex-start; }
    .subject { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.5rem; }
    .changes { margin: 0; padding-left: 1.1rem; }
    .changes li { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.35rem; }
    .changes .before { text-decoration: line-through; color: var(--v-ink-3); }
    .facts { display: flex; flex-wrap: wrap; gap: 0.6rem; margin: 0; }
    .ate { margin: 0; padding-left: 1.1rem; }
    .ate li { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.4rem; }
    .paging { display: flex; flex-wrap: wrap; align-items: center; gap: 0.6rem; margin-top: 0.75rem; }`,
})
export class ProductsPage {
  private readonly api = inject(ApiClient);
  readonly i18n = inject(I18nService);
  readonly format = inject(FormatService);
  readonly recent = signal<Product[]>([]);
  readonly proposals = signal<ProductProposal[]>([]);
  /** The product a correction is about, by proposal id: its other numbers judge the changed one. */
  readonly subjects = signal<Map<string, Product>>(new Map());
  /** Where a proposal's subject was logged, by proposal id. */
  readonly usage = signal<Map<string, ProductUsage>>(new Map());
  readonly error = signal<string | null>(null);
  readonly deciding = signal(false);
  readonly loading = signal(false);
  readonly more = signal(false);
  constructor() {
    this.load(0);
    this.api.proposals().subscribe({
      next: (p) => {
        this.proposals.set(p);
        this.loadEvidence(p);
      },
      error: () => undefined,
    });
  }
  /**
   * One page of the catalogue, appended unless it is the first.
   *
   * A page shorter than asked for is the last one, which is why no count is fetched: the
   * heading says A–Z, and every name has to be reachable from here without searching for
   * a product you cannot name.
   */
  private load(offset: number, limit = PAGE_SIZE): void {
    this.loading.set(true);
    this.api.products('', { limit, offset }).subscribe({
      next: (page) => {
        this.recent.update((all) => (offset === 0 ? page : [...all, ...page]));
        this.more.set(page.length === limit);
        this.loading.set(false);
      },
      error: (e: unknown) => {
        this.error.set(describeError(e));
        this.loading.set(false);
      },
    });
  }
  loadMore(): void {
    this.load(this.recent().length);
  }
  /** Proposals that change a product that already exists. */
  corrections(): ProductProposal[] {
    return this.proposals().filter((pr) => pr.kind !== 'new');
  }
  /** Proposals that would add a product; there is no product page to send you to yet. */
  newProducts(): ProductProposal[] {
    return this.proposals().filter((pr) => pr.kind === 'new');
  }
  /** The consumable under decision: the product corrected, or the one-off logged against. */
  private subjectId(pr: ProductProposal): number | null {
    return (pr.kind === 'new' ? pr.consumable_id : pr.product_id) ?? null;
  }
  /**
   * What a proposal is decided on, one request per proposal and per kind.
   *
   * A correction needs the product itself: five of its six numbers are unchanged, and they
   * are what makes the sixth judgeable. Both kinds need the days the subject was logged on
   * — for a `new` proposal that is the whole evidence, since the values were already eaten.
   */
  private loadEvidence(proposals: ProductProposal[]): void {
    for (const pr of proposals) {
      const subject = this.subjectId(pr);
      if (subject == null) continue;
      this.api.productUsage(subject, USAGE_SHOWN).subscribe({
        next: (u) => this.usage.update((all) => new Map(all).set(pr.id, u)),
        error: () => undefined,
      });
      if (pr.kind !== 'new') {
        this.api.product(subject).subscribe({
          next: (p) => this.subjects.update((all) => new Map(all).set(pr.id, p)),
          error: () => undefined,
        });
      }
    }
  }
  /** Where the subject's own values stand: on the product, or in the proposal itself. */
  private valuesOf(pr: ProductProposal): Record<string, unknown> {
    if (pr.kind === 'new') return pr.changes;
    const p = this.subjects().get(pr.id);
    return p ? (p as unknown as Record<string, unknown>) : {};
  }
  /** A value as it is read: a number stays a number, a list is counted, a flag is a word. */
  private text(value: unknown): string {
    if (value === null || value === undefined) return '–';
    if (Array.isArray(value)) return this.i18n.t('{n} entries', { n: value.length });
    if (typeof value === 'number') return formatAmount(value);
    if (typeof value === 'boolean') return this.i18n.t(value ? 'yes' : 'no');
    return String(value);
  }
  /** What the numbers are stated per: "per 100 g", "per 100 ml". */
  perText(pr: ProductProposal): string {
    const values = this.valuesOf(pr);
    const amount = Number(values['reference_amount'] ?? 100);
    return this.i18n.t('per {amount}', {
      amount: `${formatAmount(amount)} ${String(values['reference_unit'] ?? 'g')}`,
    });
  }
  brandOf(pr: ProductProposal): string {
    const brand = this.valuesOf(pr)['brand'];
    return brand ? String(brand) : '';
  }
  /** kcal and the five macros of the subject, whether they change or not. */
  facts(pr: ProductProposal): Fact[] {
    const values = this.valuesOf(pr);
    return MACROS.map((key) => ({ label: this.i18n.t(key), value: this.text(values[key]) }));
  }
  /** The fields a correction changes, each with the value it replaces. */
  changes(pr: ProductProposal): Change[] {
    const unit = String(this.valuesOf(pr)['reference_unit'] ?? 'g');
    return Object.keys(pr.changes).map((field) => ({
      field,
      label: this.i18n.t(field),
      before: this.text(pr.current[field]),
      after: this.text(pr.changes[field]),
      unit: unitOf(field, unit),
    }));
  }
  usageOf(pr: ProductProposal): ProductUsage | null {
    return this.usage().get(pr.id) ?? null;
  }
  /** How much already depends on the values under decision. */
  countText(pr: ProductProposal): string {
    const found = this.usageOf(pr);
    if (!found) return '';
    const n = found.item_count ?? found.entries.length;
    if (n === 0) return this.i18n.t('Not logged yet.');
    return n === 1 ? this.i18n.t('1 line item uses it') : this.i18n.t('{n} line items use it', { n });
  }
  /** An occurrence in the unit it was logged in, not the one it was converted to. */
  amountText(e: ProductUsageEntry): string {
    return `${formatAmount(e.amount ?? e.base_amount)} ${this.i18n.t(e.unit_code ?? e.base_unit)}`;
  }
  /** Piece weights a `new` proposal brings with it, so "1 bar" means something after approval. */
  portions(pr: ProductProposal): string[] {
    const proposed = pr.changes['portions'];
    if (!Array.isArray(proposed)) return [];
    return (proposed as Record<string, unknown>[]).map((po) => {
      const label = this.i18n.t(String(po['label'] ?? po['unit_code'] ?? ''));
      return `${label} ${formatAmount(Number(po['amount']))} ${String(po['amount_unit'] ?? 'g')}`;
    });
  }
  /** A decided proposal keeps nothing: its evidence would outlive the row it belonged to. */
  private forget(pr: ProductProposal): void {
    this.subjects.update((all) => {
      const next = new Map(all);
      next.delete(pr.id);
      return next;
    });
    this.usage.update((all) => {
      const next = new Map(all);
      next.delete(pr.id);
      return next;
    });
  }
  decide(pr: ProductProposal, approve: boolean): void {
    this.deciding.set(true);
    const call = approve ? this.api.approveProposal(pr.id) : this.api.rejectProposal(pr.id);
    call.subscribe({
      next: () => {
        this.proposals.update((all) => all.filter((x) => x.id !== pr.id));
        this.forget(pr);
        this.deciding.set(false);
        if (approve) {
          // the approved product joins the catalogue: reload what is on screen, plus it
          this.load(0, Math.max(PAGE_SIZE, this.recent().length + 1));
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
