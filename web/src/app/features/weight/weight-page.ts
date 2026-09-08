import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgxEchartsDirective } from 'ngx-echarts';
import type { EChartsOption } from 'echarts';
import { ApiClient, WeightEntry } from '../../api';
import { describeError } from '../../core/problem';
import { isoDate, KgPipe, shiftDate } from '../../shared/format';
import { CHART_PALETTE } from '../reports/report-blocks/palette';

/** Weigh-ins from the scale sync plus manual entries; the moving average is computed here for display. */
@Component({
  selector: 'v-weight-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, NgxEchartsDirective, KgPipe],
  template: `
    <div class="v-page">
      <header class="v-page-head">
        <div><h2>Weight</h2><p class="sub">Your scale syncs automatically. Add an entry by hand only when it was not around.</p></div>
        <label class="v-field"><span>Range</span>
          <select [ngModel]="days()" (ngModelChange)="days.set(+$event); load()"><option [value]="30">30 days</option><option [value]="90">90 days</option><option [value]="365">1 year</option><option [value]="3650">all</option></select>
        </label>
      </header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
      <div class="v-panel chart">
        @if (entries().length) {
          <div echarts [options]="chart()" class="echart" aria-label="Weight over time"></div>
        } @else { <div class="v-empty">No weigh-ins in this range.</div> }
      </div>
      <div class="grid">
        <form class="v-panel add" (ngSubmit)="add()">
          <h3>Add a weigh-in</h3>
          <div class="v-form-row">
            <label class="v-field"><span>Date and time</span><input name="at" type="datetime-local" [(ngModel)]="measuredAt" required /></label>
            <label class="v-field"><span>kg</span><input name="kg" type="number" step="0.1" min="30" max="300" [(ngModel)]="kg" required /></label>
          </div>
          <button type="submit" class="v-btn primary" [disabled]="!kg">Add weigh-in</button>
        </form>
        <div class="v-scroll-x">
          <table class="v-table">
            <thead><tr><th>When</th><th class="num">kg</th><th>Source</th><th></th></tr></thead>
            <tbody>
              @for (w of recent(); track w.id) {
                <tr>
                  <td>{{ w.measured_at.replace('T', ' ').slice(0, 16) }}</td><td class="num">{{ w.kg | kg }}</td>
                  <td>@if (w.source === 'manual') { <span class="v-tag">manual</span> } @else { <span class="v-small v-muted">{{ w.source === 'scale_sync' ? 'scale' : w.source }}</span> }</td>
                  <td class="num">@if (w.source === 'manual') { <button type="button" class="v-btn quiet small danger" (click)="remove(w)">remove</button> }</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `,
  styles: `
    .chart { margin-bottom: 1.25rem; } .echart { height: 20rem; width: 100%; }
    .grid { display: grid; grid-template-columns: minmax(16rem, 1fr) minmax(0, 2fr); gap: 1.5rem; align-items: start; }
    .add { display: grid; gap: 0.75rem; }
    @media (max-width: 52rem) { .grid { grid-template-columns: 1fr; } }
  `,
})
export class WeightPage {
  private readonly api = inject(ApiClient);
  readonly days = signal(90);
  readonly entries = signal<WeightEntry[]>([]);
  readonly error = signal<string | null>(null);
  measuredAt = new Date().toISOString().slice(0, 16);
  kg: number | null = null;

  readonly recent = computed(() => [...this.entries()].sort((a, b) => (a.measured_at < b.measured_at ? 1 : -1)).slice(0, 60));

  readonly chart = computed<EChartsOption>(() => {
    const byDay = new Map<string, number[]>();
    for (const e of this.entries()) {
      const d = e.measured_at.slice(0, 10);
      byDay.set(d, [...(byDay.get(d) ?? []), e.kg]);
    }
    const daily = [...byDay.entries()].map(([d, v]) => [d, v.reduce((a, b) => a + b, 0) / v.length] as [string, number]).sort((a, b) => (a[0] < b[0] ? -1 : 1));
    const ma: [string, number][] = daily.map(([d], i) => {
      const from = new Date(`${d}T00:00:00Z`).getTime() - 6 * 86400000;
      const win = daily.slice(0, i + 1).filter(([x]) => new Date(`${x}T00:00:00Z`).getTime() >= from);
      return [d, win.reduce((a, [, v]) => a + v, 0) / win.length];
    });
    return {
      animation: false,
      grid: { left: 48, right: 16, top: 24, bottom: 32 },
      tooltip: { trigger: 'axis', valueFormatter: (v) => `${Number(v).toFixed(1)} kg` },
      xAxis: { type: 'time' },
      yAxis: { type: 'value', scale: true, axisLabel: { formatter: '{value} kg' } },
      series: [
        { name: 'Weigh-in', type: 'scatter', symbolSize: 5, data: daily, itemStyle: { color: CHART_PALETTE[0], opacity: 0.6 } },
        { name: '7-day average', type: 'line', showSymbol: false, smooth: false, data: ma, lineStyle: { width: 2, color: CHART_PALETTE[1] }, itemStyle: { color: CHART_PALETTE[1] } },
      ],
    };
  });

  constructor() {
    this.load();
  }
  load(): void {
    const to = isoDate(new Date());
    this.api.weight(shiftDate(to, -this.days()), to).subscribe({ next: (w) => this.entries.set(w), error: (e: unknown) => this.error.set(describeError(e)) });
  }
  add(): void {
    if (!this.kg) return;
    this.api.addWeight({ measured_at: new Date(this.measuredAt).toISOString(), kg: this.kg }).subscribe({
      next: () => {
        this.kg = null;
        this.load();
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }
  remove(w: WeightEntry): void {
    this.api.deleteWeight(w.id).subscribe({ next: () => this.load(), error: (e: unknown) => this.error.set(describeError(e)) });
  }
}
