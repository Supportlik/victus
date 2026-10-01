import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal, untracked, viewChildren } from '@angular/core';
import { RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { Observable, forkJoin, of, switchMap, throwError } from 'rxjs';
import { ApiClient, Capture, DayLog, DraftListEntry, LineItem, Unit } from '../../api';
import { I18nService } from '../../core/i18n.service';
import { describeError } from '../../core/problem';
import { CaptureCard } from '../../shared/capture-card';
import { FoodIcon } from '../../shared/food-icon';
import { DayNamePipe, MacroPipe } from '../../shared/format';
import { LineItemForm, MealChoice } from '../../shared/line-item-form';
import { MarkdownPipe } from '../../shared/markdown.pipe';

interface Row {
  item: LineItem;
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
  imports: [RouterLink, MacroPipe, DayNamePipe, MarkdownPipe, CaptureCard, FoodIcon, LineItemForm],
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
                @if (r.item.estimated || r.item.amount_estimated) { <span class="v-tag warn" [title]="i18n.t('estimated')">{{ i18n.t('estimate') }}</span> }
                @if (r.item.confidence != null) { <span class="conf" [class.low]="r.item.confidence < 0.7">{{ (r.item.confidence * 100).toFixed(0) }} %</span> }
                <span class="kcal">{{ r.item.kcal | macro: 'kcal' }} kcal</span>
              </div>
              <!-- every value the agent suggested is an input: product, amount, unit or
                   portion, meal and both estimate marks (R84) -->
              <v-line-item-form [item]="r.item" [units]="units()" [meals]="meals()" [day]="entry().date" [embedded]="true" />
              @if (r.item.rationale) { <p class="why v-small v-muted">{{ r.item.rationale }}</p> }
              <div class="v-actions">
                <button type="button" class="v-btn small" (click)="save(r)" [disabled]="r.busy || busy() || !canSave(r)">{{ i18n.t('Save') }}</button>
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
    .conf { font-size: var(--v-fs-xs); color: var(--v-ink-3); } .conf.low { color: var(--v-warn-ink); }
    .kcal { font-variant-numeric: tabular-nums; margin-left: auto; font-size: var(--v-fs-s); }
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
  /** The unit table, loaded once by the inbox for every card. */
  readonly units = input<Unit[]>([]);
  readonly changed = output<void>();

  readonly day = signal<DayLog | null>(null);
  readonly summary = signal<string | null>(null);
  readonly rows = signal<Row[]>([]);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly confirmDiscard = signal(false);
  /** One edit panel per row; Save, Accept and Accept all read what each one holds. */
  private readonly forms = viewChildren(LineItemForm);
  private loadedFor = '';

  readonly total = computed(() => this.rows().length);
  /** Meals of the drafted day, for the per-item meal picker. */
  readonly meals = computed<MealChoice[]>(() =>
    (this.day()?.meals ?? []).map((m) => ({ id: m.id, name: m.name })),
  );

  constructor() {
    // A newer entry for the same day arrives with every refresh of the inbox. The card
    // follows it unless something on it was touched: then it keeps what was typed (R83).
    effect(() => {
      const date = this.entry().date;
      untracked(() => {
        if (date !== this.loadedFor || !this.dirty()) this.load();
      });
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
                source: item.source_capture_id ? (byId.get(item.source_capture_id) ?? null) : null,
                busy: false,
              })),
          ),
        );
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  /** The edit panel of a row. */
  private formOf(r: Row): LineItemForm | undefined {
    return this.forms().find((f) => f.item().id === r.item.id);
  }

  /**
   * Whether a row here has been touched, so the screen around it leaves the card alone.
   *
   * A corrected amount, unit, portion, mark, product or meal, or a new meal's name half
   * typed: reloading would put the agent's own values back without a word (R83).
   */
  dirty(): boolean {
    return (
      this.busy() ||
      this.confirmDiscard() ||
      this.rows().some((r) => r.busy || (this.formOf(r)?.dirty() ?? false))
    );
  }

  /** Save is offered once there is something to save, and it can be saved. */
  canSave(r: Row): boolean {
    const form = this.formOf(r);
    return !!form && form.dirty() && form.ready();
  }

  /** What a row's panel holds, written; nothing when nothing was changed. */
  private persisted(r: Row): Observable<unknown> {
    const form = this.formOf(r);
    if (!form || !form.dirty()) return of(null);
    if (!form.ready()) {
      return throwError(() => new Error(this.i18n.t('Complete the correction of {name} first.', { name: r.item.consumable_name })));
    }
    return form.persist();
  }

  /** Correct the draft without accepting it: the item stays a draft, with the person's values. */
  save(r: Row): void {
    r.busy = true;
    this.error.set(null);
    this.persisted(r).subscribe({
      next: () => {
        r.busy = false;
        this.load();
      },
      error: (e: unknown) => this.fail(e, r),
    });
  }

  /** Accept one item with whatever its panel holds. */
  approve(r: Row): void {
    r.busy = true;
    this.error.set(null);
    this.persisted(r)
      .pipe(switchMap(() => this.api.approveLineItem(r.item.id, {})))
      .subscribe({
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

  /** Accept the day: every correction on screen is written first, the meal included. */
  approveAll(): void {
    this.busy.set(true);
    this.error.set(null);
    const writes = this.rows().map((r) => this.persisted(r));
    forkJoin(writes.length ? writes : [of(null)])
      .pipe(switchMap(() => this.api.approveDraft(this.entry().date, { corrections: [], close: false })))
      .subscribe({
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
    // an unfinished correction is said in words of its own; a refusal is read from the API
    this.error.set(e instanceof HttpErrorResponse ? describeError(e) : e instanceof Error ? e.message : describeError(e));
    this.busy.set(false);
    if (r) r.busy = false;
  }
}
