import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Observable, map, of, switchMap, tap } from 'rxjs';
import { ApiClient, ConsumableKind, LineItem, LineItemPatch, Product, Unit } from '../api';
import { I18nService } from '../core/i18n.service';
import { describeError } from '../core/problem';
import { formatAmount, formatUnit } from './format';
import { ProductSearch } from './product-search';

/** A meal the item can be moved to: one of its own day. */
export interface MealChoice {
  id: number;
  name: string;
}

/** A portion a pending new-product proposal brings with it, before it is a portion row. */
interface ProposedPortion {
  label: string;
  unit_code: string;
  amount: number;
  amount_unit: string;
}

/** What the panel compares against to know whether anything was typed. */
interface Baseline {
  consumableId: number;
  amount: number | null;
  unitCode: string;
  estimated: boolean;
  amountEstimated: boolean;
  meal: number | 'new' | null;
}

/**
 * Editing one logged item, in the same shape as adding one: the product, amount, the units
 * the product really supports, the meal, and both estimate marks — in both directions.
 *
 * Every value the agent suggested is an input here (R84): another product from its
 * alternatives or from a search, another meal of the same day, the unit and portion, and
 * the marks. An estimate that cannot be withdrawn makes the mark lie, so `false` is sent.
 *
 * `embedded` drops the panel's own Save and Cancel: the inbox card puts Save beside
 * Accept and drives the panel through `dirty()` and `persist()`.
 */
@Component({
  selector: 'v-line-item-form',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, ProductSearch],
  template: `
    <!-- A div, not a form: on the approval page this sits inside the approve form, and a
         nested form is not markup a browser keeps. Every control is standalone for the
         same reason — it belongs to this panel, not to whatever form encloses it. -->
    <div class="v-form-row edit" [class.embedded]="embedded()">
      <div class="picked">
        <span class="name">{{ consumableName() }}</span>
        @if (!embedded()) { <span class="v-muted v-small">{{ current() }}</span> }
        @if (consumableKind() === 'product') {
          <a class="v-small" [routerLink]="['/products', consumableId()]">{{ i18n.t('Open the product') }}</a>
        }
        <button type="button" class="v-btn small quiet" (click)="searching.set(!searching())" [attr.aria-expanded]="searching()">{{ i18n.t('Change product') }}</button>
      </div>
      @if (searching()) {
        <div class="change">
          @if (alternatives().length) {
            <div class="alts">
              <span class="v-small v-muted">{{ i18n.t('The agent also considered') }}</span>
              @for (a of alternatives(); track a.consumable_id) {
                <button type="button" class="v-btn small" (click)="pickAlternative(a.consumable_id, a.name, a.kind)">{{ a.name }} ({{ (a.score * 100).toFixed(0) }} %)</button>
              }
            </div>
          }
          <v-product-search [on]="day()" (picked)="pickProduct($event)" />
        </div>
      }
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
          @if (proposedPortions().length) {
            <optgroup [attr.label]="i18n.t('Portions the proposal brings')">
              @for (p of proposedPortions(); track $index) { <option [value]="'proposed:' + $index">{{ i18n.t(p.label) }} ({{ amountText(p.amount) }} {{ i18n.t(p.amount_unit) }})</option> }
            </optgroup>
          }
          @if (undeclaredUnits().length) {
            <optgroup [attr.label]="i18n.t('Needs a size once')">
              @for (u of undeclaredUnits(); track u.code) { <option [value]="u.code">{{ i18n.t(u.singular) }}</option> }
            </optgroup>
          }
        </select>
      </label>
      @if (meals().length) {
        <label class="v-field"><span>{{ i18n.t('Meal') }}</span>
          <select [(ngModel)]="meal" [ngModelOptions]="{ standalone: true }" [attr.aria-label]="i18n.t('Meal')">
            @for (m of meals(); track m.id) { <option [ngValue]="m.id">{{ m.name }}</option> }
            @if (day()) { <option ngValue="new">{{ i18n.t('new meal…') }}</option> }
          </select>
        </label>
        @if (meal === 'new') {
          <label class="v-field"><span>{{ i18n.t('Meal name') }}</span>
            <input [(ngModel)]="newMeal" [ngModelOptions]="{ standalone: true }" [attr.aria-label]="i18n.t('New meal name')" />
          </label>
        }
      }
      @if (proposedPortion(); as po) {
        <p class="v-small v-muted hint">{{ i18n.t('Saved as {amount} {unit} until the product is approved.', { amount: amountText((amount ?? 0) * po.amount), unit: po.amount_unit }) }}</p>
      }
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
      @if (kept()) {
        <p class="v-small v-muted hint kept">{{ i18n.t('This item changed meanwhile. What you typed is kept until you save or cancel.') }}</p>
      }
      @if (!embedded()) {
        <span class="v-actions">
          <button type="button" class="v-btn small primary" (click)="save()" [disabled]="!ready() || busy()">{{ i18n.t('Save') }}</button>
          <button type="button" class="v-btn small quiet" (click)="cancelled.emit()">{{ i18n.t('Cancel') }}</button>
        </span>
      }
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
    </div>
  `,
  styles: `
    .edit { padding: 0.6rem 0.75rem; border: 1px solid var(--v-line); border-radius: var(--v-radius-l); background: var(--v-surface); }
    .edit.embedded { padding: 0; border: 0; background: transparent; }
    .picked { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: baseline; font-weight: 500; }
    .picked a, .picked button { font-weight: 400; }
    .change { grid-column: 1 / -1; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.4rem; }
    .alts { display: flex; flex-wrap: wrap; gap: 0.35rem; align-items: center; }
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
  /** The meals of the item's day; empty hides the meal select. */
  readonly meals = input<MealChoice[]>([]);
  /** The day the item belongs to: the version a search offers, and where a new meal goes. */
  readonly day = input<string | null>(null);
  /** Without its own buttons, for a host that offers Save and Accept itself. */
  readonly embedded = input(false);
  readonly saved = output<LineItem>();
  readonly cancelled = output<void>();
  readonly error = signal<string | null>(null);
  readonly busy = signal(false);
  /** The item's product, for its portions and its reference unit; null for an ad-hoc item. */
  readonly product = signal<Product | null>(null);
  /** The portions a pending new-product proposal carries for an ad-hoc item. */
  readonly proposedPortions = signal<ProposedPortion[]>([]);
  readonly unitCode = signal('g');
  /** The consumable the item will point at; another one once a product is picked. */
  readonly consumableId = signal(0);
  readonly consumableName = signal('');
  readonly consumableKind = signal<ConsumableKind>('product');
  /** The search and the agent's alternatives, opened by "Change product". */
  readonly searching = signal(false);
  /** A refresh brought newer values while something was typed; the typing won. */
  readonly kept = signal(false);
  amount: number | null = null;
  portionAmount: number | null = null;
  estimated = false;
  amountEstimated = false;
  meal: number | 'new' | null = null;
  newMeal = '';
  private baseline: Baseline | null = null;
  private loadedId: number | null = null;

  readonly portions = computed(() => this.product()?.portions ?? []);

  /** The agent's other candidates, without the one already chosen. */
  readonly alternatives = computed(() =>
    (this.item().alternatives ?? []).filter((a) => a.consumable_id !== this.consumableId()),
  );

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

  /** The proposal's portion chosen for an ad-hoc item, if one is. */
  readonly proposedPortion = computed(() => {
    const chosen = this.unitCode();
    if (!chosen.startsWith('proposed:')) return null;
    return this.proposedPortions()[Number(chosen.slice(9))] ?? null;
  });

  readonly unitLabel = computed(() =>
    this.i18n.t(this.units().find((u) => u.code === this.unitCode())?.singular ?? this.unitCode()),
  );

  constructor() {
    effect(() => {
      const it = this.item();
      untracked(() => this.take(it));
    });
  }

  /**
   * The item as the server has it now. A refresh of the same item while something was
   * typed keeps the typing: replacing it would undo a correction without a word (R83).
   */
  private take(it: LineItem): void {
    if (this.loadedId === it.id && this.dirty() && !this.matches(it)) {
      this.kept.set(true);
      return;
    }
    this.loadedId = it.id;
    this.kept.set(false);
    this.amount = it.amount ?? it.base_amount;
    this.estimated = it.estimated;
    this.amountEstimated = it.amount_estimated;
    this.meal = this.meals().some((m) => m.id === it.meal_id) ? it.meal_id : null;
    this.newMeal = '';
    // the portion, when there is one: "piece" alone would drop the L of "2 piece (L)"
    this.unitCode.set(it.portion_id ? `portion:${it.portion_id}` : (it.unit_code ?? it.base_unit));
    this.portionAmount = null;
    this.consumableId.set(it.consumable_id);
    this.consumableName.set(it.consumable_name);
    this.consumableKind.set(it.consumable_kind);
    this.searching.set(false);
    this.baseline = {
      consumableId: it.consumable_id,
      amount: this.amount,
      unitCode: this.unitCode(),
      estimated: it.estimated,
      amountEstimated: it.amount_estimated,
      meal: this.meal,
    };
    this.loadConsumable(it.consumable_id, it.consumable_kind);
  }

  /** The product behind the item, or the portions its pending proposal brings. */
  private loadConsumable(id: number, kind: ConsumableKind): void {
    this.product.set(null);
    this.proposedPortions.set([]);
    if (kind === 'product') {
      this.api.product(id).subscribe({
        next: (p) => this.product.set(p),
        error: () => this.product.set(null),
      });
    } else if (kind === 'ad_hoc') {
      this.api.proposals({ consumable_id: id }).subscribe({
        next: (list) => {
          const pending = list.find((pr) => pr.kind === 'new' && pr.status === 'pending');
          const raw = pending?.changes['portions'];
          this.proposedPortions.set(
            Array.isArray(raw)
              ? (raw as Record<string, unknown>[])
                  .filter((po) => (po['op'] ?? 'add') === 'add' && Number(po['amount']) > 0)
                  .map((po) => ({
                    label: String(po['label'] ?? po['unit_code'] ?? ''),
                    unit_code: String(po['unit_code'] ?? ''),
                    amount: Number(po['amount']),
                    amount_unit: String(po['amount_unit'] ?? 'g'),
                  }))
              : [],
          );
        },
        error: () => this.proposedPortions.set([]),
      });
    }
  }

  /**
   * Whether the server's item already says what the panel holds — the echo of this
   * panel's own save, which is no reason to warn about a change made meanwhile.
   */
  private matches(it: LineItem): boolean {
    const unit = it.portion_id ? `portion:${it.portion_id}` : (it.unit_code ?? it.base_unit);
    return (
      this.newMeal.trim() === '' &&
      this.portionAmount === null &&
      it.consumable_id === this.consumableId() &&
      (it.amount ?? it.base_amount) === this.amount &&
      unit === this.unitCode() &&
      it.estimated === this.estimated &&
      it.amount_estimated === this.amountEstimated &&
      (this.meal === null || it.meal_id === this.meal)
    );
  }

  /** What was just written is the panel's new starting point; a new meal or size now has its id. */
  private markSaved(li: LineItem): void {
    if (this.meal === 'new') {
      this.meal = li.meal_id;
      this.newMeal = '';
    }
    if (this.portionAmount !== null) {
      this.unitCode.set(li.portion_id ? `portion:${li.portion_id}` : (li.unit_code ?? li.base_unit));
      this.portionAmount = null;
    }
    this.kept.set(false);
    this.baseline = {
      consumableId: li.consumable_id,
      amount: this.amount,
      unitCode: this.unitCode(),
      estimated: this.estimated,
      amountEstimated: this.amountEstimated,
      meal: this.meal,
    };
  }

  /** Whether anything differs from what the server said when the panel opened. */
  dirty(): boolean {
    const b = this.baseline;
    if (!b) return false;
    return (
      this.consumableId() !== b.consumableId ||
      this.amount !== b.amount ||
      this.unitCode() !== b.unitCode ||
      this.estimated !== b.estimated ||
      this.amountEstimated !== b.amountEstimated ||
      this.meal !== b.meal ||
      this.newMeal.trim() !== '' ||
      this.portionAmount !== null
    );
  }

  /** Whether `persist()` has what it needs. */
  ready(): boolean {
    if (!this.amount) return false;
    if (this.needsSize() && !this.portionAmount) return false;
    if (this.meal === 'new' && !this.newMeal.trim()) return false;
    return true;
  }

  amountText(value: number | null | undefined): string {
    return formatAmount(value);
  }

  pickAlternative(id: number, name: string, kind: ConsumableKind): void {
    this.switchTo(id, name, kind);
  }

  pickProduct(p: Product): void {
    this.switchTo(p.id, p.name, 'product');
  }

  /** Another consumable: its own units, so a portion of the old one does not carry over. */
  private switchTo(id: number, name: string, kind: ConsumableKind): void {
    this.consumableId.set(id);
    this.consumableName.set(name);
    this.consumableKind.set(kind);
    this.searching.set(false);
    const unit = this.unitCode();
    if (unit.startsWith('portion:') || unit.startsWith('proposed:')) {
      this.unitCode.set(this.item().base_unit);
    }
    this.loadConsumable(id, kind);
  }

  /** The panel's own Save: write, then tell the host. */
  save(): void {
    if (!this.ready()) return;
    this.busy.set(true);
    this.error.set(null);
    this.persist().subscribe({
      next: (li) => {
        this.busy.set(false);
        this.saved.emit(li);
      },
      error: (e: unknown) => this.failed(e),
    });
  }

  /**
   * Write what the panel holds: a new meal and a size first when they are needed, then
   * the item. The host decides what happens after — a reload, or an approval.
   */
  persist(): Observable<LineItem> {
    const it = this.item();
    const day = this.day();
    const meal$: Observable<number | null> =
      this.meal === 'new' && day
        ? this.api.addMeal(day, { name: this.newMeal.trim() }).pipe(map((m) => m.id))
        : of(typeof this.meal === 'number' ? this.meal : null);
    return meal$.pipe(
      switchMap((mealId) =>
        this.unit().pipe(
          switchMap((unit) => {
            const body: LineItemPatch = {
              ...unit,
              estimated: this.estimated,
              amount_estimated: this.amountEstimated,
            };
            if (this.consumableId() !== it.consumable_id) body.consumable_id = this.consumableId();
            if (mealId !== null && mealId !== it.meal_id) body.meal_id = mealId;
            return this.api.updateLineItem(it.id, body);
          }),
        ),
      ),
      // what was written is the new starting point: its echo from the server is not a
      // change made meanwhile, and the panel is clean again
      tap((li) => this.markSaved(li)),
    );
  }

  /** Amount, unit and portion as the server takes them. */
  private unit(): Observable<Pick<LineItemPatch, 'amount' | 'unit_code' | 'portion_id'>> {
    const amount = this.amount ?? 0;
    const p = this.product();
    // a unit the product has no portion for is declared once, then used like any other
    if (this.needsSize() && p && this.portionAmount) {
      const code = this.unitCode();
      // the unit's own word, not the translated one: a label is data and outlives the
      // language it was typed in
      const label = this.units().find((u) => u.code === code)?.singular ?? code;
      return this.api
        .createPortion(p.id, {
          unit_code: code,
          label,
          amount: this.portionAmount,
          amount_unit: p.reference_unit,
          is_default: true,
          weight_source: this.amountEstimated ? 'estimated' : 'weighed',
        })
        .pipe(
          map((portion) => {
            this.product.update((prod) =>
              prod ? { ...prod, portions: [...(prod.portions ?? []), portion] } : prod,
            );
            this.unitCode.set('portion:' + portion.id);
            this.portionAmount = null;
            return { amount, unit_code: portion.unit_code, portion_id: portion.id };
          }),
        );
    }
    // a one-off has no portion rows yet: the proposal's piece weight becomes its weight
    const proposed = this.proposedPortion();
    if (proposed) {
      return of({ amount: amount * proposed.amount, unit_code: proposed.amount_unit, portion_id: null });
    }
    const chosen = this.unitCode();
    const portionId = chosen.startsWith('portion:') ? Number(chosen.slice(8)) : null;
    const portion = portionId ? this.portions().find((x) => x.id === portionId) : undefined;
    // explicitly null, so switching back to grams drops the portion it had
    return of({ amount, unit_code: portion ? portion.unit_code : chosen, portion_id: portionId });
  }

  private failed(e: unknown): void {
    this.busy.set(false);
    this.error.set(describeError(e));
  }
}
