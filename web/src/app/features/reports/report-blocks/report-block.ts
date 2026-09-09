import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { NgxEchartsDirective } from 'ngx-echarts';
import type { EChartsOption } from 'echarts';
import {
  BandDistributionBlock,
  BodyCompositionBlock,
  EnergySplitBlock,
  RatedValue,
  ThresholdMark,
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
  TimelineBlock,
  TrendBlock,
  WeeklyChartBlock,
} from '../../../api';
import { FormatService } from '../../../core/format.service';
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
            <h3>{{ block().meta.title }} @if (tdee().reference_tdee != null) { <span class="v-small v-muted">reference {{ formatMacro(tdee().reference_tdee, 'kcal') }} kcal, {{ basisLabel(tdee().reference_basis) }}</span> }</h3>
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
        @case ('timeline') {
          <div class="v-panel">
            <h3>{{ block().meta.title }} <span class="v-small v-muted">weight, intake, rolling {{ timeline().tdee_window }}-day TDEE and macros on one axis</span></h3>
            <div echarts [options]="timelineChart()" class="echart tall" aria-label="Weight, intake, TDEE and macros over time"></div>
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
            @if (finding().markdown) { <div class="v-md" [innerHTML]="finding().markdown | markdown"></div> } @else {
              <p class="v-muted">No assessment yet. Freeze this report below to keep its numbers, then let Claude judge that moment. The text and the figures then belong together.</p>
            }
          </div>
        }
        @case ('body_composition') {
          <div class="v-panel body">
            <h3>{{ block().meta.title }}</h3>
            @if (body().weight_kg != null) {
              <p class="v-small v-muted">
                {{ format.number(body().weight_kg!, 1) }} kg@if (body().height_cm) { at {{ body().height_cm }} cm }
                @if (body().measured_at) { · measured {{ format.day(body().measured_at!) }} }
              </p>
            }
            @for (m of rated(); track m.label) {
              <div class="measure">
                <div class="head">
                  <span class="what">{{ m.label }}</span>
                  <span class="val">{{ format.number(m.rated.value, m.decimals) }}</span>
                  <span class="v-tag" [class]="'v-tag ' + toneTag(m.rated.tone)">{{ m.rated.band }}</span>
                  @if (m.rated.to_next != null) {
                    <span class="v-small v-muted">{{ format.number(absOf(m.rated.to_next), m.decimals) }} to the next class</span>
                  }
                </div>
                <div class="scale" [attr.aria-label]="m.label + ': ' + m.rated.band">
                  @for (seg of segments(m.rated); track seg.name) {
                    <span class="seg" [class]="'seg ' + seg.tone" [class.here]="seg.here" [style.flex]="seg.weight" [title]="seg.title"></span>
                  }
                  <span class="pin" [style.left.%]="position(m.rated)"></span>
                </div>
              </div>
            }
            @if (body().bmi_weight_bands.length && body().weight_kg != null) {
              <details class="marks">
                <summary class="v-small">What the classes mean in kilograms</summary>
                <table class="v-table">
                  <thead><tr><th>Class</th><th class="num">from</th><th class="num">to</th></tr></thead>
                  <tbody>
                    @for (m of body().bmi_weight_bands; track m.name) {
                      <tr [class.here]="inBand(m)">
                        <td>{{ m.name }}</td>
                        <td class="num">{{ m.lower ? format.number(m.lower, 1) + ' kg' : '–' }}</td>
                        <td class="num">{{ m.upper ? format.number(m.upper, 1) + ' kg' : '–' }}</td>
                      </tr>
                    }
                  </tbody>
                </table>
              </details>
            }
            @if (circumferences().length) {
              <table class="v-table circ">
                <thead><tr><th></th><th class="num">now</th><th class="num">change</th></tr></thead>
                <tbody>
                  @for (c of circumferences(); track c.key) {
                    <tr>
                      <td>{{ c.label }}</td>
                      <td class="num">{{ format.number(c.value, 1) }} cm</td>
                      <td class="num" [class.down]="(c.change ?? 0) < 0" [class.up]="(c.change ?? 0) > 0">
                        {{ c.change == null ? '–' : (c.change > 0 ? '+' : '−') + format.number(absOf(c.change), 1) + ' cm' }}
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            }
            @if (body().missing.length) {
              <p class="v-small v-muted">Not shown: {{ body().missing.join('; ') }}.</p>
            }
          </div>
        }
        @case ('energy_split') {
          <div class="v-panel energy">
            <h3>{{ block().meta.title }}</h3>
            @if (energy().tdee_kcal == null) {
              <p class="v-muted">Not available: {{ energy().missing.join('; ') || 'no data' }}.</p>
            } @else {
              <div class="rows">
                <div><span>Expenditure</span><b>{{ format.number(energy().tdee_kcal!) }} kcal</b><span class="v-small v-muted">{{ basisLabel(energy().basis) }}</span></div>
                @if (energy().basal_kcal != null) {
                  <div><span>At rest</span><b>{{ format.number(energy().basal_kcal!) }} kcal</b><span class="v-small v-muted">age {{ energy().age_years }}</span></div>
                  <div><span>From moving</span><b>{{ format.number(energy().activity_kcal!) }} kcal</b><span class="v-small v-muted">{{ format.number(energy().pal!, 2) }} × resting</span></div>
                }
              </div>
              @if (energy().basal_kcal != null) {
                <div class="split" [attr.aria-label]="'resting versus activity'">
                  <span class="rest" [style.flex]="energy().basal_kcal!">at rest</span>
                  <span class="move" [style.flex]="maxOf(energy().activity_kcal!, 1)">moving</span>
                </div>
              }
              @if (energy().caveat) { <p class="v-small warn-text">{{ energy().caveat }}</p> }
              @if (energy().missing.length) { <p class="v-small v-muted">Not shown: {{ energy().missing.join('; ') }}.</p> }
            }
          </div>
        }
        @default {
          <div class="v-panel v-muted">Block type “{{ block().meta.type }}” is not supported by this version of the app.</div>
        }
      }
    }
  `,
  styles: `
    .body, .energy { display: grid; gap: 0.6rem; }
    .measure { display: grid; gap: 0.3rem; }
    .measure .head { display: flex; gap: 0.5rem; align-items: baseline; flex-wrap: wrap; }
    .measure .what { min-width: 8rem; color: var(--v-ink-2); }
    .measure .val { font-size: var(--v-fs-l); font-weight: 600; font-variant-numeric: tabular-nums; }
    .scale { position: relative; display: flex; height: 0.7rem; border-radius: 999px; overflow: hidden; background: var(--v-surface-2); }
    .seg { display: block; opacity: 0.35; }
    .seg.here { opacity: 0.9; }
    .seg.ok { background: var(--v-ok); }
    .seg.watch { background: var(--v-warn); }
    .seg.warn { background: var(--v-warn); }
    .seg.bad { background: var(--v-bad); }
    .pin { position: absolute; top: -0.15rem; width: 2px; height: 1rem; background: var(--v-ink); transform: translateX(-1px); }
    .marks summary { cursor: pointer; color: var(--v-ink-2); }
    .marks tr.here { background: var(--v-primary-soft); font-weight: 500; }
    .circ .down { color: var(--v-ok); }
    .circ .up { color: var(--v-warn); }
    .energy .rows { display: grid; gap: 0.3rem; }
    .energy .rows > div { display: flex; gap: 0.5rem; align-items: baseline; }
    .energy .rows > div > span:first-child { min-width: 8rem; color: var(--v-ink-2); }
    .energy .rows b { font-variant-numeric: tabular-nums; }
    .split { display: flex; height: 1.4rem; border-radius: var(--v-radius); overflow: hidden; font-size: var(--v-fs-xs); }
    .split span { display: grid; place-items: center; color: var(--v-primary-ink); }
    .split .rest { background: var(--v-primary); }
    .split .move { background: var(--v-ok); }
    .warn-text { color: var(--v-warn); }

    :host { display: block; min-width: 0; }
    /* One row each for title, value and note, so tiles line up whether or not a note is present. */
    .tile { display: grid; grid-template-rows: auto 1fr auto; gap: 0.15rem; padding: 0.9rem 1.1rem; border: 1px solid var(--v-line); border-left-width: 4px; border-radius: var(--v-radius-l); background: var(--v-surface); height: 100%; min-height: 6.5rem; align-content: start; }
    .tile .v { align-self: center; }
    .tile .d { min-height: 1.1rem; }
    .tile.ok { border-left-color: var(--v-ok); } .tile.warn { border-left-color: var(--v-warn); } .tile.bad { border-left-color: var(--v-bad); } .tile.muted { border-left-color: var(--v-line-strong); }
    .t { font-size: var(--v-fs-s); color: var(--v-ink-2); } .v { font-size: var(--v-fs-xl); font-weight: 560; } .u { font-size: var(--v-fs-s); font-weight: 400; color: var(--v-ink-3); } .d { font-size: var(--v-fs-xs); color: var(--v-ink-3); }
    .bar { min-width: 10rem; } .stack { display: flex; height: 10px; border-radius: 5px; overflow: hidden; background: var(--v-surface-2); } .stack span { display: block; }
    .echart { height: 18rem; width: 100%; }
    .echart.tall { height: 30rem; }
    .stages { margin-top: 0.75rem; }
    .failed { border-left: 3px solid var(--v-bad); }
    .not-countable td { color: var(--v-ink-3); }
    h3 { margin-bottom: 0.5rem; font-size: var(--v-fs-m); }
  `,
})
export class ReportBlockView {
  /** Read from the template, so numbers and dates follow the tenant's locale (R69). */
  readonly format = inject(FormatService);
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
  /**
   * What the reader actually wants on a burndown: the weight behind the remaining
   * kilograms, how far it still is to the goal, the day-on-day change, and how the
   * actual line stands against each planned line.
   */
  burndownTooltip(params: unknown, bd: BurndownBlock): string {
    const rows = (Array.isArray(params) ? params : [params]) as {
      seriesName?: string;
      value?: [string | number, number];
      color?: string;
      dataIndex?: number;
    }[];
    if (!rows.length) return '';
    const goal = bd.goal_kg;
    const actual = bd.result.actual as [string, number][];
    const kg = (v: number) => `${v.toFixed(1)} kg`;
    const day = (v: string | number) => new Date(v).toLocaleDateString();
    const dot = (c?: string) => `<span style="display:inline-block;width:.55em;height:.55em;border-radius:50%;background:${c ?? 'currentColor'};margin-right:.4em"></span>`;

    const head = rows[0]?.value ? day(rows[0].value[0]) : '';
    const actualRow = rows.find((r) => r.seriesName?.startsWith('Actual'));
    const remainingNow = actualRow?.value?.[1];
    const lines: string[] = [];

    if (actualRow && remainingNow != null) {
      const i = actualRow.dataIndex ?? -1;
      const prev = i > 0 ? actual[i - 1]?.[1] : undefined;
      const delta = prev != null ? remainingNow - prev : undefined;
      const change = delta == null ? '' : ` · ${delta <= 0 ? '−' : '+'}${Math.abs(delta).toFixed(2)} kg vs. the day before`;
      lines.push(`${dot(actualRow.color)}<b>${kg(goal + remainingNow)}</b> · ${kg(remainingNow)} to go${change}`);
    }

    for (const r of rows) {
      if (r === actualRow || r.value == null) continue;
      const planned = r.value[1];
      const gap = remainingNow == null ? null : planned - remainingNow;
      const stand =
        gap == null ? '' : gap >= 0 ? ` · ${kg(Math.abs(gap))} ahead` : ` · ${kg(Math.abs(gap))} behind`;
      lines.push(`${dot(r.color)}${r.seriesName}: plan ${kg(goal + planned)}${stand}`);
    }

    const last = actual.length ? actual[actual.length - 1][1] : null;
    if (last != null && rows.some((r) => r.seriesName?.startsWith('Actual'))) {
      lines.push(`<span class="v-small">goal ${kg(goal)} by ${bd.goal_date}</span>`);
    }
    return `${head}<br>${lines.join('<br>')}`;
  }

  /** "rolling_14d" reads like a database column; say it in words. */
  basisLabel(basis: string): string {
    const rolling = /^rolling_(\d+)d$/.exec(basis);
    if (rolling) return `from the rolling ${rolling[1]}-day window`;
    const weekly = /^weekly_mean_(\d+)w$/.exec(basis);
    if (weekly) return `mean of the last ${weekly[1]} weekly values`;
    return basis === 'none' ? 'no basis yet' : basis;
  }

  timeline(): TimelineBlock {
    return this.block() as TimelineBlock;
  }

  /**
   * The three panels share one day, so the tooltip shows that day the same way from any of
   * them: weight on top, intake in the middle, TDEE below, macros last. Letting ECharts list
   * whatever series sit under the pointer put a different line first in every panel.
   */
  timelineTooltip(params: unknown): string {
    const rows = (Array.isArray(params) ? params : [params]) as { axisValue?: string }[];
    const day = rows.find((r) => r.axisValue)?.axisValue;
    const row = this.timeline().rows.find((r) => r.date === day);
    if (!row) return '';
    const dot = (c: string) =>
      `<span style="display:inline-block;width:.55em;height:.55em;border-radius:50%;background:${c};margin-right:.4em"></span>`;
    const num = (v: number, digits = 0) => this.format.number(v, digits);
    const line = (color: string, label: string, value: number | null | undefined, unit: string, digits = 0) =>
      value == null ? '' : `<div>${dot(color)}${label}: <b>${num(value, digits)}</b> ${unit}</div>`;

    const weight = row.weight_ma ?? row.weight;
    const grams = [
      ['Protein', row.protein],
      ['Carbs', row.carbs],
      ['Fat', row.fat],
      ['Fiber', row.fiber],
    ] as const;
    const macros = grams
      .filter(([, v]) => v != null)
      .map(([name, v]) => `${name} ${num(v as number)} g`)
      .join(' · ');

    return [
      `<div style="margin-bottom:.25em"><b>${this.format.day(day ?? '')}</b>${row.countable ? '' : ' · not counted'}</div>`,
      line(CHART_PALETTE[0], 'Weight', weight, 'kg', 1),
      line(CHART_PALETTE[1], 'Intake', row.kcal, 'kcal'),
      line(CHART_PALETTE[2], `TDEE (${this.timeline().tdee_window} d)`, row.tdee, 'kcal'),
      macros ? `<div style="margin-top:.25em;opacity:.8">${macros}</div>` : '',
    ]
      .filter(Boolean)
      .join('');
  }

  /**
   * Four panels, one time axis: weight against the goal, intake against the corridor and
   * the rolling TDEE, and the macro split. Hovering shows the same day in every panel.
   */
  timelineChart(): EChartsOption {
    const t = this.timeline();
    const days = t.rows.map((r) => r.date);
    const pick = (f: (r: (typeof t.rows)[number]) => number | null | undefined) =>
      t.rows.map((r) => {
        const v = f(r);
        return v === null || v === undefined ? null : v;
      });
    const line = (name: string, data: (number | null)[], color: string, extra: Record<string, unknown> = {}) => ({
      name,
      type: 'line' as const,
      showSymbol: false,
      connectNulls: true,
      data,
      xAxisIndex: extra['xAxisIndex'] ?? 0,
      yAxisIndex: extra['yAxisIndex'] ?? 0,
      lineStyle: { color, width: 2 },
      itemStyle: { color },
      ...extra,
    });
    const grids = [
      { left: 56, right: 24, top: 28, height: 110 },
      { left: 56, right: 24, top: 176, height: 110 },
      { left: 56, right: 24, top: 324, height: 110 },
    ];
    const axisCommon = {
      type: 'category' as const,
      data: days,
      boundaryGap: false,
      axisLabel: { hideOverlap: true, formatter: (v: string) => v.slice(8) + '.' + v.slice(5, 7) + '.' },
    };
    const kcalMarks = [];
    if (t.kcal_min != null) kcalMarks.push({ yAxis: t.kcal_min, name: 'corridor min' });
    if (t.kcal_max != null) kcalMarks.push({ yAxis: t.kcal_max, name: 'corridor max' });

    return {
      animation: false,
      axisPointer: { link: [{ xAxisIndex: 'all' }], label: { backgroundColor: '#555' } },
      tooltip: {
        trigger: 'axis',
        confine: true,
        formatter: (p: unknown) => this.timelineTooltip(p),
      },
      legend: { top: 0, type: 'scroll', icon: 'roundRect' },
      grid: grids,
      xAxis: [
        { ...axisCommon, gridIndex: 0, axisLabel: { show: false } },
        { ...axisCommon, gridIndex: 1, axisLabel: { show: false } },
        { ...axisCommon, gridIndex: 2 },
      ],
      yAxis: [
        { type: 'value', gridIndex: 0, scale: true, name: 'kg', nameGap: 12, splitLine: { lineStyle: { opacity: 0.3 } } },
        { type: 'value', gridIndex: 1, name: 'kcal', nameGap: 12, splitLine: { lineStyle: { opacity: 0.3 } } },
        { type: 'value', gridIndex: 2, name: 'g', nameGap: 12, splitLine: { lineStyle: { opacity: 0.3 } } },
      ],
      series: [
        {
          ...line('Weight (7-day avg.)', pick((r) => r.weight_ma), CHART_PALETTE[0]),
          areaStyle: { opacity: 0.1, color: CHART_PALETTE[0] },
          markLine: t.goal_kg
            ? { symbol: 'none', silent: true, lineStyle: { type: 'dashed', color: CHART_PALETTE[3] }, label: { formatter: 'goal', fontSize: 10, position: 'insideEndTop' }, data: [{ yAxis: t.goal_kg }] }
            : undefined,
        },
        { ...line('Weigh-ins', pick((r) => r.weight), CHART_PALETTE[4]), showSymbol: true, symbolSize: 4, lineStyle: { opacity: 0 }, connectNulls: false },
        {
          name: 'Intake',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: pick((r) => r.kcal),
          itemStyle: { color: CHART_PALETTE[1], opacity: 0.75 },
          markLine: kcalMarks.length
            ? { symbol: 'none', silent: true, lineStyle: { type: 'dotted', color: CHART_PALETTE[2] }, label: { formatter: '{b}', fontSize: 10, position: 'insideEndTop' }, data: kcalMarks }
            : undefined,
        },
        line(`TDEE (${t.tdee_window} d)`, pick((r) => r.tdee), CHART_PALETTE[2], { xAxisIndex: 1, yAxisIndex: 1 }),
        line('Protein', pick((r) => r.protein), CHART_PALETTE[0], { xAxisIndex: 2, yAxisIndex: 2 }),
        line('Carbs', pick((r) => r.carbs), CHART_PALETTE[1], { xAxisIndex: 2, yAxisIndex: 2 }),
        line('Fat', pick((r) => r.fat), CHART_PALETTE[3], { xAxisIndex: 2, yAxisIndex: 2 }),
        line('Fiber', pick((r) => r.fiber), CHART_PALETTE[4], { xAxisIndex: 2, yAxisIndex: 2 }),
      ] as EChartsOption['series'],
    };
  }

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
      tooltip: { trigger: 'axis', confine: true, formatter: (p: unknown) => this.burndownTooltip(p, bd) },
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

  // ── body composition ─────────────────────────────────────────────────────

  private static readonly CIRCUMFERENCE_LABELS: Record<string, string> = {
    waist_cm: 'Waist',
    belly_cm: 'Belly',
    hip_cm: 'Hip',
    chest_cm: 'Chest',
    neck_cm: 'Neck',
    thigh_cm: 'Thigh',
    arm_cm: 'Arm',
  };

  body(): BodyCompositionBlock {
    return this.block() as BodyCompositionBlock;
  }

  energy(): EnergySplitBlock {
    return this.block() as EnergySplitBlock;
  }

  absOf(value: number): number {
    return Math.abs(value);
  }

  maxOf(value: number, floor: number): number {
    return Math.max(value, floor);
  }

  /** The measures that could be computed, in a fixed order with their precision. */
  rated(): { label: string; rated: RatedValue; decimals: number }[] {
    const b = this.body();
    const out: { label: string; rated: RatedValue; decimals: number }[] = [];
    if (b.bmi) out.push({ label: 'BMI', rated: b.bmi, decimals: 1 });
    if (b.waist_to_height) out.push({ label: 'Waist to height', rated: b.waist_to_height, decimals: 2 });
    if (b.waist_to_hip) out.push({ label: 'Waist to hip', rated: b.waist_to_hip, decimals: 2 });
    return out;
  }

  circumferences(): { key: string; label: string; value: number; change: number | null }[] {
    const b = this.body();
    return Object.entries(ReportBlockView.CIRCUMFERENCE_LABELS)
      .filter(([key]) => b.circumferences[key] != null)
      .map(([key, label]) => ({
        key,
        label,
        value: b.circumferences[key],
        change: b.changes[key] ?? null,
      }));
  }

  /**
   * The scale as segments, so the reader sees the whole range and not only the class.
   *
   * The open classes at either end have no width of their own, so they are drawn as wide
   * as the average closed one; otherwise a bar with an open top would be meaningless.
   */
  segments(r: RatedValue): { name: string; tone: string; weight: number; here: boolean; title: string }[] {
    const widths = r.bands
      .filter((b) => b.lower != null && b.upper != null)
      .map((b) => b.upper! - b.lower!);
    const fallback = widths.length ? widths.reduce((a, c) => a + c, 0) / widths.length : 1;
    return r.bands.map((b) => ({
      name: b.name,
      tone: b.tone,
      weight: b.lower != null && b.upper != null ? b.upper - b.lower : fallback,
      here: b.name === r.band,
      title: `${b.name}: ${b.lower ?? '–'} to ${b.upper ?? '–'}`,
    }));
  }

  /** Where the value sits along the drawn scale, as a percentage. */
  position(r: RatedValue): number {
    const segs = this.segments(r);
    const total = segs.reduce((a, s) => a + s.weight, 0);
    if (!total) return 0;
    let before = 0;
    for (const [i, band] of r.bands.entries()) {
      if (band.name !== r.band) {
        before += segs[i].weight;
        continue;
      }
      const lower = band.lower ?? r.value - segs[i].weight;
      const upper = band.upper ?? r.value + segs[i].weight;
      const within = upper > lower ? (r.value - lower) / (upper - lower) : 0.5;
      const clamped = Math.min(Math.max(within, 0), 1);
      return ((before + clamped * segs[i].weight) / total) * 100;
    }
    return 100;
  }

  toneTag(tone: string): string {
    return tone === 'ok' ? 'ok' : tone === 'bad' ? 'bad' : 'warn';
  }

  /** Whether the current weight falls in this class, for the kilogram table. */
  inBand(mark: ThresholdMark): boolean {
    const kg = this.body().weight_kg;
    if (kg == null) return false;
    if (mark.lower != null && kg < mark.lower) return false;
    return !(mark.upper != null && kg >= mark.upper);
  }

  weeklyChart(): EChartsOption {
    const rows = this.weekly().rows;
    return {
      animation: false,
      grid: { left: 56, right: 56, top: 32, bottom: 32 },
      tooltip: { trigger: 'axis', confine: true },
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
