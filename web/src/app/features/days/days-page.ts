import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiClient, DaySummary } from '../../api';
import { I18nService } from '../../core/i18n.service';
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
          <h2>{{ i18n.t('Days') }}</h2>
          <p class="sub">{{ i18n.t('{n} days between {from} and {to}', { n: days().length, from: from(), to: to() }) }}</p>
        </div>
        <div class="v-actions">
          <label class="v-field"><span>{{ i18n.t('From') }}</span><input type="date" [ngModel]="from()" (ngModelChange)="from.set($event); load()" /></label>
          <label class="v-field"><span>{{ i18n.t('To') }}</span><input type="date" [ngModel]="to()" (ngModelChange)="to.set($event); load()" /></label>
          <label class="v-field"><span>{{ i18n.t('Status') }}</span>
            <select [ngModel]="status()" (ngModelChange)="status.set($event); load()">
              <option value="">{{ i18n.t('all') }}</option><option value="draft">{{ i18n.t('draft') }}</option><option value="open">{{ i18n.t('open') }}</option><option value="closed">{{ i18n.t('closed') }}</option>
            </select>
          </label>
        </div>
      </header>

      @if (error(); as e) { <div class="v-error">{{ e }}</div> }

      @if (days().length === 0 && !loading()) {
        <div class="v-empty">{{ i18n.t('No days in this range yet.') }} <a [routerLink]="['/days', today]">{{ i18n.t('Open today to start logging.') }}</a></div>
      } @else {
        <div class="v-scroll-x">
          <table class="v-table">
            <thead>
              <tr><th>{{ i18n.t('Day') }}</th><th>{{ i18n.t('Status') }}</th><th class="num">kcal</th><th class="num">{{ i18n.t('Protein') }}</th><th class="num">{{ i18n.t('Carbs') }}</th><th class="num">{{ i18n.t('Fat') }}</th><th class="num">{{ i18n.t('Fiber') }}</th><th class="num">{{ i18n.t('Salt') }}</th><th class="num">{{ i18n.t('Weight') }}</th><th>{{ i18n.t('Reliable') }}</th></tr>
            </thead>
            <tbody>
              @for (d of days(); track d.date) {
                <tr>
                  <td><a [routerLink]="['/days', d.date]">{{ d.date | dayName }}</a></td>
                  <td><v-status-tag [status]="d.status" />@if (d.has_drafts && d.status !== 'draft') { <span class="v-tag draft">{{ i18n.t('items') }}</span> }</td>
                  <td class="num">{{ d.macros.kcal | macro: 'kcal' }}</td>
                  <td class="num">{{ d.macros.protein | macro: 'protein' }}</td>
                  <td class="num">{{ d.macros.carbs | macro: 'carbs' }}</td>
                  <td class="num">{{ d.macros.fat | macro: 'fat' }}</td>
                  <td class="num">{{ d.macros.fiber | macro: 'fiber' }}</td>
                  <td class="num">{{ d.macros.salt | macro: 'salt' }}</td>
                  <td class="num">{{ d.weight_kg ?? '–' }}</td>
                  <td>@if (d.reliable === false) { <span class="v-tag warn">{{ i18n.t('estimated day') }}</span> } @else if (d.reliable === null) { <span class="v-tag bad">{{ i18n.t('flag missing') }}</span> } @else { {{ i18n.t('yes') }} }</td>
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
  readonly i18n = inject(I18nService);
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
