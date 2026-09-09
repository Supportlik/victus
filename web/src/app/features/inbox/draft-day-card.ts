import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiClient, Capture, DayLog, DraftListEntry, LineItem } from '../../api';
import { I18nService } from '../../core/i18n.service';
import { describeError } from '../../core/problem';
import { CaptureCard } from '../../shared/capture-card';
import { FoodIcon } from '../../shared/food-icon';
import { DayNamePipe, MacroPipe } from '../../shared/format';
import { MarkdownPipe } from '../../shared/markdown.pipe';

interface Row {
  item: LineItem;
  meal: string;
  amount: number;
  consumableId: number;
  /** Meal to accept into: an existing id, or 'new' with `newMeal`. */
  mealChoice: number | 'new';
  newMeal: string;
  source: Capture | null;
  busy: boolean;
}

/**
 * One drafted day on the inbox screen: every item next to the capture it came from,
 * acceptable on its own or all at once. The captures stay until their item is accepted.
 */
@Component({
  selector: 'v-draft-day-card',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, MacroPipe, DayNamePipe, MarkdownPipe, CaptureCard, FoodIcon],
  template: `
    <section class="v-panel day" [attr.data-draft-day]="entry().date">
      <header>
        <div>
          <h3><a [routerLink]="['/days', entry().date]">{{ entry().date | dayName }}</a></h3>
          <p class="v-small v-muted">
            {{ rows().length === 1 ? i18n.t('{n} item waiting', { n: rows().length }) : i18n.t('{n} items waiting', { n: rows().length }) }}
            @if (day(); as d) { · {{ i18n.t('day total') }} {{ d.macros.kcal | macro: 'kcal' }} kcal }
            @if (entry().estimated_items; as n) { · {{ n === 1 ? i18n.t('{n} estimate', { n }) : i18n.t('{n} estimates', { n }) }} }
          </p>
        </div>
        <div class="v-actions">
          <button type="button" class="v-btn primary" (click)="approveAll()" [disabled]="busy() || !rows().length">{{ i18n.t('Accept all') }}</button>
          @if (confirmDiscard()) {
            <span class="v-small">{{ i18n.t('Discard the whole draft?') }}</span>
            <button type="button" class="v-btn small danger" (click)="discardAll()" [disabled]="busy()">{{ i18n.t('Yes') }}</button>
            <button type="button" class="v-btn small quiet" (click)="confirmDiscard.set(false)">{{ i18n.t('No') }}</button>
          } @else {
            <button type="button" class="v-btn quiet danger" (click)="confirmDiscard.set(true)" [disabled]="busy()">{{ i18n.t('Discard draft') }}</button>
          }
        </div>
      </header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }

      <ul class="rows">
        @for (r of rows(); track r.item.id) {
          <li class="row" [attr.data-item]="r.item.id">
            <div class="what">
              <div class="head">
                <v-food-icon [name]="r.item.consumable_name" [category]="r.item.category ?? null" [kind]="r.item.consumable_kind" [icon]="r.item.icon" />
                @if (r.item.alternatives?.length && r.item.alternatives!.length > 1) {
                  <select [name]="'c' + r.item.id" [(ngModel)]="r.consumableId" class="pick">
                    <option [ngValue]="r.item.consumable_id">{{ r.item.consumable_name }}</option>
                    @for (a of r.item.alternatives; track a.consumable_id) {
                      @if (a.consumable_id !== r.item.consumable_id) { <option [ngValue]="a.consumable_id">{{ a.name }} ({{ (a.score * 100).toFixed(0) }} %)</option> }
                    }
                  </select>
                } @else {
                  <span class="name">{{ r.item.consumable_name }}</span>
                }
                @if (r.item.estimated || r.item.amount_estimated) { <span class="v-tag warn" [title]="i18n.t('estimated')">{{ i18n.t('estimate') }}</span> }
                @if (r.item.confidence != null) { <span class="conf" [class.low]="r.item.confidence < 0.7">{{ (r.item.confidence * 100).toFixed(0) }} %</span> }
              </div>
              <div class="numbers">
                <label class="qty"><span class="v-small v-muted">{{ i18n.t('Amount') }}</span>
                  <input [name]="'a' + r.item.id" type="number" step="any" min="0" [(ngModel)]="r.amount" />
                  <span class="unit">{{ r.item.unit_code ?? r.item.base_unit }}</span>
                </label>
                <span class="kcal">{{ r.item.kcal | macro: 'kcal' }} kcal</span>
                <label class="meal"><span class="v-small v-muted">{{ i18n.t('Meal') }}</span>
                  <select [name]="'m' + r.item.id" [(ngModel)]="r.mealChoice">
                    @for (m of meals(); track m.id) { <option [ngValue]="m.id">{{ m.name }}</option> }
                    <option ngValue="new">{{ i18n.t('new meal…') }}</option>
                  </select>
                  @if (r.mealChoice === 'new') {
                    <input [name]="'mn' + r.item.id" [(ngModel)]="r.newMeal" [placeholder]="i18n.t('Meal name')" [attr.aria-label]="i18n.t('New meal name')" />
                  }
                </label>
              </div>
              @if (r.item.rationale) { <p class="why v-small v-muted">{{ r.item.rationale }}</p> }
              <div class="v-actions">
                <button type="button" class="v-btn small primary" (click)="approve(r)" [disabled]="r.busy || busy()">{{ i18n.t('Accept') }}</button>
                <button type="button" class="v-btn small quiet danger" (click)="drop(r)" [disabled]="r.busy || busy()">{{ i18n.t('Drop') }}</button>
              </div>
            </div>
            <div class="source">
              @if (r.source) {
                <v-capture-card [capture]="r.source" [compact]="true" [showTarget]="false" [readonly]="true" />
              } @else if (r.item.raw_text) {
                <p class="raw v-small">“{{ r.item.raw_text }}”</p>
              } @else {
                <p class="v-small v-muted">{{ i18n.t('No source recorded.') }}</p>
              }
            </div>
          </li>
        } @empty {
          <li class="v-muted v-small">{{ i18n.t('Nothing left to accept here.') }}</li>
        }
      </ul>

      @if (summary()) {
        <details class="agent">
          <summary>{{ i18n.t('Agent summary') }}</summary>
          <div class="v-md" [innerHTML]="summary() | markdown"></div>
        </details>
      }
    </section>
  `,
  styles: `
    .day { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.75rem; }
    .day > header { display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; align-items: start; }
    .day h3 { font-size: var(--v-fs-l); } .day h3 a { color: inherit; text-decoration: none; } .day h3 a:hover { text-decoration: underline; }
    .rows { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.6rem; }
    .row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 20rem); gap: 0.75rem; padding: 0.6rem; border: 1px solid var(--v-line); border-left: 3px solid var(--v-agent); border-radius: var(--v-radius-l); background: var(--v-surface-2); }
    .what { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.4rem; min-width: 0; }
    .head { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; }
    .name { font-weight: 500; }
    .pick { max-width: 22rem; padding: 0.25rem 0.4rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); }
    .conf { font-size: var(--v-fs-xs); color: var(--v-ink-3); } .conf.low { color: var(--v-warn-ink); }
    .numbers { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; font-size: var(--v-fs-s); }
    .meal { display: inline-flex; gap: 0.35rem; align-items: center; }
    .meal select, .meal input { padding: 0.25rem 0.4rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); max-width: 11rem; }
    .qty { display: inline-flex; gap: 0.35rem; align-items: center; }
    .qty input { width: 5.5rem; padding: 0.25rem 0.4rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); text-align: right; }
    .kcal { font-variant-numeric: tabular-nums; }
    .why { margin: 0; }
    .raw { margin: 0; font-style: italic; }
    .agent summary { cursor: pointer; color: var(--v-ink-2); font-size: var(--v-fs-s); }
    @media (max-width: 60rem) { .row { grid-template-columns: 1fr; } }
  `,
})
export class DraftDayCard {
  private readonly api = inject(ApiClient);
  readonly i18n = inject(I18nService);
  readonly entry = input.required<DraftListEntry>();
  /** Captures of that day, so each item can show where it came from. */
  readonly captures = input<Capture[]>([]);
  readonly changed = output<void>();

  readonly day = signal<DayLog | null>(null);
  readonly summary = signal<string | null>(null);
  readonly rows = signal<Row[]>([]);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly confirmDiscard = signal(false);
  private loadedFor = '';

  readonly total = computed(() => this.rows().length);

  constructor() {
    effect(() => {
      const date = this.entry().date;
      if (date !== this.loadedFor) this.load();
    });
  }

  load(): void {
    const date = this.entry().date;
    this.loadedFor = date;
    this.api.draftSummary(date).subscribe({
      next: (s) => {
        this.day.set(s.day);
        this.summary.set(s.markdown);
        const byId = new Map(this.captures().map((c) => [c.id, c]));
        this.rows.set(
          s.day.meals.flatMap((m) =>
            m.line_items
              .filter((i) => i.is_draft)
              .map((item) => ({
                item,
                meal: m.name,
                amount: item.amount ?? item.base_amount,
                consumableId: item.consumable_id,
                mealChoice: item.meal_id as number | 'new',
                newMeal: '',
                source: item.source_capture_id ? (byId.get(item.source_capture_id) ?? null) : null,
                busy: false,
              })),
          ),
        );
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  /** Meals of the drafted day, for the per-item meal picker. */
  meals(): { id: number; name: string }[] {
    return (this.day()?.meals ?? []).map((m) => ({ id: m.id, name: m.name }));
  }

  approve(r: Row): void {
    const body: Record<string, unknown> = {};
    if (r.amount !== (r.item.amount ?? r.item.base_amount)) body['amount'] = r.amount;
    if (r.consumableId !== r.item.consumable_id) body['consumable_id'] = r.consumableId;
    if (r.mealChoice === 'new') {
      if (!r.newMeal.trim()) {
        this.error.set(this.i18n.t('Give the new meal a name.'));
        return;
      }
      body['meal_name'] = r.newMeal.trim();
    } else if (r.mealChoice !== r.item.meal_id) {
      body['meal_id'] = r.mealChoice;
    }
    r.busy = true;
    this.api.approveLineItem(r.item.id, body).subscribe({
      next: () => this.done(),
      error: (e: unknown) => this.fail(e, r),
    });
  }

  drop(r: Row): void {
    r.busy = true;
    this.api.deleteLineItem(r.item.id).subscribe({
      next: () => this.done(),
      error: (e: unknown) => this.fail(e, r),
    });
  }

  approveAll(): void {
    this.busy.set(true);
    const corrections = this.rows()
      .filter((r) => r.amount !== (r.item.amount ?? r.item.base_amount) || r.consumableId !== r.item.consumable_id)
      .map((r) => ({ line_item_id: r.item.id, amount: r.amount, consumable_id: r.consumableId }));
    this.api.approveDraft(this.entry().date, { corrections, close: false }).subscribe({
      next: () => this.done(),
      error: (e: unknown) => this.fail(e),
    });
  }

  discardAll(): void {
    this.busy.set(true);
    this.confirmDiscard.set(false);
    this.api.discardDraft(this.entry().date).subscribe({
      next: () => this.done(),
      error: (e: unknown) => this.fail(e),
    });
  }

  private done(): void {
    this.busy.set(false);
    this.changed.emit();
  }

  private fail(e: unknown, r?: Row): void {
    this.error.set(describeError(e));
    this.busy.set(false);
    if (r) r.busy = false;
  }
}
