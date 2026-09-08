import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { NgxEchartsDirective } from 'ngx-echarts';
import type { EChartsOption } from 'echarts';
import {
  BandDistributionBlock,
  BurndownBlock,
  DayListBlock,
  ErrorBlock,
  ForecastBlock,
  KpiTileBlock,
  MacroKey,
  Quality,
  ReportBlock,
  TdeeWindowsBlock,
  TextFindingBlock,
  TrendBlock,
  WeeklyChartBlock,
} from '../../../api';
import { formatKg, formatMacro, formatSigned, toneOf } from '../../../shared/format';
import { MarkdownPipe } from '../../../shared/markdown.pipe';
import { StatusTag } from '../../../shared/status-tag';
import { CHART_PALETTE } from './palette';

/**
 * Renders one block of a ReportResult (shape: src/victus/reports/results.py via render/json.py).
 * One template branch per `meta.type`; a failed block shows its message, an unknown type a
 * placeholder, so one bad block never breaks the page (T-WEB-004).
 */
@Component({
  selector: 'v-report-block',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgxEchartsDirective, MarkdownPipe, StatusTag],
  template: `
    @if (block().error) {
      <div class="v-panel failed"><h3>{{ block().meta.title }}</h3><p class="v-small">Could not compute this block: {{ failed().message }}</p></div>
    } @else {
      @switch (block().meta.type) {
        @case ('kpi_tile') {
          <div class="tile" [class]="'tile ' + toneOf(kpi().zone ?? kpi().quality)">
            <span class="t">{{ kpi().meta.title }}</span>
            <span class="v">{{ kpiValue() }} <span class="u">{{ kpi().unit }}</span></span>
            @if (kpi().delta != null) { <span class="d">{{ formatSigned(kpi().delta, kpi().decimals) }} vs. previous period</span> }
            @if (kpi().note) { <span class="d">{{ kpi().note }}</span> }
          </div>
        }
        @case ('band_distribution') {
          <div class="v-panel">
            <h3>{{ block().meta.title }}</h3>
            <table class="v-table">
              <thead><tr><th>Nutrient</th><th>Distribution</th><th class="num">below min</th><th class="num">below opt.</th><th class="num">optimal</th><th class="num">above opt.</th><th class="num">above max</th><th class="num">Ø</th><th class="num">days</th></tr></thead>
              <tbody>
                @for (r of dist().rows; track r.macro) {
                  <tr>
                    <td>{{ r.macro }}@if (r.band) { <span class="v-small v-muted"> {{ r.band.min }} / {{ r.band.opt_min }}–{{ r.band.opt_max }} / {{ r.band.max }}</span> }</td>
                    <td class="bar"><div class="stack">
                      <span style="background: #eb6834" [style.flex]="r.stat.below_min"></span><span style="background: #eda100" [style.flex]="r.stat.below_optimum"></span>
                      <span style="background: #1baf7a" [style.flex]="r.stat.optimal"></span><span style="background: #eda100" [style.flex]="r.stat.above_optimum"></span><span style="background: #eb6834" [style.flex]="r.stat.above_max"></span>
                    </div></td>
                    <td class="num">{{ r.stat.below_min }}</td><td class="num">{{ r.stat.below_optimum }}</td><td class="num">{{ r.stat.optimal }}</td><td class="num">{{ r.stat.above_optimum }}</td><td class="num">{{ r.stat.above_max }}</td>
                    <td class="num">{{ formatMacro(r.stat.mean, asMacro(r.macro)) }}</td><td class="num">{{ r.days_rated }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
        @case ('tdee_windows') {
          <div class="v-panel">
            <h3>{{ block().meta.title }} @if (tdee().reference_tdee != null) { <span class="v-small v-muted">reference {{ formatMacro(tdee().reference_tdee, 'kcal') }} kcal ({{ tdee().reference_basis }})</span> }</h3>
            <table class="v-table">
              <thead><tr><th>Window</th><th class="num">Ø kcal</th><th class="num">Δ weight</th><th class="num">TDEE</th><th class="num">Coverage</th><th class="num">in / above corridor</th>@if (tdee().show_quality) { <th>Grade</th> }</tr></thead>
              <tbody>
                @for (r of tdee().rows; track r.window_days) {
                  <tr>
                    <td>{{ r.window_days }} days</td><td class="num">{{ formatMacro(r.mean_kcal, 'kcal') }}</td>
                    <td class="num">{{ formatSigned(r.delta_ma_kg, 2, 'kg') }}</td>
                    <td class="num">{{ formatMacro(r.tdee, 'kcal') }}@if (r.tdee == null && r.rejected_tdee != null) { <span class="v-small v-muted" title="rejected as implausible">({{ formatMacro(r.rejected_tdee, 'kcal') }})</span> }</td>
                    <td class="num">{{ r.coverage_pct }} %</td><td class="num">{{ r.in_corridor }} / {{ r.above_corridor }}</td>
                    @if (tdee().show_quality) { <td><span class="v-tag" [class]="'v-tag ' + toneOf(r.quality)">{{ gradeLabel(r.quality) }}</span>@if (r.days_without_macros) { <span class="v-small v-muted"> {{ r.days_without_macros }} days without macros</span> }</td> }
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
        @case ('trend') {
          <div class="v-panel">
            <h3>{{ block().meta.title }}</h3>
            <table class="v-table">
              <thead><tr><th>Window</th><th class="num">kg / day</th><th class="num">kg / week</th><th class="num">actual change</th><th class="num">weigh-ins</th></tr></thead>
              <tbody>@for (r of trend().rows; track r.window) {
                <tr><td>{{ r.window }} days</td><td class="num">{{ formatSigned(r.slope_per_day, 3) }}</td><td class="num">{{ formatSigned(r.kg_per_week, 2) }}</td><td class="num">{{ formatSigned(r.actual_delta, 1, 'kg') }}</td><td class="num">{{ r.measured_days }}</td></tr>
              }</tbody>
            </table>
          </div>
        }
        @case ('forecast') {
          <div class="v-panel">
            <h3>{{ block().meta.title }} <span class="v-small v-muted">goal {{ formatKg(forecast().goal_kg) }} kg by {{ forecast().goal_date }}@if (forecast().current_kg != null) { · now {{ formatKg(forecast().current_kg) }} kg }</span></h3>
            <table class="v-table">
              <thead><tr><th>Based on</th><th class="num">kg / week</th><th class="num">in 1 month</th><th class="num">3 months</th><th class="num">6 months</th><th class="num">at goal date</th>@if (forecast().with_eta) { <th>goal reached</th> }</tr></thead>
              <tbody>@for (r of forecast().rows; track r.window) {
                <tr><td>{{ r.window }}-day trend</td><td class="num">{{ formatSigned(r.kg_per_week, 2) }}</td><td class="num">{{ formatKg(r.m1) }}</td><td class="num">{{ formatKg(r.m3) }}</td><td class="num">{{ formatKg(r.m6) }}</td><td class="num">{{ formatKg(r.at_goal_date) }}</td>@if (forecast().with_eta) { <td>{{ r.eta ?? 'not on this trend' }}</td> }</tr>
              }</tbody>
            </table>
          </div>
        }
        @case ('burndown') {
          <div class="v-panel">
            <h3>{{ block().meta.title }} <span class="v-small v-muted">{{ formatSigned(burndown().result.gap, 1, 'kg') }} vs. plan · actual {{ formatSigned(burndown().result.actual_rate_per_week, 2, 'kg/week') }} · required {{ formatSigned(burndown().result.required_rate_per_week, 2, 'kg/week') }}</span></h3>
            <div echarts [options]="burndownChart()" class="echart" aria-label="Planned versus actual weight"></div>
            @if (burndown().result.stages.length) {
              <p class="v-small v-muted">Below the goal line means ahead of plan. Each dotted line is one of your stages.</p>
              <table class="v-table stages">
                <thead><tr><th>Stage</th><th>Date</th><th class="num">gap</th><th class="num">required kg / week</th><th class="num">eat kcal / day</th><th>feasible</th></tr></thead>
                <tbody>@for (st of burndown().result.stages; track st.name) {
                  <tr><td>{{ st.name }}</td><td>{{ st.date }}</td><td class="num">{{ formatSigned(st.gap, 1, 'kg') }}</td><td class="num">{{ formatSigned(st.required_kg_per_week, 2) }}</td><td class="num">{{ st.eat_kcal_per_day == null ? '–' : formatMacro(st.eat_kcal_per_day, 'kcal') }}</td><td>{{ st.feasible ? 'yes' : 'no' }}</td></tr>
                }</tbody>
              </table>
            }
          </div>
        }
        @case ('weekly_chart') {
          <div class="v-panel">
            <h3>{{ block().meta.title }}</h3>
            <div echarts [options]="weeklyChart()" class="echart" aria-label="Weekly intake and expenditure"></div>
          </div>
        }
        @case ('day_list') {
          <div class="v-panel">
            <h3>{{ block().meta.title }}</h3>
            <div class="v-scroll-x"><table class="v-table">
              <thead><tr><th>Day</th>@for (c of dayList().columns; track c) { <th class="num">{{ c }}</th> }</tr></thead>
              <tbody>@for (r of dayList().rows; track r.date) {
                <tr [class.not-countable]="!r.countable"><td>{{ r.date }}</td>@for (c of dayList().columns; track c) {
                  <td class="num">
                    @if (c === 'status') { @if (r.status) { <v-status-tag [status]="r.status" /> } }
                    @else if (c === 'weight') { {{ formatKg(r.weight) }} }
                    @else if (c === 'training_type') { {{ r.training_type ?? '' }} }
                    @else if (c === 'reliable') { {{ r.reliable === null ? '?' : r.reliable ? 'yes' : 'no' }} }
                    @else { {{ formatMacro(r.macros[asMacro(c)], asMacro(c)) }} }
                  </td>
                }</tr>
              }</tbody>
            </table></div>
          </div>
        }
        @case ('text_finding') {
          <div class="v-panel finding">
            <h3>{{ block().meta.title }}</h3>
            @if (finding().markdown) { <div class="v-md" [innerHTML]="finding().markdown | markdown"></div> } @else { <p class="v-muted">Nothing written for this period.</p> }
          </div>
        }
        @default {
          <div class="v-panel v-muted">Block type “{{ block().meta.type }}” is not supported by this version of the app.</div>
        }
      }
    }
  `,
  styles: `
    :host { display: block; min-width: 0; }
    .tile { display: grid; gap: 0.15rem; padding: 0.9rem 1.1rem; border: 1px solid var(--v-line); border-left-width: 4px; border-radius: var(--v-radius-l); background: var(--v-surface); }
    .tile.ok { border-left-color: var(--v-ok); } .tile.warn { border-left-color: var(--v-warn); } .tile.bad { border-left-color: var(--v-bad); } .tile.muted { border-left-color: var(--v-line-strong); }
    .t { font-size: var(--v-fs-s); color: var(--v-ink-2); } .v { font-size: var(--v-fs-xl); font-weight: 560; } .u { font-size: var(--v-fs-s); font-weight: 400; color: var(--v-ink-3); } .d { font-size: var(--v-fs-xs); color: var(--v-ink-3); }
    .bar { min-width: 10rem; } .stack { display: flex; height: 10px; border-radius: 5px; overflow: hidden; background: var(--v-surface-2); } .stack span { display: block; }
    .echart { height: 18rem; width: 100%; }
    .stages { margin-top: 0.75rem; }
    .failed { border-left: 3px solid var(--v-bad); }
    .not-countable td { color: var(--v-ink-3); }
    h3 { margin-bottom: 0.5rem; font-size: var(--v-fs-m); }
  `,
})
export class ReportBlockView {
  readonly block = input.required<ReportBlock>();
  readonly formatMacro = formatMacro;
  readonly formatKg = formatKg;
  readonly formatSigned = formatSigned;
  readonly toneOf = toneOf;

  failed = () => this.block() as ErrorBlock;
  kpi = () => this.block() as KpiTileBlock;
  dist = () => this.block() as BandDistributionBlock;
  tdee = () => this.block() as TdeeWindowsBlock;
  trend = () => this.block() as TrendBlock;
  forecast = () => this.block() as ForecastBlock;
  burndown = () => this.block() as BurndownBlock;
  weekly = () => this.block() as WeeklyChartBlock;
  dayList = () => this.block() as DayListBlock;
  finding = () => this.block() as TextFindingBlock;

  asMacro(c: string): MacroKey {
    return c as MacroKey;
  }
  gradeLabel(q: Quality | null): string {
    return q === 'green' ? 'reliable' : q === 'yellow' ? 'indicative' : q === 'red' ? 'too little data' : 'no grade';
  }
  kpiValue(): string {
    const k = this.kpi();
    if (k.value == null) return '–';
    if (k.unit === 'kcal') return formatMacro(k.value, 'kcal');
    return formatKg(k.value, k.decimals);
  }

  /** Remaining kilograms over time: the goal line, one line per stage, and the actual curve. */
  burndownChart(): EChartsOption {
    const bd = this.burndown();
    const b = bd.result;
    const today = b.actual.length ? b.actual[b.actual.length - 1][0] : null;
    const stageSeries = (b.stages ?? [])
      .filter((st) => st.path?.length)
      .map((st, i) => ({
        name: st.name,
        type: 'line' as const,
        showSymbol: false,
        data: st.path as [string, number][],
        lineStyle: { type: 'dotted' as const, width: 1.5, color: CHART_PALETTE[(i + 4) % CHART_PALETTE.length] },
        itemStyle: { color: CHART_PALETTE[(i + 4) % CHART_PALETTE.length] },
      }));
    return {
      animation: false,
      grid: { left: 56, right: 20, top: 8, bottom: 56 },
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v: unknown) => (typeof v === 'number' ? `${v.toFixed(1)} kg` : '–'),
      },
      legend: { bottom: 0, type: 'scroll', icon: 'roundRect' },
      xAxis: {
        type: 'time',
        axisLabel: { hideOverlap: true, formatter: { day: '{d}.{MM}.', month: '{MMM}', year: '{yyyy}' } },
        splitLine: { show: true, lineStyle: { opacity: 0.25 } },
      },
      yAxis: {
        type: 'value',
        min: 0,
        name: 'kg above goal',
        nameLocation: 'end',
        nameGap: 12,
        axisLabel: { formatter: '{value}' },
        splitLine: { lineStyle: { opacity: 0.35 } },
      },
      series: [
        {
          name: `Goal ${bd.goal_date}`,
          type: 'line',
          showSymbol: false,
          data: b.target_path as [string, number][],
          lineStyle: { type: 'dashed', width: 2, color: CHART_PALETTE[3] },
          itemStyle: { color: CHART_PALETTE[3] },
        },
        ...stageSeries,
        {
          name: 'Actual (7-day avg.)',
          type: 'line',
          showSymbol: false,
          data: b.actual as [string, number][],
          lineStyle: { color: CHART_PALETTE[0], width: 3 },
          itemStyle: { color: CHART_PALETTE[0] },
          areaStyle: { opacity: 0.12, color: CHART_PALETTE[0] },
          markLine: today
            ? {
                symbol: 'none',
                silent: true,
                label: { formatter: 'today', position: 'insideEndTop', fontSize: 10 },
                lineStyle: { color: CHART_PALETTE[2], type: 'solid', width: 1 },
                data: [{ xAxis: today }],
              }
            : undefined,
        },
      ],
    };
  }

  weeklyChart(): EChartsOption {
    const rows = this.weekly().rows;
    return {
      animation: false,
      grid: { left: 56, right: 56, top: 32, bottom: 32 },
      tooltip: { trigger: 'axis' },
      legend: { top: 0 },
      xAxis: { type: 'category', data: rows.map((r) => r.week_start) },
      yAxis: [
        { type: 'value', name: 'kcal', axisLabel: { formatter: '{value}' } },
        { type: 'value', name: 'kg', scale: true },
      ],
      series: [
        { name: 'Ø intake', type: 'bar', data: rows.map((r) => r.mean_kcal), itemStyle: { color: CHART_PALETTE[0] } },
        { name: 'Weekly TDEE', type: 'line', data: rows.map((r) => r.tdee), itemStyle: { color: CHART_PALETTE[1] }, lineStyle: { color: CHART_PALETTE[1] } },
        { name: 'Ø weight', type: 'line', yAxisIndex: 1, data: rows.map((r) => r.mean_kg), itemStyle: { color: CHART_PALETTE[2] }, lineStyle: { color: CHART_PALETTE[2] } },
      ],
    };
  }
}
