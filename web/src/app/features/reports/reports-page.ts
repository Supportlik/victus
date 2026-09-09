import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiClient, ReportBlock, ReportDefinition, ReportResult } from '../../api';
import { FormatService } from '../../core/format.service';
import { I18nService } from '../../core/i18n.service';
import { describeError } from '../../core/problem';
import { isoDate, shiftDate } from '../../shared/format';
import { ReportBlockView } from './report-blocks/report-block';
import { SnapshotList } from './snapshot-list';

/** Report dashboard: pick a definition and a period, render the blocks. */
@Component({
  selector: 'v-reports-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, ReportBlockView, SnapshotList],
  template: `
    <div class="v-page">
      <header class="v-page-head">
        <div><h2>{{ i18n.t(current()?.title ?? 'Reports') }}</h2>@if (current()?.description) { <p class="sub">{{ i18n.t(current()!.description!) }}</p> }</div>
        <div class="v-actions controls">
          <label class="v-field"><span>{{ i18n.t('Report') }}</span>
            <select [ngModel]="name()" (ngModelChange)="name.set($event); render()">
              @for (r of definitions(); track r.name) { <option [value]="r.name">{{ i18n.t(r.title) }}@if (!r.builtin) { {{ i18n.t('(custom)') }} }</option> }
            </select>
          </label>
          <label class="v-field"><span>{{ i18n.t('As of') }}</span><input type="date" [ngModel]="asOf()" (ngModelChange)="setAsOf($event)" name="asof" /></label>
          <label class="v-field"><span>{{ i18n.t('Period') }}</span>
            <select [ngModel]="period()" (ngModelChange)="setPeriod($event)">
              @for (p of current()?.period?.options ?? ['7d', '14d', '30d', '90d', 'custom']; track p) { <option [value]="p">{{ p === 'custom' ? i18n.t('Custom range') : i18n.t('last {n} days', { n: p.replace('d', '') }) }}</option> }
            </select>
          </label>
        </div>
      </header>
      <!-- Own row, so choosing "custom range" never reflows the controls above. -->
      <div class="range" [class.shown]="period() === 'custom'">
        <label class="v-field"><span>{{ i18n.t('From') }}</span><input type="date" [ngModel]="from()" (ngModelChange)="from.set($event); render()" /></label>
        <label class="v-field"><span>{{ i18n.t('To') }}</span><input type="date" [ngModel]="to()" (ngModelChange)="to.set($event); render()" /></label>
      </div>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
      @if (result(); as r) {
        <p class="v-small v-muted">{{ format.day(r.period.start) }} {{ i18n.t('to') }} {{ format.day(r.period.end) }} ({{ i18n.t('{n} days', { n: r.period.days }) }}) · {{ i18n.t('generated') }} {{ format.moment(r.generated_at) }}@if (errorCount(); as n) { · <span class="v-tag bad">{{ i18n.t('{n} block(s) failed', { n }) }}</span> }</p>
        @if (tiles().length) {
          <section class="tiles">@for (b of tiles(); track $index) { <v-report-block [block]="b" /> }</section>
        }
        <section class="blocks">@for (b of others(); track $index) { <v-report-block [block]="b" /> }</section>
        <v-snapshot-list [report]="name()" [from]="from()" [to]="to()" [asOf]="asOf()" />
      } @else if (!error()) {
        <p class="v-muted">{{ i18n.t('Rendering…') }}</p>
      }
    </div>
  `,
  styles: `
    .controls { align-items: end; }
    .controls .v-field select { min-width: 11rem; }
    .range { display: none; gap: 0.75rem; margin-bottom: 0.75rem; }
    .range.shown { display: flex; flex-wrap: wrap; }
    .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: 0.75rem; margin-bottom: 1rem; align-items: stretch; }
    .tiles v-report-block { display: block; height: 100%; }
    .blocks { display: grid; grid-template-columns: minmax(0, 1fr); gap: 1rem; }
  `,
})
export class ReportsPage {
  private readonly api = inject(ApiClient);
  readonly i18n = inject(I18nService);
  readonly format = inject(FormatService);
  readonly definitions = signal<ReportDefinition[]>([]);
  readonly name = signal('checkup');
  readonly period = signal('14d');
  readonly asOf = signal(isoDate(new Date()));
  readonly to = signal(isoDate(new Date()));
  readonly from = signal(shiftDate(isoDate(new Date()), -13));
  readonly result = signal<ReportResult | null>(null);
  readonly error = signal<string | null>(null);
  readonly current = computed(() => this.definitions().find((d) => d.name === this.name()) ?? null);
  readonly tiles = computed<ReportBlock[]>(() => this.result()?.blocks.filter((b) => b.meta.type === 'kpi_tile' && !b.error) ?? []);
  readonly errorCount = computed(() => this.result()?.blocks.filter((b) => b.error).length ?? 0);
  readonly others = computed<ReportBlock[]>(() => this.result()?.blocks.filter((b) => b.meta.type !== 'kpi_tile' || b.error) ?? []);

  constructor() {
    this.api.reports().subscribe({
      next: (d) => {
        this.definitions.set(d);
        const first = d.find((x) => x.name === 'checkup') ?? d[0];
        if (first) {
          this.name.set(first.name);
          this.setPeriod(first.period?.default ?? '14d');
        }
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  /** Every window ends on the chosen day, so the panels and the tables agree. */
  setAsOf(day: string): void {
    this.asOf.set(day || isoDate(new Date()));
    this.setPeriod(this.period());
  }

  setPeriod(p: string): void {
    this.period.set(p);
    const m = /^(\d+)d$/.exec(p);
    if (m) {
      this.to.set(this.asOf());
      this.from.set(shiftDate(this.to(), -(Number(m[1]) - 1)));
    }
    this.render();
  }

  render(): void {
    this.error.set(null);
    this.result.set(null);
    this.api.renderReport(this.name(), this.from(), this.to(), this.asOf()).subscribe({
      next: (r) => this.result.set(r),
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }
}
