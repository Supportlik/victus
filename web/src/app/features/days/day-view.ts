import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiClient, DayLog, LineItem, MACRO_KEYS, MACRO_LABEL, MACRO_UNIT, MacroKey, Meal, Product, TrainingType, Unit } from '../../api';
import { HttpErrorResponse } from '@angular/common/http';
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
            <a [routerLink]="['/days', prev()]">← previous</a>
            <a routerLink="/days">all days</a>
            <a [routerLink]="['/days', next()]">next →</a>
          </nav>
          <h2>{{ date() | dayName }}</h2>
          @if (day(); as d) {
            <p class="sub">
              <v-status-tag [status]="d.status" />
              @if (d.reliable === false) { <span class="v-tag warn">estimated day</span> }
              @if (d.reliable === null) { <span class="v-tag bad">reliable flag missing</span> }
              @if (d.target_band) { <span class="v-muted">band: {{ d.target_band.name }}</span> }
            </p>
          }
        </div>
        @if (day(); as d) {
          <div class="v-actions">
            <label class="v-field"><span>Training</span>
              <select [ngModel]="d.training_type ?? ''" (ngModelChange)="setTraining($event)">
                <option value="">none / rest</option><option value="rest">rest</option><option value="strength">strength</option><option value="martial_arts">martial arts</option>
              </select>
            </label>
            <label class="v-field"><span>Reliable</span>
              <select [ngModel]="d.reliable === null ? '' : d.reliable ? 'true' : 'false'" (ngModelChange)="setReliable($event)">
                <option value="" disabled>choose</option><option value="true">yes, counts</option><option value="false">no, whole day estimated</option>
              </select>
            </label>
            @if (d.status === 'closed') {
              <button type="button" class="v-btn" (click)="reopen()">Reopen day</button>
            } @else if (d.status === 'open') {
              <button type="button" class="v-btn primary" (click)="close()">Close day</button>
            } @else {
              <a class="v-btn primary" [routerLink]="['/drafts', date()]">Review draft</a>
            }
          </div>
        }
      </header>

      @if (missing()) {
        <section class="v-panel create-day">
          <h3>Nothing logged for this day yet</h3>
          <p class="v-small v-muted">Create the day to start adding meals. Say whether it will count: a day you only estimate as a whole (travel, party) does not enter the statistics.</p>
          <form class="v-form-row" (ngSubmit)="createDay()">
            <label class="v-field"><span>Counts for statistics?</span>
              <select name="rel" [(ngModel)]="newReliable" required>
                <option value="true">yes, I log it properly</option>
                <option value="false">no, whole day estimated</option>
              </select>
            </label>
            <label class="v-field"><span>Training</span>
              <select name="tt" [(ngModel)]="newTraining">
                <option value="">none / rest</option><option value="rest">rest</option><option value="strength">strength</option><option value="martial_arts">martial arts</option>
              </select>
            </label>
            <button type="submit" class="v-btn primary">Create this day</button>
          </form>
        </section>
      } @else if (error(); as e) { <div class="v-error">{{ e }}</div> }

      @if (day(); as d) {
        <section class="gauges" aria-label="Targets">
          @for (k of macroKeys; track k) {
            <v-band-gauge [macro]="k" [label]="label[k]" [unit]="unit[k]" [value]="d.macros[k]" [band]="bandFor(d, k)" [zone]="d.zones?.[k]" />
          }
        </section>

        @if (d.findings.length) {
          <div class="v-notice">
            @for (f of d.findings; track f.code + f.message) { <div>{{ f.message }}</div> }
          </div>
        }

        <div class="columns">
          <section class="ledger">
            @if (d.has_drafts) {
              <div class="v-notice drafts-bar">
                <span>This day has draft items from the agent. Accept them one by one below, or all at once.</span>
                <span class="v-actions">
                  <button type="button" class="v-btn small primary" (click)="acceptAll()">Accept all</button>
                  <a class="v-btn small" routerLink="/inbox">Open the inbox</a>
                </span>
              </div>
            }
            @for (meal of d.meals; track meal.id) {
              <article class="meal">
                <header>
                  @if (editingMeal() === meal.id) {
                    <form class="meal-edit" (ngSubmit)="saveMeal(meal)">
                      <input name="mn{{ meal.id }}" [(ngModel)]="mealName" aria-label="Meal name" required />
                      <input name="mt{{ meal.id }}" type="time" [(ngModel)]="mealTime" aria-label="Meal time" />
                      <button type="submit" class="v-btn small primary" [disabled]="!mealName.trim()">Save</button>
                      <button type="button" class="v-btn small quiet" (click)="editingMeal.set(null)">Cancel</button>
                    </form>
                  } @else {
                    <h3>
                      <button type="button" class="meal-name" (click)="editMeal(meal)" title="Rename or set the time">{{ meal.name }}</button>
                      @if (meal.time) { <span class="v-muted v-small"> {{ meal.time }}</span> }
                    </h3>
                  }
                  <span class="v-actions">
                    <button type="button" class="v-btn quiet small" (click)="adding.set(adding() === meal.id ? null : meal.id)">
                      {{ adding() === meal.id ? 'Cancel' : 'Add item' }}
                    </button>
                    <button type="button" class="v-btn quiet small danger" (click)="deleteMeal(meal)" [disabled]="meal.line_items.length > 0"
                      [title]="meal.line_items.length ? 'Delete or move the items first' : 'Delete this meal'">Delete</button>
                  </span>
                </header>
                @if (adding() === meal.id) {
                  <div class="add">
                    @if (!pending()) {
                      <v-product-search (picked)="pending.set($event)" />
                    } @else {
                      <form class="v-form-row" (ngSubmit)="addItem(meal)">
                        <div class="picked">{{ pending()!.name }} <button type="button" class="v-btn quiet small" (click)="pending.set(null)">change</button></div>
                        <label class="v-field"><span>Amount</span><input name="amount" type="number" step="any" min="0" [(ngModel)]="amount" required /></label>
                        <label class="v-field"><span>Unit</span>
                          <select name="unit" [(ngModel)]="unitCode">
                            @for (u of units(); track u.code) { <option [value]="u.code">{{ u.singular }}</option> }
                            @for (p of pending()!.portions ?? []; track p.id) { <option [value]="'portion:' + p.id">{{ p.label }} ({{ p.amount }} {{ p.amount_unit }})</option> }
                          </select>
                        </label>
                        <label class="v-field check"><span>Estimated</span><input name="est" type="checkbox" [(ngModel)]="estimated" /></label>
                        <button type="submit" class="v-btn primary" [disabled]="!amount">Add</button>
                      </form>
                    }
                  </div>
                }
                <div class="v-scroll-x">
                  <table class="v-table">
                    <thead><tr><th>Item</th><th class="num">Amount</th><th class="num">kcal</th><th class="num">P</th><th class="num v-hide-m">C</th><th class="num v-hide-m">F</th><th class="num v-hide-m">Fi</th><th class="num v-hide-m">S</th><th></th></tr></thead>
                    <tbody>
                      @for (it of meal.line_items; track it.id) {
                        <tr [class.draft]="it.is_draft" [class.estimated]="it.estimated || it.amount_estimated" [attr.data-item]="it.id">
                          <td>
                            <v-food-icon [name]="it.consumable_name" [category]="it.category" [kind]="it.consumable_kind" />
                            {{ it.consumable_name }}
                            @if (it.is_draft) { <span class="v-tag draft">draft</span> }
                            @if (it.estimated || it.amount_estimated) { <span class="warn-mark" title="estimated">⚠️</span> }
                            @if (it.consumable_kind === 'ad_hoc') { <span class="v-tag">unmatched</span> }
                          </td>
                          <td class="num">{{ it.amount ?? it.base_amount }} {{ it.unit_code ?? it.base_unit }}</td>
                          <td class="num">{{ it.kcal | macro: 'kcal' }}</td>
                          <td class="num">{{ it.protein | macro: 'protein' }}</td>
                          <td class="num">{{ it.carbs | macro: 'carbs' }}</td>
                          <td class="num">{{ it.fat | macro: 'fat' }}</td>
                          <td class="num">{{ it.fiber | macro: 'fiber' }}</td>
                          <td class="num">{{ it.salt | macro: 'salt' }}</td>
                          <td class="row-actions">
                            @if (it.is_draft) { <button type="button" class="v-btn small primary" (click)="acceptItem(it)" title="Accept this drafted item">Accept</button> }
                            <button type="button" class="v-btn quiet small" (click)="editAmount(it)">edit</button>
                            <button type="button" class="v-btn quiet small danger" (click)="remove(it)">remove</button>
                          </td>
                        </tr>
                      } @empty {
                        <tr><td colspan="9" class="v-muted">Nothing logged in this meal.</td></tr>
                      }
                      <tr class="total">
                        <td>Total</td><td></td>
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
              <input name="meal" [(ngModel)]="newMeal" placeholder="New meal, e.g. Lunch" />
              <button type="submit" class="v-btn" [disabled]="!newMeal.trim()">Add meal</button>
            </form>
          </section>
          <v-day-thread [date]="date()" />
        </div>
      } @else if (!error() && !missing()) {
        <p class="v-muted">Loading…</p>
      }
    </div>
  `,
  styles: `
    .daynav { display: flex; gap: 1rem; margin-bottom: 0.25rem; }
    .create-day { display: grid; gap: 0.75rem; margin-bottom: 1.25rem; }
    .create-day form { align-items: end; }
    .sub { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
    .gauges { display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: 1rem 1.5rem; padding: 1rem 1.25rem; margin-bottom: 1.25rem; background: var(--v-surface); border: 1px solid var(--v-line); border-radius: var(--v-radius-l); }
    .columns { display: grid; grid-template-columns: minmax(0, 2fr) minmax(16rem, 1fr); gap: 1.5rem; align-items: start; }
    .ledger { display: grid; gap: 1.25rem; }
    .drafts-bar { display: flex; justify-content: space-between; gap: 1rem; align-items: center; flex-wrap: wrap; }
    .meal header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.25rem; }
    .meal h3 { font-size: var(--v-fs-m); }
    .meal-name { all: unset; cursor: text; border-bottom: 1px dashed transparent; } .meal-name:hover { border-bottom-color: var(--v-line-strong); }
    .meal-edit { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; }
    .meal-edit input { padding: 0.3rem 0.5rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); }
    .add { padding: 0.75rem; margin-bottom: 0.5rem; border: 1px solid var(--v-line); border-radius: var(--v-radius-l); background: var(--v-surface); }
    .picked { align-self: end; font-weight: 500; }
    .check { align-items: center; grid-template-columns: auto auto; }
    tr.draft td { background: var(--v-agent-soft); }
    .warn-mark { margin-left: 0.25rem; }
    .row-actions { white-space: nowrap; text-align: right; }
    .new-meal { display: flex; gap: 0.5rem; }
    .new-meal input { flex: 1; padding: 0.45rem 0.6rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); }
    @media (max-width: 64rem) { .columns { grid-template-columns: 1fr; } }
  `,
})
export class DayView {
  private readonly api = inject(ApiClient);
  readonly date = input.required<string>();
  readonly day = signal<DayLog | null>(null);
  readonly error = signal<string | null>(null);
  /** True when GET /days/{date} answered 404: the day has not been created yet. */
  readonly missing = signal(false);
  readonly units = signal<Unit[]>([]);
  readonly adding = signal<number | null>(null);
  readonly pending = signal<Product | null>(null);
  readonly prev = computed(() => shiftDate(this.date(), -1));
  readonly next = computed(() => shiftDate(this.date(), 1));
  readonly macroKeys = MACRO_KEYS;
  readonly label = MACRO_LABEL;
  readonly unit = MACRO_UNIT;
  amount: number | null = null;
  unitCode = 'g';
  estimated = false;
  newMeal = '';
  readonly editingMeal = signal<number | null>(null);
  mealName = '';
  mealTime = '';
  newReliable = 'true';
  newTraining = '';

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
      next: () => this.reload(),
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  acceptAll(): void {
    this.api.approveDraft(this.date(), { corrections: [], close: false }).subscribe({
      next: () => this.reload(),
      error: (e: unknown) => this.error.set(describeError(e)),
    });
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
    const portionId = this.unitCode.startsWith('portion:') ? Number(this.unitCode.slice(8)) : null;
    const portion = portionId ? p.portions?.find((x) => x.id === portionId) : undefined;
    this.api
      .addLineItem(meal.id, {
        consumable_id: p.id,
        amount: this.amount,
        unit_code: portion ? portion.unit_code : this.unitCode,
        portion_id: portionId,
        estimated: this.estimated,
      })
      .subscribe({
        next: () => {
          this.pending.set(null);
          this.adding.set(null);
          this.amount = null;
          this.estimated = false;
          this.unitCode = 'g';
          this.reload();
        },
        error: (e: unknown) => this.error.set(describeError(e)),
      });
  }

  editAmount(it: LineItem): void {
    const v = window.prompt(`Amount for ${it.consumable_name} (${it.unit_code ?? it.base_unit})`, String(it.amount ?? it.base_amount));
    if (v === null) return;
    const amount = Number(v.replace(',', '.'));
    if (!Number.isFinite(amount) || amount <= 0) return;
    this.api.updateLineItem(it.id, { amount }).subscribe({ next: () => this.reload(), error: (e: unknown) => this.error.set(describeError(e)) });
  }

  remove(it: LineItem): void {
    this.api.deleteLineItem(it.id).subscribe({ next: () => this.reload(), error: (e: unknown) => this.error.set(describeError(e)) });
  }
}
