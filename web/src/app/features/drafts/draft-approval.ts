import { ChangeDetectionStrategy, Component, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ApiClient, ApproveRequest, DraftCorrection, DraftSummary, LineItem } from '../../api';
import { describeError } from '../../core/problem';
import { DayNamePipe, MacroPipe } from '../../shared/format';
import { MarkdownPipe } from '../../shared/markdown.pipe';

interface Row {
  item: LineItem;
  amount: number;
  consumableId: number;
  remove: boolean;
}

/**
 * Approve a drafted day: change quantities, pick another candidate from the agent's
 * alternatives, drop items, then approve (optionally closing the day) or discard.
 */
@Component({
  selector: 'v-draft-approval',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, MacroPipe, DayNamePipe, MarkdownPipe],
  template: `
    <div class="v-page">
      <header class="v-page-head">
        <div><h2>Draft for {{ date() | dayName }}</h2><p class="sub">Review each item, then approve. Estimates stay marked as estimates.</p></div>
        <a class="v-btn" [routerLink]="['/days', date()]">Open the day</a>
      </header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }

      @if (summary(); as s) {
        <div class="grid">
          <form (ngSubmit)="approve()" class="items">
            <table class="v-table">
              <thead><tr><th>Meal</th><th>Item</th><th class="num">Amount</th><th class="num">kcal</th><th>Confidence</th><th>Reasoning</th><th>Keep</th></tr></thead>
              <tbody>
                @for (r of rows(); track r.item.id) {
                  <tr [class.removed]="r.remove">
                    <td>{{ mealName(r.item.meal_id) }}</td>
                    <td>
                      @if (r.item.alternatives?.length) {
                        <select [name]="'c' + r.item.id" [(ngModel)]="r.consumableId">
                          <option [ngValue]="r.item.consumable_id">{{ r.item.consumable_name }}</option>
                          @for (a of r.item.alternatives; track a.consumable_id) {
                            @if (a.consumable_id !== r.item.consumable_id) { <option [ngValue]="a.consumable_id">{{ a.name }} ({{ (a.score * 100).toFixed(0) }} %)</option> }
                          }
                        </select>
                      } @else { {{ r.item.consumable_name }} }
                      @if (r.item.estimated || r.item.amount_estimated) { <span title="estimated">⚠️</span> }
                    </td>
                    <td class="num"><input [name]="'a' + r.item.id" type="number" step="any" min="0" [(ngModel)]="r.amount" class="amount" /> {{ r.item.unit_code ?? r.item.base_unit }}</td>
                    <td class="num">{{ r.item.kcal | macro: 'kcal' }}</td>
                    <td>@if (r.item.confidence != null) { <span class="conf" [class.low]="r.item.confidence < 0.7">{{ (r.item.confidence * 100).toFixed(0) }} %</span> }</td>
                    <td class="v-small v-muted">{{ r.item.rationale }}</td>
                    <td><input type="checkbox" [name]="'k' + r.item.id" [ngModel]="!r.remove" (ngModelChange)="r.remove = !$event" /></td>
                  </tr>
                }
              </tbody>
            </table>
            <div class="v-actions foot">
              <label class="v-field check"><input name="close" type="checkbox" [(ngModel)]="close" /> <span>Close the day after approving</span></label>
              <button type="submit" class="v-btn primary" [disabled]="busy()">Approve</button>
              <button type="button" class="v-btn danger" (click)="discard()" [disabled]="busy()">Discard draft</button>
            </div>
          </form>
          <aside class="summary v-panel">
            <h3>Agent summary</h3>
            <div class="v-md" [innerHTML]="s.markdown | markdown"></div>
          </aside>
        </div>
      }
    </div>
  `,
  styles: `
    .grid { display: grid; grid-template-columns: minmax(0, 3fr) minmax(16rem, 2fr); gap: 1.5rem; align-items: start; }
    .amount { width: 5.5rem; padding: 0.25rem 0.4rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); text-align: right; }
    .removed td { opacity: 0.45; text-decoration: line-through; }
    .conf.low { color: var(--v-warn); }
    .foot { margin-top: 1rem; }
    .check { display: flex; align-items: center; gap: 0.4rem; }
    @media (max-width: 64rem) { .grid { grid-template-columns: 1fr; } }
  `,
})
export class DraftApproval {
  private readonly api = inject(ApiClient);
  private readonly router = inject(Router);
  readonly date = input.required<string>();
  readonly summary = signal<DraftSummary | null>(null);
  readonly rows = signal<Row[]>([]);
  readonly error = signal<string | null>(null);
  readonly busy = signal(false);
  close = true;

  constructor() {
    effect(() => {
      this.api.draftSummary(this.date()).subscribe({
        next: (s) => {
          this.summary.set(s);
          this.rows.set(
            s.day.meals.flatMap((m) => m.line_items.filter((i) => i.is_draft)).map((item) => ({
              item,
              amount: item.amount ?? item.base_amount,
              consumableId: item.consumable_id,
              remove: false,
            })),
          );
        },
        error: (e: unknown) => this.error.set(describeError(e)),
      });
    });
  }

  mealName(id: number): string {
    return this.summary()?.day.meals.find((m) => m.id === id)?.name ?? '';
  }

  /** Only what changed becomes a correction; untouched items are approved as they are. */
  buildRequest(): ApproveRequest {
    const corrections: DraftCorrection[] = [];
    for (const r of this.rows()) {
      if (r.remove) {
        corrections.push({ line_item_id: r.item.id, delete: true });
        continue;
      }
      const c: DraftCorrection = { line_item_id: r.item.id };
      if (r.amount !== (r.item.amount ?? r.item.base_amount)) c.amount = r.amount;
      if (r.consumableId !== r.item.consumable_id) c.consumable_id = r.consumableId;
      if (c.amount !== undefined || c.consumable_id !== undefined) corrections.push(c);
    }
    return { corrections, close: this.close };
  }

  approve(): void {
    this.busy.set(true);
    this.api.approveDraft(this.date(), this.buildRequest()).subscribe({
      next: () => void this.router.navigate(['/days', this.date()]),
      error: (e: unknown) => {
        this.error.set(describeError(e));
        this.busy.set(false);
      },
    });
  }

  discard(): void {
    if (!window.confirm('Discard all draft items of this day?')) return;
    this.busy.set(true);
    this.api.discardDraft(this.date()).subscribe({
      next: () => void this.router.navigate(['/drafts']),
      error: (e: unknown) => {
        this.error.set(describeError(e));
        this.busy.set(false);
      },
    });
  }
}
