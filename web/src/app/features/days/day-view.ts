import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiClient, DayLog, LineItem, MACRO_KEYS, MACRO_LABEL, MACRO_UNIT, MacroKey, Meal, Product, TrainingType, Unit } from '../../api';
import { HttpErrorResponse } from '@angular/common/http';
import { FormatService } from '../../core/format.service';
import { I18nService } from '../../core/i18n.service';
import { describeError } from '../../core/problem';
import { BandGauge } from '../../shared/band-gauge';
import { DayNamePipe, MacroPipe, shiftDate } from '../../shared/format';
import { ProductSearch } from '../../shared/product-search';
import { StatusTag } from '../../shared/status-tag';
import { FoodIcon } from '../../shared/food-icon';
import { DayThread } from './day-thread';

/**
 * The day as a ledger: meals with their line items and running totals, the band gauges
 * above, the day thread beside it. Estimates carry ⚠️, agent drafts are tinted.
 */
@Component({
  selector: 'v-day-view',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, FormsModule, BandGauge, StatusTag, MacroPipe, DayNamePipe, ProductSearch, DayThread, FoodIcon],
  template: `
    <div class="v-page">
      <header class="v-page-head">
        <div>
          <nav class="daynav v-small">
            <a class="step" [routerLink]="['/days', prev()]" [title]="i18n.t('previous')">
              <span aria-hidden="true">←</span><span class="word">{{ i18n.t('previous') }}</span>
            </a>
            <a class="all" routerLink="/days">{{ i18n.t('all days') }}</a>
            <a class="step" [routerLink]="['/days', next()]" [title]="i18n.t('next')">
              <span class="word">{{ i18n.t('next') }}</span><span aria-hidden="true">→</span>
            </a>
          </nav>
          <h2>{{ date() | dayName }}</h2>
          @if (day(); as d) {
            <p class="sub">
              <v-status-tag [status]="d.status" />
              @if (d.reliable === false) { <span class="v-tag warn">{{ i18n.t('estimated day') }}</span> }
              @if (d.reliable === null) { <span class="v-tag bad">{{ i18n.t('reliable flag missing') }}</span> }
              @if (d.target_band) { <span class="v-muted">{{ i18n.t('band') }}: {{ d.target_band.name }}</span> }
            </p>
          }
        </div>
        @if (day(); as d) {
          <div class="v-actions">
            <label class="v-field"><span>{{ i18n.t('Training') }}</span>
              <!-- a day carrying no type is judged as a rest day, so it reads as one here -->
              <select [ngModel]="d.training_type ?? 'rest'" (ngModelChange)="setTraining($event)">
                <option value="rest">{{ i18n.t('rest') }}</option><option value="strength">{{ i18n.t('strength') }}</option><option value="martial_arts">{{ i18n.t('martial arts') }}</option>
              </select>
            </label>
            <label class="v-field"><span>{{ i18n.t('Reliable') }}</span>
              <select [ngModel]="d.reliable === null ? '' : d.reliable ? 'true' : 'false'" (ngModelChange)="setReliable($event)">
                <option value="" disabled>{{ i18n.t('choose') }}</option><option value="true">{{ i18n.t('yes, counts') }}</option><option value="false">{{ i18n.t('no, whole day estimated') }}</option>
              </select>
            </label>
            @if (d.status === 'closed') {
              <button type="button" class="v-btn" (click)="reopen()">{{ i18n.t('Reopen day') }}</button>
            } @else if (d.status === 'open') {
              <button type="button" class="v-btn primary" (click)="close()">{{ i18n.t('Close day') }}</button>
            } @else {
              <a class="v-btn primary" [routerLink]="['/drafts', date()]">{{ i18n.t('Review draft') }}</a>
            }
          </div>
        }
      </header>

      @if (missing()) {
        <section class="v-panel create-day">
          <h3>{{ i18n.t('Nothing logged for this day yet') }}</h3>
          <p class="v-small v-muted">{{ i18n.t('Create the day to start adding meals. Say whether it will count: a day you only estimate as a whole (travel, party) does not enter the statistics.') }}</p>
          <form class="v-form-row" (ngSubmit)="createDay()">
            <label class="v-field"><span>{{ i18n.t('Counts for statistics?') }}</span>
              <select name="rel" [(ngModel)]="newReliable" required>
                <option value="true">{{ i18n.t('yes, I log it properly') }}</option>
                <option value="false">{{ i18n.t('no, whole day estimated') }}</option>
              </select>
            </label>
            <label class="v-field"><span>{{ i18n.t('Training') }}</span>
              <select name="tt" [(ngModel)]="newTraining">
                <option value="rest">{{ i18n.t('rest') }}</option><option value="strength">{{ i18n.t('strength') }}</option><option value="martial_arts">{{ i18n.t('martial arts') }}</option>
              </select>
            </label>
            <button type="submit" class="v-btn primary">{{ i18n.t('Create this day') }}</button>
          </form>
        </section>
      } @else if (error(); as e) { <div class="v-error">{{ e }}</div> }

      @if (day(); as d) {
        <section class="gauges" [attr.aria-label]="i18n.t('Targets')">
          @for (k of macroKeys; track k) {
            <v-band-gauge [macro]="k" [label]="i18n.t(label[k])" [unit]="unit[k]" [value]="d.macros[k]" [band]="bandFor(d, k)" [zone]="d.zones?.[k]" />
          }
        </section>

        @if (d.findings.length) {
          <div class="v-notice">
            @for (f of d.findings; track f.code + i18n.msg(f.message)) {
                  <div>{{ i18n.msg(f.message) }}</div>
                }
          </div>
        }

        <div class="columns">
          <section class="ledger">
            @if (d.has_drafts) {
              <div class="v-notice drafts-bar">
                <span>{{ i18n.t('This day has draft items from the agent. Accept them one by one below, or all at once.') }}</span>
                <span class="v-actions">
                  <button type="button" class="v-btn small primary" (click)="acceptAll()">{{ i18n.t('Accept all') }}</button>
                  <a class="v-btn small" routerLink="/inbox">{{ i18n.t('Open the inbox') }}</a>
                </span>
              </div>
            }
            @for (meal of d.meals; track meal.id) {
              <article class="meal">
                <header>
                  @if (editingMeal() === meal.id) {
                    <form class="meal-edit" (ngSubmit)="saveMeal(meal)">
                      <input name="mn{{ meal.id }}" [(ngModel)]="mealName" [attr.aria-label]="i18n.t('Meal name')" required />
                      <input name="mt{{ meal.id }}" type="time" [(ngModel)]="mealTime" [attr.aria-label]="i18n.t('Meal time')" />
                      <button type="submit" class="v-btn small primary" [disabled]="!mealName.trim()">{{ i18n.t('Save') }}</button>
                      <button type="button" class="v-btn small quiet" (click)="editingMeal.set(null)">{{ i18n.t('Cancel') }}</button>
                    </form>
                  } @else {
                    <h3>
                      <button type="button" class="meal-name" (click)="editMeal(meal)" [title]="i18n.t('Rename or set the time')">{{ meal.name }}</button>
                      @if (meal.time) { <span class="v-muted v-small"> {{ meal.time }}</span> }
                    </h3>
                  }
                  <span class="v-actions">
                    <button type="button" class="v-btn quiet small" (click)="adding.set(adding() === meal.id ? null : meal.id)">
                      {{ i18n.t(adding() === meal.id ? 'Cancel' : 'Add item') }}
                    </button>
                    <button type="button" class="v-btn quiet small danger" (click)="deleteMeal(meal)" [disabled]="meal.line_items.length > 0"
                      [title]="i18n.t(meal.line_items.length ? 'Delete or move the items first' : 'Delete this meal')">{{ i18n.t('Delete') }}</button>
                  </span>
                </header>
                @if (adding() === meal.id) {
                  <div class="add">
                    @if (!pending()) {
                      <v-product-search [on]="date()" (picked)="pending.set($event)" />
                    } @else {
                      <form class="v-form-row" (ngSubmit)="addItem(meal)">
                        <div class="picked">{{ pending()!.name }} <button type="button" class="v-btn quiet small" (click)="pending.set(null)">{{ i18n.t('change') }}</button></div>
                        <label class="v-field"><span>{{ i18n.t('Amount') }}</span><input name="amount" type="number" step="any" min="0" [(ngModel)]="amount" required /></label>
                        <label class="v-field"><span>{{ i18n.t('Unit') }}</span>
                          <select name="unit" [ngModel]="unitCode()" (ngModelChange)="unitCode.set($event)">
                            <optgroup [attr.label]="i18n.t('Weight and volume')">
                              @for (u of measuredUnits(); track u.code) { <option [value]="u.code">{{ i18n.t(u.singular) }}</option> }
                            </optgroup>
                            @if (pending()!.portions?.length) {
                              <optgroup [attr.label]="i18n.t('Portions of this product')">
                                @for (p of pending()!.portions ?? []; track p.id) { <option [value]="'portion:' + p.id">{{ i18n.t(p.label) }} ({{ amountText(p.amount) }} {{ i18n.t(p.amount_unit) }})</option> }
                              </optgroup>
                            }
                            <optgroup [attr.label]="i18n.t('Needs a size once')">
                              @for (u of undeclaredUnits(); track u.code) { <option [value]="u.code">{{ i18n.t(u.singular) }}</option> }
                            </optgroup>
                          </select>
                        </label>
                        @if (needsSize()) {
                          <label class="v-field size-field">
                            <span>{{ i18n.t('One {unit} is', { unit: unitLabel() }) }}</span>
                            <span class="size">
                              <input name="psize" type="number" step="any" min="0" [(ngModel)]="portionAmount" required />
                              <span class="fixed">{{ pending()!.reference_unit }}</span>
                            </span>
                          </label>
                          <p class="v-small v-muted hint">{{ i18n.t('Saved with {product}, so “{unit}” works from now on.', { product: pending()!.name, unit: unitLabel() }) }}</p>
                        }
                        <label class="v-field check"><span>{{ i18n.t('Estimated') }}</span><input name="est" type="checkbox" [(ngModel)]="estimated" /></label>
                        <button type="submit" class="v-btn primary" [disabled]="!amount || (needsSize() && !portionAmount)">{{ i18n.t('Add') }}</button>
                      </form>
                    }
                  </div>
                }
                <div class="v-scroll-x">
                  <table class="v-table">
                    <thead><tr><th>{{ i18n.t('Item') }}</th><th class="num">{{ i18n.t('Amount') }}</th><th class="num">kcal</th><th class="num">P</th><th class="num v-hide-m">C</th><th class="num v-hide-m">F</th><th class="num v-hide-m">Fi</th><th class="num v-hide-m">S</th><th></th></tr></thead>
                    <tbody>
                      @for (it of meal.line_items; track it.id) {
                        <tr [class.draft]="it.is_draft" [class.estimated]="it.estimated || it.amount_estimated" [attr.data-item]="it.id">
                          <td>
                            <v-food-icon [name]="it.consumable_name" [category]="it.category" [kind]="it.consumable_kind" [icon]="it.icon" />
                            @if (it.consumable_kind === 'product') {
                              <a [routerLink]="['/products', it.consumable_id]" [title]="i18n.t('Open the product')">{{ it.consumable_name }}</a>
                            } @else if (it.consumable_kind === 'recipe_batch') {
                              <a [routerLink]="['/recipes']" [title]="i18n.t('Recipes')">{{ it.consumable_name }}</a>
                            } @else { {{ it.consumable_name }} }
                            @if (it.is_draft) { <span class="v-tag draft">{{ i18n.t('draft') }}</span> }
                            @if (it.estimated || it.amount_estimated) { <span class="warn-mark" [title]="i18n.t('estimated')">⚠️</span> }
                            @if (it.consumable_kind === 'ad_hoc') { <span class="v-tag">{{ i18n.t('unmatched') }}</span> }
                          </td>
                          <td class="num">{{ amountText(it.amount ?? it.base_amount) }} {{ unitOf(it) }}</td>
                          <td class="num">{{ it.kcal | macro: 'kcal' }}</td>
                          <td class="num">{{ it.protein | macro: 'protein' }}</td>
                          <td class="num v-hide-m">{{ it.carbs | macro: 'carbs' }}</td>
                          <td class="num v-hide-m">{{ it.fat | macro: 'fat' }}</td>
                          <td class="num v-hide-m">{{ it.fiber | macro: 'fiber' }}</td>
                          <td class="num v-hide-m">{{ it.salt | macro: 'salt' }}</td>
                          <td class="row-actions">
                            @if (it.is_draft) { <button type="button" class="v-btn small primary" (click)="acceptItem(it)" [title]="i18n.t('Accept this drafted item')">{{ i18n.t('Accept') }}</button> }
                            <button type="button" class="v-btn quiet small" (click)="editAmount(it)">{{ i18n.t('edit') }}</button>
                            <button type="button" class="v-btn quiet small danger" (click)="remove(it)">{{ i18n.t('remove') }}</button>
                          </td>
                        </tr>
                      } @empty {
                        <tr><td colspan="9" class="v-muted">{{ i18n.t('Nothing logged in this meal.') }}</td></tr>
                      }
                      <tr class="total">
                        <td>{{ i18n.t('Total') }}</td><td></td>
                        <td class="num">{{ meal.totals.kcal | macro: 'kcal' }}</td>
                        <td class="num">{{ meal.totals.protein | macro: 'protein' }}</td>
                        <td class="num v-hide-m">{{ meal.totals.carbs | macro: 'carbs' }}</td>
                        <td class="num v-hide-m">{{ meal.totals.fat | macro: 'fat' }}</td>
                        <td class="num v-hide-m">{{ meal.totals.fiber | macro: 'fiber' }}</td>
                        <td class="num v-hide-m">{{ meal.totals.salt | macro: 'salt' }}</td><td></td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>
            }
            <form class="new-meal" (ngSubmit)="addMeal()">
              <input name="meal" [(ngModel)]="newMeal" [placeholder]="i18n.t('New meal, e.g. Lunch')" />
              <button type="submit" class="v-btn" [disabled]="!newMeal.trim()">{{ i18n.t('Add meal') }}</button>
            </form>
          </section>
          <v-day-thread [date]="date()" [revision]="threadRevision()" />
        </div>
      } @else if (!error() && !missing()) {
        <p class="v-muted">{{ i18n.t('Loading…') }}</p>
      }
    </div>
  `,
  styles: `
    // Three loose links were hard to hit and read as body text. As one pill they read as
    // what they are: a switch between neighbouring days, with the list in the middle.
    .daynav {
      display: inline-flex;
      align-items: stretch;
      gap: 2px;
      width: max-content;
      max-width: 100%;
      margin-bottom: 0.5rem;
      padding: 2px;
      border: 1px solid var(--v-line);
      border-radius: 999px;
      background: var(--v-surface);

      a {
        display: inline-flex;
        align-items: center;
        gap: 0.3rem;
        min-height: 1.9rem;
        padding: 0 0.7rem;
        border-radius: 999px;
        color: var(--v-ink-2);
        text-decoration: none;
        font-size: var(--v-fs-s);
        white-space: nowrap;
        &:hover { background: var(--v-surface-2); color: var(--v-ink); }
      }
      .all { color: var(--v-ink); }
    }
    .create-day { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.75rem; margin-bottom: 1.25rem; }
    .create-day form { align-items: end; }
    .sub { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
    .gauges { display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: 1rem 1.5rem; padding: 1rem 1.25rem; margin-bottom: 1.25rem; background: var(--v-surface); border: 1px solid var(--v-line); border-radius: var(--v-radius-l); }
    .columns { display: grid; grid-template-columns: minmax(0, 2fr) minmax(16rem, 1fr); gap: 1.5rem; align-items: start; }
    .ledger { display: grid; grid-template-columns: minmax(0, 1fr); gap: 1.25rem; }
    .drafts-bar { display: flex; justify-content: space-between; gap: 1rem; align-items: center; flex-wrap: wrap; }
    // The name takes the line it needs; the actions stay together and keep to the right,
    // on their own row when the name is long. Before this, "Delete" wrapped on its own and
    // landed in the middle of the panel.
    .meal header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 0.15rem 0.75rem; margin-bottom: 0.35rem; }
    .meal header > .v-actions { margin-left: auto; }
    .meal h3 { font-size: var(--v-fs-m); margin: 0; }
    // A product's full name can be a sentence. Two lines of it are enough to recognise it
    // by; the rest is one hover (or one tap on the link) away.
    .ledger .v-table td:first-child { max-width: 22rem; }
    .ledger .v-table td:first-child a {
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .meal-name { all: unset; cursor: text; border-bottom: 1px dashed transparent; } .meal-name:hover { border-bottom-color: var(--v-line-strong); }
    .meal-edit { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; }
    .meal-edit input { padding: 0.3rem 0.5rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); }
    .add { padding: 0.75rem; margin-bottom: 0.5rem; border: 1px solid var(--v-line); border-radius: var(--v-radius-l); background: var(--v-surface); }
    .picked { align-self: end; font-weight: 500; }
    .check { align-items: center; grid-template-columns: auto auto; }
    .size-field { grid-column: 1 / -1; }
    .size { display: flex; gap: 0.4rem; align-items: center; }
    .size .fixed { color: var(--v-ink-2); font-size: var(--v-fs-s); }
    .size input { min-width: 5rem; }
    .add .hint { grid-column: 1 / -1; margin: 0; }
    tr.draft td { background: var(--v-agent-soft); }
    .warn-mark { margin-left: 0.25rem; }
    .row-actions { white-space: nowrap; text-align: right; }
    .new-meal { display: flex; flex-wrap: wrap; gap: 0.5rem; }
    .new-meal input { flex: 1 1 12rem; padding: 0.45rem 0.6rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); }
    @media (max-width: 64rem) { .columns { grid-template-columns: 1fr; } }
    // A phone: the switcher spans the width with thumb-sized ends, the words drop out, and
    // anything that would otherwise sit in a half-empty row takes the full line.
    @media (max-width: 40rem) {
      .daynav { display: flex; width: 100%; }
      .daynav .word { display: none; }
      .daynav .step { min-width: 3rem; min-height: 2.4rem; justify-content: center; font-size: var(--v-fs-m); }
      .daynav .all { flex: 1; justify-content: center; }
      .new-meal { flex-direction: column; }
      .new-meal .v-btn { width: 100%; justify-content: center; }
      .add .v-btn[type='submit'] { width: 100%; justify-content: center; }
    }
  `,
})
export class DayView {
  private readonly api = inject(ApiClient);
  readonly i18n = inject(I18nService);
  readonly format = inject(FormatService);
  readonly date = input.required<string>();
  readonly day = signal<DayLog | null>(null);
  readonly error = signal<string | null>(null);
  /** True when GET /days/{date} answered 404: the day has not been created yet. */
  readonly missing = signal(false);
  readonly units = signal<Unit[]>([]);
  /** Raised when an approval changed a capture, so the thread and the badges catch up. */
  readonly threadRevision = signal(0);
  readonly adding = signal<number | null>(null);
  readonly pending = signal<Product | null>(null);
  readonly prev = computed(() => shiftDate(this.date(), -1));
  readonly next = computed(() => shiftDate(this.date(), 1));
  /** Grams and millilitres always work; they need no portion. */
  readonly measuredUnits = computed(() => {
    // A product declared per 100 g cannot be measured in millilitres: it carries no
    // density, and the server would refuse the item. Offer its own family only.
    const family = this.pending()?.reference_unit === 'ml' ? 'volume' : 'mass';
    return this.units().filter((u) => u.unit_type === family);
  });

  /**
   * Count units this product has no portion for. Offering them without saying so was the
   * whole problem: the item was rejected on save with "no portion for unit" (R73).
   */
  readonly undeclaredUnits = computed(() => {
    const declared = new Set((this.pending()?.portions ?? []).map((p) => p.unit_code));
    return this.units().filter((u) => u.unit_type === 'count' && !declared.has(u.code));
  });

  readonly needsSize = computed(() =>
    this.undeclaredUnits().some((u) => u.code === this.unitCode()),
  );

  readonly unitLabel = computed(() =>
    this.i18n.t(this.units().find((u) => u.code === this.unitCode())?.singular ?? this.unitCode()),
  );

  /** The unit an item was logged in, with the portion when the unit alone is ambiguous.
   *
   * One unit can have several portions — a piece of egg is S, M, L or XL — so "1 Stück"
   * would stand for anything between 43 and 65 g.
   */
  unitOf(it: LineItem): string {
    const unit = this.i18n.t(it.unit_code ?? it.base_unit);
    // a label that only repeats the unit's own word would read "1 Stück (Stück)"
    const named = it.portion_label && it.portion_label !== it.unit_code;
    return named ? `${unit} (${this.i18n.t(it.portion_label!)})` : unit;
  }

  /** An amount as it is written here: a whole number stays whole, a fraction keeps one place. */
  amountText(value: number | null | undefined): string {
    if (value == null) return '–';
    return this.format.number(value, Number.isInteger(value) ? 0 : 1);
  }

  readonly macroKeys = MACRO_KEYS;
  readonly label = MACRO_LABEL;
  readonly unit = MACRO_UNIT;
  amount: number | null = null;
  /** A signal, because needsSize() and unitLabel() are derived from it. */
  readonly unitCode = signal('g');
  /** Size of a unit the chosen product has no portion for; stored with the product. */
  portionAmount: number | null = null;
  estimated = false;
  newMeal = '';
  readonly editingMeal = signal<number | null>(null);
  mealName = '';
  mealTime = '';
  newReliable = 'true';
  newTraining = 'rest';

  constructor() {
    this.api.units().subscribe({ next: (u) => this.units.set(u), error: () => this.units.set([{ code: 'g', singular: 'g', plural: 'g', unit_type: 'mass' }, { code: 'ml', singular: 'ml', plural: 'ml', unit_type: 'volume' }]) });
    effect(() => {
      this.date();
      this.reload();
    });
  }

  bandFor(d: DayLog, k: MacroKey) {
    return d.target_band ? d.target_band[k] ?? null : null;
  }

  reload(): void {
    this.error.set(null);
    this.missing.set(false);
    this.api.day(this.date()).subscribe({
      next: (d) => this.day.set(d),
      error: (e: unknown) => {
        if (e instanceof HttpErrorResponse && e.status === 404) {
          this.day.set(null);
          this.missing.set(true);
        } else {
          this.error.set(describeError(e));
        }
      },
    });
  }

  createDay(): void {
    this.api
      .createDay(this.date(), { reliable: this.newReliable === 'true', training_type: this.newTraining || null })
      .subscribe({
        next: (d) => {
          this.missing.set(false);
          this.day.set(d);
        },
        error: (e: unknown) => this.error.set(describeError(e)),
      });
  }

  private apply(obs: { subscribe: (o: { next: (d: DayLog) => void; error: (e: unknown) => void }) => unknown }): void {
    obs.subscribe({ next: (d) => this.day.set(d), error: (e) => this.error.set(describeError(e)) });
  }

  setTraining(v: string): void {
    this.apply(this.api.updateDay(this.date(), { training_type: (v || null) as TrainingType | null }));
  }
  setReliable(v: string): void {
    if (v === '') return;
    this.apply(this.api.updateDay(this.date(), { reliable: v === 'true' }));
  }
  close(): void {
    this.apply(this.api.closeDay(this.date()));
  }
  reopen(): void {
    this.apply(this.api.reopenDay(this.date()));
  }

  editMeal(meal: Meal): void {
    this.editingMeal.set(meal.id);
    this.mealName = meal.name;
    this.mealTime = meal.time ? meal.time.slice(0, 5) : '';
  }

  saveMeal(meal: Meal): void {
    const name = this.mealName.trim();
    if (!name) return;
    this.api.updateMeal(meal.id, { name, time: this.mealTime || null }).subscribe({
      next: () => {
        this.editingMeal.set(null);
        this.reload();
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  deleteMeal(meal: Meal): void {
    if (meal.line_items.length) return;
    this.api.deleteMeal(meal.id).subscribe({
      next: () => this.reload(),
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  acceptItem(it: LineItem): void {
    this.api.approveLineItem(it.id).subscribe({
      next: () => this.approved(),
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  acceptAll(): void {
    this.api.approveDraft(this.date(), { corrections: [], close: false }).subscribe({
      next: () => this.approved(),
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  /** An approval touches the day, the captures behind it and the inbox count. */
  private approved(): void {
    this.reload();
    this.threadRevision.update((n) => n + 1);
  }

  addMeal(): void {
    const name = this.newMeal.trim();
    if (!name) return;
    this.api.addMeal(this.date(), { name }).subscribe({
      next: () => {
        this.newMeal = '';
        this.reload();
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  addItem(meal: Meal): void {
    const p = this.pending();
    if (!p || !this.amount) return;
    // a unit without a portion is declared once, then used like any other
    if (this.needsSize()) {
      if (!this.portionAmount) return;
      const code = this.unitCode();
      // the unit's own word, not the translated one: a label is data and outlives the
      // language it was typed in
      const label = this.units().find((u) => u.code === code)?.singular ?? code;
      this.api
        .createPortion(p.id, {
          unit_code: code,
          label,
          amount: this.portionAmount,
          amount_unit: p.reference_unit,
          is_default: true,
          weight_source: this.estimated ? 'estimated' : 'weighed',
        })
        .subscribe({
          next: (portion) => {
            this.pending.update((prod) =>
              prod ? { ...prod, portions: [...(prod.portions ?? []), portion] } : prod,
            );
            this.unitCode.set('portion:' + portion.id);
            this.portionAmount = null;
            this.addItem(meal);
          },
          error: (e: unknown) => this.error.set(describeError(e)),
        });
      return;
    }
    const chosen = this.unitCode();
    const portionId = chosen.startsWith('portion:') ? Number(chosen.slice(8)) : null;
    const portion = portionId ? p.portions?.find((x) => x.id === portionId) : undefined;
    this.api
      .addLineItem(meal.id, {
        consumable_id: p.id,
        amount: this.amount,
        unit_code: portion ? portion.unit_code : chosen,
        portion_id: portionId,
        estimated: this.estimated,
      })
      .subscribe({
        next: () => {
          this.pending.set(null);
          this.adding.set(null);
          this.amount = null;
          this.estimated = false;
          this.unitCode.set('g');
          this.portionAmount = null;
          this.reload();
        },
        error: (e: unknown) => this.error.set(describeError(e)),
      });
  }

  editAmount(it: LineItem): void {
    const v = window.prompt(
      this.i18n.t('Amount for {name} ({unit})', {
        name: it.consumable_name,
        unit: this.unitOf(it),
      }),
      String(it.amount ?? it.base_amount),
    );
    if (v === null) return;
    const amount = Number(v.replace(',', '.'));
    if (!Number.isFinite(amount) || amount <= 0) return;
    this.api.updateLineItem(it.id, { amount }).subscribe({ next: () => this.reload(), error: (e: unknown) => this.error.set(describeError(e)) });
  }

  remove(it: LineItem): void {
    this.api.deleteLineItem(it.id).subscribe({ next: () => this.reload(), error: (e: unknown) => this.error.set(describeError(e)) });
  }
}
