import { ChangeDetectionStrategy, Component, effect, inject, input, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ApiClient, Capture, Portion, Product, ProductProposal, ProductUsage } from '../../api';
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
            <a routerLink="/products" class="v-small">← Products</a>
            <h2>{{ p.name }}</h2>
            <p class="sub">{{ p.brand }} @if (p.verified) { <span class="v-tag ok">values from the label</span> } @else { <span class="v-tag warn">estimate</span> } @if (p.ean) { <span class="v-muted v-small">EAN {{ p.ean }}</span> }</p>
          </div>
          <div class="v-actions">
            <button type="button" class="v-btn" (click)="editing.set(!editing())">{{ editing() ? 'Close editor' : 'Edit' }}</button>
            <button type="button" class="v-btn danger" (click)="remove()">Delete</button>
          </div>
        </header>

        @if (editing()) {
          <div class="v-panel"><v-product-form [product]="p" (saved)="onSaved($event)" (cancelled)="editing.set(false)" /></div>
        } @else {
          <section class="facts v-panel">
            <h3>Per 100 {{ p.reference_unit }}</h3>
            <dl>
              <div><dt>kcal</dt><dd>{{ p.kcal | macro: 'kcal' }}</dd></div>
              <div><dt>Protein</dt><dd>{{ p.protein | macro: 'protein' }} g</dd></div>
              <div><dt>Carbs</dt><dd>{{ p.carbs | macro: 'carbs' }} g</dd></div>
              <div><dt>Fat</dt><dd>{{ p.fat | macro: 'fat' }} g</dd></div>
              <div><dt>Fiber</dt><dd>{{ p.fiber | macro: 'fiber' }} g</dd></div>
              <div><dt>Salt</dt><dd>{{ p.salt | macro: 'salt' }} g</dd></div>
            </dl>
            @if (p.source) { <p class="v-small v-muted">Source: {{ p.source }}</p> }
            @if (p.note) { <p class="v-small">{{ p.note }}</p> }
          </section>
        }

        @if (proposals().length) {
          <section class="v-panel proposals">
            <h3>Proposed corrections</h3>
            <p class="v-small v-muted">The agent read these from your label photos or notes. Nothing changes until you approve.</p>
            @for (pr of proposals(); track pr.id) {
              <div class="proposal">
                <table class="v-table diff">
                  <thead><tr><th>Apply</th><th>Field</th><th class="num">Now</th><th class="num">Proposed</th></tr></thead>
                  <tbody>
                    @for (k of keys(pr); track k) {
                      <tr>
                        <td><input type="checkbox" [checked]="isSelected(pr, k)" (change)="toggle(pr, k)" [attr.aria-label]="'apply ' + k" /></td>
                        <td>{{ k }}</td>
                        <td class="num v-muted">{{ pr.current[k] ?? '–' }}</td>
                        <td class="num"><strong>{{ pr.changes[k] }}</strong></td>
                      </tr>
                    }
                  </tbody>
                </table>
                @if (pr.rationale) { <p class="v-small">{{ pr.rationale }}</p> }
                <p class="v-small v-muted">{{ pr.source }} · {{ pr.created_at.replace('T', ' ').slice(0, 16) }}</p>
                <div class="v-actions">
                  <button type="button" class="v-btn primary" (click)="decide(pr, true)" [disabled]="deciding() || !selectedCount(pr)">
                    {{ selectedCount(pr) === keys(pr).length ? 'Apply all' : 'Apply ' + selectedCount(pr) + ' of ' + keys(pr).length }}
                  </button>
                  <button type="button" class="v-btn" (click)="decide(pr, false)" [disabled]="deciding()">Reject</button>
                </div>
              </div>
            }
          </section>
        }

        <section class="captures v-panel">
          <h3>Label photos &amp; notes</h3>
          <p class="v-small v-muted">Photograph the nutrition label or say what is wrong. The agent reads it on its next run and proposes corrected values; you approve them above. Approved values apply to every day that logged this product.</p>
          <v-capture-input [productId]="p.id" (uploaded)="onCapture($event)" />
          <div class="cap-list">
            @for (c of captures(); track c.id) {
              <v-capture-card [capture]="c" [compact]="true" [showTarget]="false" (changed)="replaceCapture($event)" (deleted)="removeCapture($event)" />
            }
          </div>
        </section>

        <section class="usage v-panel">
          <h3>Where you ate this</h3>
          @if (usage(); as u) {
            @if (u.entries.length) {
              <p class="v-small v-muted">{{ u.days }} day{{ u.days === 1 ? '' : 's' }} · {{ u.first_date }} to {{ u.last_date }} · {{ u.total_base_amount | number: '1.0-0' }} {{ p.reference_unit }} in total · {{ u.total_kcal | number: '1.0-0' }} kcal</p>
              <div class="v-scroll-x"><table class="v-table">
                <thead><tr><th>Day</th><th>Meal</th><th class="num">Amount</th><th class="num">kcal</th><th></th></tr></thead>
                <tbody>
                  @for (e of u.entries; track e.line_item_id) {
                    <tr>
                      <td><a [routerLink]="['/days', e.date]">{{ e.date }}</a></td>
                      <td>{{ e.meal }}</td>
                      <td class="num">{{ e.amount ?? e.base_amount }} {{ e.unit_code ?? e.base_unit }}@if (e.estimated) { <span title="estimated"> ⚠️</span> }</td>
                      <td class="num">{{ e.kcal | number: '1.0-0' }}</td>
                      <td>@if (e.is_draft) { <span class="v-tag draft">draft</span> }</td>
                    </tr>
                  }
                </tbody>
              </table></div>
            } @else {
              <p class="v-muted v-small">Not logged yet.</p>
            }
          } @else { <p class="v-muted v-small">Loading…</p> }
        </section>

        <section class="portions">
          <h3>Portions</h3>
          <p class="v-small v-muted">Piece weights live only here. One default portion per unit.</p>
          <table class="v-table">
            <thead><tr><th>Label</th><th>Unit</th><th class="num">Weight</th><th>Default</th><th>Weighed</th><th></th></tr></thead>
            <tbody>
              @for (po of p.portions ?? []; track po.id) {
                <tr>
                  <td>{{ po.label }}</td><td>{{ po.unit_code }}</td><td class="num">{{ po.amount }} {{ po.amount_unit }}</td>
                  <td>{{ po.is_default ? 'yes' : '' }}</td><td>{{ po.weight_source === 'weighed' ? 'yes' : po.weight_source === 'estimated' ? 'estimated' : '' }}</td>
                  <td class="num"><button type="button" class="v-btn quiet small danger" (click)="deletePortion(po)">remove</button></td>
                </tr>
              } @empty { <tr><td colspan="6" class="v-muted">No portions yet.</td></tr> }
            </tbody>
          </table>
          <form class="v-form-row add" (ngSubmit)="addPortion()">
            <label class="v-field"><span>Label</span><input name="label" [(ngModel)]="np.label" placeholder="tub, slice, piece" required /></label>
            <label class="v-field"><span>Unit code</span><input name="unit" [(ngModel)]="np.unit_code" placeholder="piece" required /></label>
            <label class="v-field"><span>Weight</span><input name="amount" type="number" step="any" min="0" [(ngModel)]="np.amount" required /></label>
            <label class="v-field"><span>Weight unit</span><select name="au" [(ngModel)]="np.amount_unit"><option value="g">g</option><option value="ml">ml</option></select></label>
            <label class="v-field check"><span>Default</span><input name="def" type="checkbox" [(ngModel)]="np.is_default" /></label>
            <label class="v-field"><span>How measured</span><select name="ws" [(ngModel)]="np.weight_source"><option value="weighed">weighed</option><option value="estimated">estimated</option></select></label>
            <button type="submit" class="v-btn" [disabled]="!np.label || !np.unit_code || !np.amount">Add portion</button>
          </form>
        </section>
      }
    </div>
  `,
  styles: `
    dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(7rem, 1fr)); gap: 0.75rem; margin: 0.5rem 0; }
    dt { font-size: var(--v-fs-xs); color: var(--v-ink-3); } dd { margin: 0; font-size: var(--v-fs-l); font-weight: 560; }
    .portions { margin-top: 1.5rem; } .add { margin-top: 0.75rem; align-items: end; }
    .captures { margin-top: 1.5rem; display: grid; gap: 0.6rem; }
    .usage { margin-top: 1.5rem; display: grid; gap: 0.5rem; }
    .cap-list { display: grid; gap: 0.5rem; }
    .proposals { margin-top: 1.5rem; display: grid; gap: 0.75rem; border-color: var(--v-agent); }
    .proposal { display: grid; gap: 0.4rem; padding-top: 0.5rem; border-top: 1px dashed var(--v-line); }
    .diff { max-width: 28rem; }
    .check { grid-template-columns: 1fr auto; align-items: center; }
  `,
})
export class ProductDetail {
  readonly api = inject(ApiClient);
  private readonly router = inject(Router);
  readonly id = input.required<string>();
  readonly product = signal<Product | null>(null);
  readonly editing = signal(false);
  readonly error = signal<string | null>(null);
  readonly captures = signal<Capture[]>([]);
  readonly proposals = signal<ProductProposal[]>([]);
  readonly usage = signal<ProductUsage | null>(null);
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
    this.api.createPortion(p.id, this.np).subscribe({
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
    if (!p || !window.confirm(`Delete “${p.name}”? Days that use it keep their items only if the API allows it.`)) return;
    this.api.deleteProduct(p.id).subscribe({ next: () => void this.router.navigate(['/products']), error: (e: unknown) => this.error.set(describeError(e)) });
  }
}
