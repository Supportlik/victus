import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ApiClient, Capture, Portion, Product, ProductProposal, ProductUsage, Unit } from '../../api';
import { todayLocal } from '../../core/format.service';
import { I18nService } from '../../core/i18n.service';
import { describeError } from '../../core/problem';
import { CaptureCard } from '../../shared/capture-card';
import { CaptureInput } from '../../shared/capture-input';
import { MacroPipe } from '../../shared/format';
import { ProductForm } from './product-form';

@Component({
  selector: 'v-product-detail',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, FormsModule, MacroPipe, ProductForm, CaptureInput, CaptureCard, DecimalPipe],
  template: `
    <div class="v-page">
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
      @if (product(); as p) {
        <header class="v-page-head">
          <div>
            <a routerLink="/products" class="v-small">← {{ i18n.t('Products') }}</a>
            <h2>{{ p.name }}</h2>
            <p class="sub">{{ p.brand }} @if (p.verified) { <span class="v-tag ok">values from the label</span> } @else { <span class="v-tag warn">estimate</span> } @if (p.ean) { <span class="v-muted v-small">EAN {{ p.ean }}</span> }</p>
            @if (p.valid_from || p.valid_until) {
              <p class="v-small v-muted">{{ i18n.t('These values apply {range}.', { range: validity(p) }) }}</p>
            }
          </div>
          <div class="v-actions">
            <button type="button" class="v-btn" (click)="editing.set(!editing())">{{ editing() ? i18n.t('Close editor') : i18n.t('Edit') }}</button>
            <button type="button" class="v-btn" (click)="startVersion(p)">{{ i18n.t('Values changed…') }}</button>
            <button type="button" class="v-btn danger" (click)="remove()">{{ i18n.t('Delete') }}</button>
          </div>
        </header>

        @if (editing()) {
          <div class="v-panel"><v-product-form [product]="p" (saved)="onSaved($event)" (cancelled)="editing.set(false)" /></div>
        } @else {
          <section class="facts v-panel">
            <h3>{{ i18n.t('Per {amount} {unit}', { amount: p.reference_amount, unit: p.reference_unit }) }}</h3>
            <dl>
              <div><dt>kcal</dt><dd>{{ p.kcal | macro: 'kcal' }}</dd></div>
              <div><dt>{{ i18n.t('Protein') }}</dt><dd>{{ p.protein | macro: 'protein' }} g</dd></div>
              <div><dt>{{ i18n.t('Carbs') }}</dt><dd>{{ p.carbs | macro: 'carbs' }} g</dd></div>
              <div><dt>{{ i18n.t('Fat') }}</dt><dd>{{ p.fat | macro: 'fat' }} g</dd></div>
              <div><dt>{{ i18n.t('Fiber') }}</dt><dd>{{ p.fiber | macro: 'fiber' }} g</dd></div>
              <div><dt>{{ i18n.t('Salt') }}</dt><dd>{{ p.salt | macro: 'salt' }} g</dd></div>
            </dl>
            @if (p.source) { <p class="v-small v-muted">{{ i18n.t('Source') }}: {{ p.source }}</p> }
            @if (p.note) { <p class="v-small">{{ p.note }}</p> }
          </section>
        }

        @if (versionForm()) {
          <section class="v-panel newver">
            <h3>{{ i18n.t('Since when do the new values apply?') }}</h3>
            <p class="v-small v-muted">{{ i18n.t('Use this when the product itself changed: a reformulated recipe, a different supplier, a new label. From that day on the values below count; every day before it keeps the numbers it has now, so nothing you already logged moves. Leave a field empty to carry the current value over.') }}</p>
            <div class="v-form-row">
              <label class="v-field"><span>{{ i18n.t('Valid from') }}</span><input type="date" name="vf" [(ngModel)]="vf" /></label>
              <label class="v-field"><span>{{ i18n.t('kcal per 100 {unit}', { unit: p.reference_unit }) }}</span><input type="number" name="vkcal" step="0.1" [(ngModel)]="vkcal" [placeholder]="p.kcal ?? ''" /></label>
              <label class="v-field"><span>{{ i18n.t('Protein') }}</span><input type="number" name="vprot" step="0.1" [(ngModel)]="vprotein" [placeholder]="p.protein ?? ''" /></label>
              <label class="v-field"><span>{{ i18n.t('Carbs') }}</span><input type="number" name="vcarb" step="0.1" [(ngModel)]="vcarbs" [placeholder]="p.carbs ?? ''" /></label>
              <label class="v-field"><span>{{ i18n.t('Fat') }}</span><input type="number" name="vfat" step="0.1" [(ngModel)]="vfat" [placeholder]="p.fat ?? ''" /></label>
              <label class="v-field"><span>{{ i18n.t('Fiber') }}</span><input type="number" name="vfib" step="0.1" [(ngModel)]="vfiber" [placeholder]="p.fiber ?? ''" /></label>
              <label class="v-field"><span>{{ i18n.t('Salt') }}</span><input type="number" name="vsalt" step="0.1" [(ngModel)]="vsalt" [placeholder]="p.salt ?? ''" /></label>
              <label class="v-field wide"><span>{{ i18n.t('Where the new values come from') }}</span><input name="vsrc" [(ngModel)]="vsource" [placeholder]="i18n.t('new label, September 2026')" /></label>
            </div>
            <div class="v-actions">
              <button type="button" class="v-btn primary" (click)="saveVersion(p)" [disabled]="!vf || saving()">{{ i18n.t('Save new version') }}</button>
              <button type="button" class="v-btn quiet" (click)="versionForm.set(false)">{{ i18n.t('Cancel') }}</button>
            </div>
          </section>
        }

        @if (versions().length > 1) {
          <section class="v-panel history">
            <h3>{{ i18n.t('Values over time') }}</h3>
            <div class="v-scroll-x">
              <table class="v-table">
                <thead><tr><th>{{ i18n.t('Validity') }}</th><th class="num">kcal</th><th class="num">{{ i18n.t('Protein') }}</th><th class="num">{{ i18n.t('Carbs') }}</th><th class="num">{{ i18n.t('Fat') }}</th><th>{{ i18n.t('Source') }}</th></tr></thead>
                <tbody>
                  @for (v of versions(); track v.id) {
                    <tr [class.current]="v.id === p.id">
                      <td>
                        @if (v.id === p.id) { <b>{{ validity(v) }}</b> } @else { <a [routerLink]="['/products', v.id]">{{ validity(v) }}</a> }
                      </td>
                      <td class="num">{{ v.kcal | macro: 'kcal' }}</td>
                      <td class="num">{{ v.protein | macro: 'protein' }}</td>
                      <td class="num">{{ v.carbs | macro: 'carbs' }}</td>
                      <td class="num">{{ v.fat | macro: 'fat' }}</td>
                      <td class="v-small v-muted">{{ v.source }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
            <p class="v-small v-muted">{{ i18n.t('A day keeps the version that applied when it was logged. Reports read each day with its own numbers.') }}</p>
          </section>
        }

        @if (proposals().length) {
          <section class="v-panel proposals">
            <h3>{{ i18n.t('Proposed corrections') }}</h3>
            <p class="v-small v-muted">{{ i18n.t('The agent read these from your label photos or notes. Nothing changes until you approve.') }}</p>
            @for (pr of proposals(); track pr.id) {
              <div class="proposal">
                <div class="v-scroll-x">
                  <table class="v-table diff">
                    <thead><tr><th>{{ i18n.t('Apply') }}</th><th>{{ i18n.t('Field') }}</th><th class="num">{{ i18n.t('Now') }}</th><th class="num">{{ i18n.t('Proposed') }}</th></tr></thead>
                    <tbody>
                      @for (k of keys(pr); track k) {
                        <tr>
                          <td><input type="checkbox" [checked]="isSelected(pr, k)" (change)="toggle(pr, k)" [attr.aria-label]="i18n.t('apply {field}', { field: k })" /></td>
                          <td>{{ k }}</td>
                          <td class="num v-muted">{{ pr.current[k] ?? '–' }}</td>
                          <td class="num"><strong>{{ pr.changes[k] }}</strong></td>
                        </tr>
                      }
                    </tbody>
                  </table>
                </div>
                @if (pr.rationale) { <p class="v-small">{{ pr.rationale }}</p> }
                <p class="v-small v-muted">{{ pr.source }} · {{ pr.created_at.replace('T', ' ').slice(0, 16) }}</p>
                <div class="v-actions">
                  <button type="button" class="v-btn primary" (click)="decide(pr, true)" [disabled]="deciding() || !selectedCount(pr)">
                    {{ selectedCount(pr) === keys(pr).length ? i18n.t('Apply all') : i18n.t('Apply {n} of {total}', { n: selectedCount(pr), total: keys(pr).length }) }}
                  </button>
                  <button type="button" class="v-btn" (click)="decide(pr, false)" [disabled]="deciding()">{{ i18n.t('Reject') }}</button>
                </div>
              </div>
            }
          </section>
        }

        <section class="captures v-panel">
          <h3>{{ i18n.t('Label photos & notes') }}</h3>
          <p class="v-small v-muted">{{ i18n.t('Photograph the nutrition label or say what is wrong. The agent reads it on its next run and proposes corrected values; you approve them above. Approved values apply to every day that logged this product.') }}</p>
          <v-capture-input
            [productId]="p.id"
            [placeholder]="i18n.t('Photograph the label, or write what is wrong: 112 kcal per 100 g, not 96')"
            (uploaded)="onCapture($event)"
          />
          <div class="cap-list">
            @for (c of captures(); track c.id) {
              <v-capture-card [capture]="c" [compact]="true" [showTarget]="false" (changed)="replaceCapture($event)" (deleted)="removeCapture($event)" />
            }
          </div>
        </section>

        <section class="usage v-panel">
          <h3>{{ i18n.t('Where you ate this') }}</h3>
          @if (usage(); as u) {
            @if (u.entries.length) {
              <p class="v-small v-muted">{{ u.days === 1 ? i18n.t('{n} day', { n: u.days }) : i18n.t('{n} days', { n: u.days }) }} · {{ u.first_date }} {{ i18n.t('to') }} {{ u.last_date }} · {{ u.total_base_amount | number: '1.0-0' }} {{ p.reference_unit }} {{ i18n.t('in total') }} · {{ u.total_kcal | number: '1.0-0' }} kcal</p>
              <div class="v-scroll-x"><table class="v-table">
                <thead><tr><th>{{ i18n.t('Day') }}</th><th>{{ i18n.t('Meal') }}</th><th class="num">{{ i18n.t('Amount') }}</th><th class="num">kcal</th><th></th></tr></thead>
                <tbody>
                  @for (e of u.entries; track e.line_item_id) {
                    <tr>
                      <td><a [routerLink]="['/days', e.date]">{{ e.date }}</a></td>
                      <td>{{ e.meal }}</td>
                      <td class="num">{{ e.amount ?? e.base_amount }} {{ i18n.t(e.unit_code ?? e.base_unit) }}@if (e.estimated) { <span [title]="i18n.t('estimated')"> ⚠️</span> }</td>
                      <td class="num">{{ e.kcal | number: '1.0-0' }}</td>
                      <td>@if (e.is_draft) { <span class="v-tag draft">{{ i18n.t('draft') }}</span> }</td>
                    </tr>
                  }
                </tbody>
              </table></div>
            } @else {
              <p class="v-muted v-small">{{ i18n.t('Not logged yet.') }}</p>
            }
          } @else { <p class="v-muted v-small">{{ i18n.t('Loading…') }}</p> }
        </section>

        <section class="portions">
          <h3>{{ i18n.t('Portions') }}</h3>
          <p class="v-small v-muted">{{ i18n.t('Piece weights live only here, and they are measured in {unit} like the values above. One portion per unit can be the default.', { unit: p.reference_unit }) }}</p>
          <div class="v-scroll-x">
            <table class="v-table">
              <thead><tr><th>{{ i18n.t('Label') }}</th><th>{{ i18n.t('Unit') }}</th><th class="num">{{ i18n.t('Weight') }}</th><th>{{ i18n.t('Default') }}</th><th>{{ i18n.t('Weighed') }}</th><th></th></tr></thead>
              <tbody>
                @for (po of p.portions ?? []; track po.id) {
                  <tr>
                    <td>{{ po.label }}</td><td>{{ i18n.t(po.unit_code) }}</td><td class="num">{{ po.amount }} {{ i18n.t(po.amount_unit) }}</td>
                    <td>{{ po.is_default ? i18n.t('yes') : '' }}</td><td>{{ po.weight_source === 'weighed' ? i18n.t('yes') : po.weight_source === 'estimated' ? i18n.t('estimated') : '' }}</td>
                    <td class="num"><button type="button" class="v-btn quiet small danger" (click)="deletePortion(po)">{{ i18n.t('remove') }}</button></td>
                  </tr>
                } @empty { <tr><td colspan="6" class="v-muted">{{ i18n.t('No portions yet.') }}</td></tr> }
              </tbody>
            </table>
          </div>
          <form class="v-form-row add" (ngSubmit)="addPortion()">
            <label class="v-field">
              <span>{{ i18n.t('Sold or eaten as') }}</span>
              <select name="unit" [(ngModel)]="np.unit_code" (ngModelChange)="onPortionUnit($event)">
                @for (u of countUnits(); track u.code) { <option [value]="u.code">{{ i18n.t(u.singular) }}</option> }
              </select>
            </label>
            <label class="v-field">
              <span>{{ i18n.t('One {unit} of this is', { unit: portionUnitLabel() }) }}</span>
              <span class="pair">
                <input name="amount" type="number" step="any" min="0" [(ngModel)]="np.amount" required />
                <span class="fixed">{{ p.reference_unit }}</span>
              </span>
            </label>
            <label class="v-field">
              <span>{{ i18n.t('Name') }} <span class="v-muted">({{ i18n.t('optional') }})</span></span>
              <input name="label" [(ngModel)]="np.label" [placeholder]="portionUnitLabel()" />
            </label>
            <label class="v-field"><span>{{ i18n.t('Weight is') }}</span><select name="ws" [(ngModel)]="np.weight_source"><option value="weighed">{{ i18n.t('weighed') }}</option><option value="estimated">{{ i18n.t('estimated') }}</option></select></label>
            <label class="v-field check"><span>{{ i18n.t('Use by default') }}</span><input name="def" type="checkbox" [(ngModel)]="np.is_default" /></label>
            <p class="v-small v-muted hint">
              {{ i18n.t('A portion says what one {unit} of this product weighs, so “2 {unit}” can be logged without weighing anything. It is measured in', { unit: portionUnitLabel() }) }}
              <b>{{ p.reference_unit }}</b>{{ i18n.t(', because that is what the values of this product are stated per; the other unit would need a density to convert.') }}
              <b>{{ i18n.t('Use by default') }}</b> {{ i18n.t('decides which one counts when a day just says {unit} and this product has several of that unit, for instance a small and a large one.', { unit: portionUnitLabel() }) }}
            </p>
            <button type="submit" class="v-btn" [disabled]="!np.unit_code || !np.amount">{{ i18n.t('Add portion') }}</button>
          </form>
        </section>
      }
    </div>
  `,
  styles: `
    dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(7rem, 1fr)); gap: 0.75rem; margin: 0.5rem 0; }
    dt { font-size: var(--v-fs-xs); color: var(--v-ink-3); } dd { margin: 0; font-size: var(--v-fs-l); font-weight: 560; }
    .portions { margin-top: 1.5rem; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.6rem; }
    .portions h3 { font-size: var(--v-fs-l); }
    .portions p { margin: 0; }
    .portions .v-table { margin: 0; }
    .add { margin-top: 0.25rem; align-items: end; row-gap: 0.75rem; }
    .captures { margin-top: 1.5rem; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.6rem; }
    .usage { margin-top: 1.5rem; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.5rem; }
    .newver, .history { margin-top: 1rem; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.5rem; }
    .newver .wide { grid-column: 1 / -1; }
    .history tr.current { background: var(--v-primary-soft); }
    .cap-list { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.5rem; }
    .proposals { margin-top: 1.5rem; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.75rem; border-color: var(--v-agent); }
    .proposal { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.4rem; padding-top: 0.5rem; border-top: 1px dashed var(--v-line); }
    .diff { max-width: 28rem; }
    .check { grid-template-columns: 1fr auto; align-items: center; }
    .pair { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }
    .pair .fixed { color: var(--v-ink-2); font-size: var(--v-fs-s); }
    .pair input { flex: 1 1 4rem; min-width: 0; }
    .add .hint { grid-column: 1 / -1; margin: 0; }
  `,
})
export class ProductDetail {
  readonly api = inject(ApiClient);
  readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  readonly id = input.required<string>();
  readonly product = signal<Product | null>(null);
  readonly editing = signal(false);
  readonly error = signal<string | null>(null);
  readonly captures = signal<Capture[]>([]);
  readonly proposals = signal<ProductProposal[]>([]);
  readonly usage = signal<ProductUsage | null>(null);
  readonly versions = signal<Product[]>([]);
  readonly units = signal<Unit[]>([]);
  /** Portions only make sense for count units; grams need no portion. */
  readonly countUnits = computed(() => this.units().filter((u) => u.unit_type === 'count'));
  readonly portionUnitLabel = computed(() =>
    this.i18n.t(
      this.units().find((u) => u.code === this.np.unit_code)?.singular ?? this.np.unit_code,
    ),
  );
  readonly versionForm = signal(false);
  readonly saving = signal(false);
  vf = '';
  vkcal: number | null = null;
  vprotein: number | null = null;
  vcarbs: number | null = null;
  vfat: number | null = null;
  vfiber: number | null = null;
  vsalt: number | null = null;
  vsource = '';
  readonly deciding = signal(false);
  readonly unselected = signal<Set<string>>(new Set());
  np: Omit<Portion, 'id' | 'product_id'> = { label: '', unit_code: 'piece', amount: 0, amount_unit: 'g', is_default: false, weight_source: 'weighed' };

  constructor() {
    effect(() => this.load(Number(this.id())));
  }
  load(id: number): void {
    this.api.product(id).subscribe({ next: (p) => this.product.set(p), error: (e: unknown) => this.error.set(describeError(e)) });
    this.api.captures(undefined, undefined, id).subscribe({ next: (c) => this.captures.set(c), error: () => undefined });
    this.api.proposals({ product_id: id }).subscribe({ next: (p) => this.proposals.set(p), error: () => undefined });
    this.api.productUsage(id).subscribe({ next: (u) => this.usage.set(u), error: () => undefined });
    this.api.productVersions(id).subscribe({ next: (v) => this.versions.set(v), error: () => this.versions.set([]) });
    if (!this.units().length) {
      this.api.units().subscribe({ next: (u) => this.units.set(u), error: () => undefined });
    }
  }
  /** How long the values of a version apply, in words. */
  validity(p: Product): string {
    if (p.valid_from && p.valid_until) {
      return this.i18n.t('from {from} to {until}', { from: p.valid_from, until: p.valid_until });
    }
    if (p.valid_from) return this.i18n.t('from {from} onwards', { from: p.valid_from });
    if (p.valid_until) return this.i18n.t('until {until}', { until: p.valid_until });
    return this.i18n.t('from the beginning');
  }

  startVersion(p: Product): void {
    this.vf = todayLocal();
    this.vsource = '';
    for (const k of ['vkcal', 'vprotein', 'vcarbs', 'vfat', 'vfiber', 'vsalt'] as const) this[k] = null;
    this.versionForm.set(true);
    void p;
  }

  saveVersion(p: Product): void {
    if (!this.vf) return;
    const changes: Record<string, unknown> = {};
    const fields: [string, number | null][] = [
      ['kcal', this.vkcal],
      ['protein', this.vprotein],
      ['carbs', this.vcarbs],
      ['fat', this.vfat],
      ['fiber', this.vfiber],
      ['salt', this.vsalt],
    ];
    for (const [key, value] of fields) if (value !== null && value !== undefined) changes[key] = value;
    if (this.vsource.trim()) changes['source'] = this.vsource.trim();
    this.saving.set(true);
    this.api.createProductVersion(p.id, this.vf, changes).subscribe({
      next: (fresh) => {
        this.saving.set(false);
        this.versionForm.set(false);
        // the new version is a row of its own, so the page moves to it
        void this.router.navigate(['/products', fresh.id]);
      },
      error: (e: unknown) => {
        this.saving.set(false);
        this.error.set(describeError(e));
      },
    });
  }

  /** The name follows the unit unless it was typed by hand. */
  onPortionUnit(code: string): void {
    const previous = this.units().find(
      (u) => u.code !== code && this.i18n.t(u.singular) === this.np.label,
    );
    if (!this.np.label || previous) this.np.label = '';
    void code;
  }

  onCapture(c: Capture): void {
    this.captures.update((list) => [c, ...list]);
  }
  replaceCapture(u: Capture): void {
    this.captures.update((list) => list.map((x) => (x.id === u.id ? u : x)));
  }
  removeCapture(id: string): void {
    this.captures.update((list) => list.filter((x) => x.id !== id));
  }
  keys(pr: ProductProposal): string[] {
    return Object.keys(pr.changes);
  }
  /** Every field is selected until it is explicitly unticked. */
  isSelected(pr: ProductProposal, key: string): boolean {
    return !this.unselected().has(pr.id + '|' + key);
  }
  toggle(pr: ProductProposal, key: string): void {
    const id = pr.id + '|' + key;
    this.unselected.update((set) => {
      const next = new Set(set);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  selectedCount(pr: ProductProposal): number {
    return this.keys(pr).filter((k) => this.isSelected(pr, k)).length;
  }
  decide(pr: ProductProposal, approve: boolean): void {
    this.deciding.set(true);
    const fields = this.keys(pr).filter((k) => this.isSelected(pr, k));
    const call = approve
      ? this.api.approveProposal(pr.id, fields.length === this.keys(pr).length ? {} : { fields })
      : this.api.rejectProposal(pr.id);
    call.subscribe({
      next: () => {
        this.deciding.set(false);
        this.load(pr.product_id);
      },
      error: (e: unknown) => {
        this.error.set(describeError(e));
        this.deciding.set(false);
      },
    });
  }
  onSaved(p: Product): void {
    this.product.set({ ...p, portions: this.product()?.portions ?? p.portions });
    this.editing.set(false);
  }
  addPortion(): void {
    const p = this.product();
    if (!p) return;
    // an empty name takes the unit's own word, which is what the placeholder showed
    const body = { ...this.np, label: this.np.label.trim() || this.portionUnitLabel() };
    this.api.createPortion(p.id, body).subscribe({
      next: () => {
        this.np = { label: '', unit_code: 'piece', amount: 0, amount_unit: 'g', is_default: false, weight_source: 'weighed' };
        this.load(p.id);
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }
  deletePortion(po: Portion): void {
    this.api.deletePortion(po.id).subscribe({ next: () => this.load(po.product_id), error: (e: unknown) => this.error.set(describeError(e)) });
  }
  remove(): void {
    const p = this.product();
    if (!p) return;
    const question = this.i18n.t('Delete “{name}”? Days that use it keep their items only if the API allows it.', { name: p.name });
    if (!window.confirm(question)) return;
    this.api.deleteProduct(p.id).subscribe({ next: () => void this.router.navigate(['/products']), error: (e: unknown) => this.error.set(describeError(e)) });
  }
}
