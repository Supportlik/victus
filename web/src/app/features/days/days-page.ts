import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiClient, DaySummary } from '../../api';
import { describeError } from '../../core/problem';
import { DayNamePipe, isoDate, MacroPipe, shiftDate } from '../../shared/format';
import { StatusTag } from '../../shared/status-tag';

/** Day list: the last weeks as a ledger, newest first. */
@Component({
  selector: 'v-days-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, FormsModule, StatusTag, MacroPipe, DayNamePipe],
  template: `
    <div class="v-page">
      <header class="v-page-head">
        <div>
          <h2>Days</h2>
          <p class="sub">{{ days().length }} days between {{ from() }} and {{ to() }}</p>
        </div>
        <div class="v-actions">
          <label class="v-field"><span>From</span><input type="date" [ngModel]="from()" (ngModelChange)="from.set($event); load()" /></label>
          <label class="v-field"><span>To</span><input type="date" [ngModel]="to()" (ngModelChange)="to.set($event); load()" /></label>
          <label class="v-field"><span>Status</span>
            <select [ngModel]="status()" (ngModelChange)="status.set($event); load()">
              <option value="">all</option><option value="draft">draft</option><option value="open">open</option><option value="closed">closed</option>
            </select>
          </label>
        </div>
      </header>

      @if (error(); as e) { <div class="v-error">{{ e }}</div> }

      @if (days().length === 0 && !loading()) {
        <div class="v-empty">No days in this range yet. Open <a [routerLink]="['/days', today]">today</a> to start logging.</div>
      } @else {
        <div class="v-scroll-x">
          <table class="v-table">
            <thead>
              <tr><th>Day</th><th>Status</th><th class="num">kcal</th><th class="num">Protein</th><th class="num">Carbs</th><th class="num">Fat</th><th class="num">Fiber</th><th class="num">Salt</th><th class="num">Weight</th><th>Reliable</th></tr>
            </thead>
            <tbody>
              @for (d of days(); track d.date) {
                <tr>
                  <td><a [routerLink]="['/days', d.date]">{{ d.date | dayName }}</a></td>
                  <td><v-status-tag [status]="d.status" />@if (d.has_drafts && d.status !== 'draft') { <span class="v-tag draft">items</span> }</td>
                  <td class="num">{{ d.macros.kcal | macro: 'kcal' }}</td>
                  <td class="num">{{ d.macros.protein | macro: 'protein' }}</td>
                  <td class="num">{{ d.macros.carbs | macro: 'carbs' }}</td>
                  <td class="num">{{ d.macros.fat | macro: 'fat' }}</td>
                  <td class="num">{{ d.macros.fiber | macro: 'fiber' }}</td>
                  <td class="num">{{ d.macros.salt | macro: 'salt' }}</td>
                  <td class="num">{{ d.weight_kg ?? '–' }}</td>
                  <td>@if (d.reliable === false) { <span class="v-tag warn">estimated day</span> } @else if (d.reliable === null) { <span class="v-tag bad">flag missing</span> } @else { yes }</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    </div>
  `,
})
export class DaysPage {
  private readonly api = inject(ApiClient);
  readonly today = isoDate(new Date());
  readonly from = signal(shiftDate(this.today, -27));
  readonly to = signal(this.today);
  readonly status = signal('');
  readonly days = signal<DaySummary[]>([]);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly count = computed(() => this.days().length);

  constructor() {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.days(this.from(), this.to(), this.status() || undefined).subscribe({
      next: (d) => {
        this.days.set([...d].sort((a, b) => (a.date < b.date ? 1 : -1)));
        this.loading.set(false);
      },
      error: (e: unknown) => {
        this.error.set(describeError(e));
        this.loading.set(false);
      },
    });
  }
}
