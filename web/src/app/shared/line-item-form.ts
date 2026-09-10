import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiClient, LineItem, Product, Unit } from '../api';
import { I18nService } from '../core/i18n.service';
import { describeError } from '../core/problem';
import { formatAmount, formatUnit } from './format';

/**
 * Editing one logged item, in the same shape as adding one: amount, the units the product
 * really supports, and both estimate marks — in both directions.
 *
 * An estimate that cannot be withdrawn makes the mark lie: it feeds the estimate count on
 * the day, so a day whose labels have all been read still reads as guesswork. The server
 * has always accepted `false` here; only the form was missing.
 */
@Component({
  selector: 'v-line-item-form',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink],
  template: `
    <!-- A div, not a form: on the approval page this sits inside the approve form, and a
         nested form is not markup a browser keeps. Every control is standalone for the
         same reason — it belongs to this panel, not to whatever form encloses it. -->
    <div class="v-form-row edit">
      <div class="picked">
        {{ item().consumable_name }}
        <span class="v-muted v-small">{{ current() }}</span>
        @if (item().consumable_kind === 'product') {
          <a class="v-small" [routerLink]="['/products', item().consumable_id]">{{ i18n.t('Open the product') }}</a>
        }
      </div>
      <label class="v-field"><span>{{ i18n.t('Amount') }}</span>
        <input type="number" step="any" min="0" [(ngModel)]="amount" [ngModelOptions]="{ standalone: true }" required [attr.aria-label]="i18n.t('Amount')" />
      </label>
      <label class="v-field"><span>{{ i18n.t('Unit') }}</span>
        <select [ngModel]="unitCode()" (ngModelChange)="unitCode.set($event)" [ngModelOptions]="{ standalone: true }" [attr.aria-label]="i18n.t('Unit')">
          <optgroup [attr.label]="i18n.t('Weight and volume')">
            @for (u of measuredUnits(); track u.code) { <option [value]="u.code">{{ i18n.t(u.singular) }}</option> }
          </optgroup>
          @if (portions().length) {
            <optgroup [attr.label]="i18n.t('Portions of this product')">
              @for (p of portions(); track p.id) { <option [value]="'portion:' + p.id">{{ i18n.t(p.label) }} ({{ amountText(p.amount) }} {{ i18n.t(p.amount_unit) }})</option> }
            </optgroup>
          }
          @if (undeclaredUnits().length) {
            <optgroup [attr.label]="i18n.t('Needs a size once')">
              @for (u of undeclaredUnits(); track u.code) { <option [value]="u.code">{{ i18n.t(u.singular) }}</option> }
            </optgroup>
          }
        </select>
      </label>
      @if (needsSize()) {
        <label class="v-field size-field">
          <span>{{ i18n.t('One {unit} is', { unit: unitLabel() }) }}</span>
          <span class="size">
            <input type="number" step="any" min="0" [(ngModel)]="portionAmount" [ngModelOptions]="{ standalone: true }" required />
            <span class="fixed">{{ product()?.reference_unit }}</span>
          </span>
        </label>
        <p class="v-small v-muted hint">{{ i18n.t('Saved with the product, so “{unit}” works from now on.', { unit: unitLabel() }) }}</p>
      }
      <label class="v-field check"><span>{{ i18n.t('Nutrition values estimated') }}</span>
        <input type="checkbox" [(ngModel)]="estimated" [ngModelOptions]="{ standalone: true }" />
      </label>
      <label class="v-field check"><span>{{ i18n.t('Amount estimated') }}</span>
        <input type="checkbox" [(ngModel)]="amountEstimated" [ngModelOptions]="{ standalone: true }" />
      </label>
      <span class="v-actions">
        <button type="button" class="v-btn small primary" (click)="save()" [disabled]="!amount || busy() || (needsSize() && !portionAmount)">{{ i18n.t('Save') }}</button>
        <button type="button" class="v-btn small quiet" (click)="cancelled.emit()">{{ i18n.t('Cancel') }}</button>
      </span>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
    </div>
  `,
  styles: `
    .edit { padding: 0.6rem 0.75rem; border: 1px solid var(--v-line); border-radius: var(--v-radius-l); background: var(--v-surface); }
    .picked { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: baseline; font-weight: 500; }
    .picked a { font-weight: 400; }
    .check { align-items: center; grid-template-columns: auto auto; }
    .size-field { grid-column: 1 / -1; }
    .size { display: flex; gap: 0.4rem; align-items: center; }
    .size .fixed { color: var(--v-ink-2); font-size: var(--v-fs-s); }
    .size input { min-width: 5rem; }
    .hint, .v-error { grid-column: 1 / -1; margin: 0; }
  `,
})
export class LineItemForm {
  private readonly api = inject(ApiClient);
  readonly i18n = inject(I18nService);
  readonly item = input.required<LineItem>();
  /** The unit table, loaded once by the page that hosts this panel. */
  readonly units = input.required<Unit[]>();
  readonly saved = output<void>();
  readonly cancelled = output<void>();
  readonly error = signal<string | null>(null);
  readonly busy = signal(false);
  /** The item's product, for its portions and its reference unit; null for an ad-hoc item. */
  readonly product = signal<Product | null>(null);
  readonly unitCode = signal('g');
  amount: number | null = null;
  portionAmount: number | null = null;
  estimated = false;
  amountEstimated = false;

  readonly portions = computed(() => this.product()?.portions ?? []);

  /** What the item says today, so the panel shows what is being changed. */
  readonly current = computed(
    () => `${this.amountText(this.item().amount ?? this.item().base_amount)} ${formatUnit(this.item(), (k) => this.i18n.t(k))}`,
  );

  /** Grams or millilitres, whichever family the product is declared in (R73). */
  readonly measuredUnits = computed(() => {
    const reference = this.product()?.reference_unit ?? this.item().base_unit;
    const family = reference === 'ml' ? 'volume' : 'mass';
    return this.units().filter((u) => u.unit_type === family);
  });

  /** Count units this product has no portion for; an ad-hoc item can declare none. */
  readonly undeclaredUnits = computed(() => {
    if (this.product() === null) return [];
    const declared = new Set(this.portions().map((p) => p.unit_code));
    return this.units().filter((u) => u.unit_type === 'count' && !declared.has(u.code));
  });

  readonly needsSize = computed(() =>
    this.undeclaredUnits().some((u) => u.code === this.unitCode()),
  );

  readonly unitLabel = computed(() =>
    this.i18n.t(this.units().find((u) => u.code === this.unitCode())?.singular ?? this.unitCode()),
  );

  constructor() {
    effect(() => {
      const it = this.item();
      this.amount = it.amount ?? it.base_amount;
      this.estimated = it.estimated;
      this.amountEstimated = it.amount_estimated;
      // the portion, when there is one: "piece" alone would drop the L of "2 piece (L)"
      this.unitCode.set(it.portion_id ? `portion:${it.portion_id}` : (it.unit_code ?? it.base_unit));
      this.portionAmount = null;
      this.product.set(null);
      if (it.consumable_kind === 'product') {
        this.api.product(it.consumable_id).subscribe({
          next: (p) => this.product.set(p),
          error: () => this.product.set(null),
        });
      }
    });
  }

  amountText(value: number | null | undefined): string {
    return formatAmount(value);
  }

  save(): void {
    const it = this.item();
    if (!this.amount) return;
    const p = this.product();
    // a unit the product has no portion for is declared once, then used like any other
    if (this.needsSize()) {
      if (!p || !this.portionAmount) return;
      const code = this.unitCode();
      // the unit's own word, not the translated one: a label is data and outlives the
      // language it was typed in
      const label = this.units().find((u) => u.code === code)?.singular ?? code;
      this.busy.set(true);
      this.api
        .createPortion(p.id, {
          unit_code: code,
          label,
          amount: this.portionAmount,
          amount_unit: p.reference_unit,
          is_default: true,
          weight_source: this.amountEstimated ? 'estimated' : 'weighed',
        })
        .subscribe({
          next: (portion) => {
            this.product.update((prod) =>
              prod ? { ...prod, portions: [...(prod.portions ?? []), portion] } : prod,
            );
            this.unitCode.set('portion:' + portion.id);
            this.portionAmount = null;
            this.busy.set(false);
            this.save();
          },
          error: (e: unknown) => this.failed(e),
        });
      return;
    }
    const chosen = this.unitCode();
    const portionId = chosen.startsWith('portion:') ? Number(chosen.slice(8)) : null;
    const portion = portionId ? this.portions().find((x) => x.id === portionId) : undefined;
    this.busy.set(true);
    this.api
      .updateLineItem(it.id, {
        amount: this.amount,
        unit_code: portion ? portion.unit_code : chosen,
        // explicitly null, so switching back to grams drops the portion it had
        portion_id: portionId,
        estimated: this.estimated,
        amount_estimated: this.amountEstimated,
      })
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.saved.emit();
        },
        error: (e: unknown) => this.failed(e),
      });
  }

  private failed(e: unknown): void {
    this.busy.set(false);
    this.error.set(describeError(e));
  }
}
