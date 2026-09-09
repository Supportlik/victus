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
  Message,
  Quality,
  ReportBlock,
  TdeeWindowsBlock,
  TextFindingBlock,
  TimelineBlock,
  TrendBlock,
  WeeklyChartBlock,
} from '../../../api';
import { FormatService } from '../../../core/format.service';
import { I18nService } from '../../../core/i18n.service';
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
      <div class="v-panel failed"><h3>{{ i18n.t(block().meta.title) }}</h3><p class="v-small">{{ i18n.t('Could not compute this block:') }} {{ failed().message }}</p></div>
    } @else {
      @switch (block().meta.type) {
        @case ('kpi_tile') {
          <div class="tile" [class]="'tile ' + toneOf(kpi().zone ?? kpi().quality)">
            <span class="t">{{ i18n.t(kpi().meta.title) }}</span>
            <span class="v">{{ kpiValue() }} <span class="u">{{ i18n.t(kpi().unit) }}</span></span>
            @if (kpi().delta != null) { <span class="d">{{ formatSigned(kpi().delta, kpi().decimals) }} {{ i18n.t('vs. previous period') }}</span> }
            @if (kpi().note) { <span class="d">{{ i18n.msg(kpi().note) }}</span> }
          </div>
        }
        @case ('band_distribution') {
          <div class="v-panel">
            <h3>{{ i18n.t(block().meta.title) }}</h3>
            <div class="v-scroll-x">
              <table class="v-table">
                <thead><tr><th>{{ i18n.t('Nutrient') }}</th><th>{{ i18n.t('Distribution') }}</th><th class="num">{{ i18n.t('below min') }}</th><th class="num">{{ i18n.t('below opt.') }}</th><th class="num">{{ i18n.t('optimal') }}</th><th class="num">{{ i18n.t('above opt.') }}</th><th class="num">{{ i18n.t('above max') }}</th><th class="num">Ø</th><th class="num">{{ i18n.t('days') }}</th></tr></thead>
                <tbody>
                  @for (r of dist().rows; track r.macro) {
                    <tr>
                      <td>{{ i18n.t(r.macro) }}@if (r.band) { <span class="v-small v-muted"> {{ r.band.min }} / {{ r.band.opt_min }}–{{ r.band.opt_max }} / {{ r.band.max }}</span> }</td>
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
          </div>
        }
        @case ('tdee_windows') {
          <div class="v-panel">
            <h3>{{ i18n.t(block().meta.title) }} @if (tdee().reference_tdee != null) { <span class="v-small v-muted">{{ i18n.t('reference') }} {{ formatMacro(tdee().reference_tdee, 'kcal') }} kcal, {{ i18n.msg(tdee().reference_basis) }}</span> }</h3>
            <div class="v-scroll-x">
              <table class="v-table">
                <thead><tr><th>{{ i18n.t('Window') }}</th><th class="num">Ø kcal</th><th class="num">Δ {{ i18n.t('weight') }}</th><th class="num">TDEE</th><th class="num">{{ i18n.t('Coverage') }}</th><th class="num">{{ i18n.t('in / above corridor') }}</th>@if (tdee().show_quality) { <th>{{ i18n.t('Grade') }}</th> }</tr></thead>
                <tbody>
                  @for (r of tdee().rows; track r.window_days) {
                    <tr>
                      <td>{{ i18n.t('{n} days', { n: r.window_days }) }}</td><td class="num">{{ formatMacro(r.mean_kcal, 'kcal') }}</td>
                      <td class="num">{{ formatSigned(r.delta_ma_kg, 2, 'kg') }}</td>
                      <td class="num">{{ formatMacro(r.tdee, 'kcal') }}@if (r.tdee == null && r.rejected_tdee != null) { <span class="v-small v-muted" [title]="i18n.t('rejected as implausible')">({{ formatMacro(r.rejected_tdee, 'kcal') }})</span> }</td>
                      <td class="num">{{ r.coverage_pct }} %</td><td class="num">{{ r.in_corridor }} / {{ r.above_corridor }}</td>
                      @if (tdee().show_quality) { <td><span class="v-tag" [class]="'v-tag ' + toneOf(r.quality)">{{ gradeLabel(r.quality) }}</span>@if (r.days_without_macros) { <span class="v-small v-muted"> {{ i18n.t('{n} days without macros', { n: r.days_without_macros }) }}</span> }</td> }
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          </div>
        }
        @case ('trend') {
          <div class="v-panel">
            <h3>{{ i18n.t(block().meta.title) }}</h3>
            <div class="v-scroll-x">
              <table class="v-table">
                <thead><tr><th>{{ i18n.t('Window') }}</th><th class="num">{{ i18n.t('kg / day') }}</th><th class="num">{{ i18n.t('kg / week') }}</th><th class="num">{{ i18n.t('actual change') }}</th><th class="num">{{ i18n.t('weigh-ins') }}</th></tr></thead>
                <tbody>@for (r of trend().rows; track r.window) {
                  <tr><td>{{ i18n.t('{n} days', { n: r.window }) }}</td><td class="num">{{ formatSigned(r.slope_per_day, 3) }}</td><td class="num">{{ formatSigned(r.kg_per_week, 2) }}</td><td class="num">{{ formatSigned(r.actual_delta, 1, 'kg') }}</td><td class="num">{{ r.measured_days }}</td></tr>
                }</tbody>
              </table>
            </div>
          </div>
        }
        @case ('forecast') {
          <div class="v-panel">
            <h3>{{ i18n.t(block().meta.title) }} <span class="v-small v-muted">{{ i18n.t('goal {kg} by {date}', { kg: formatKg(forecast().goal_kg) + ' kg', date: forecast().goal_date }) }}@if (forecast().current_kg != null) { · {{ i18n.t('now') }} {{ formatKg(forecast().current_kg) }} kg }</span></h3>
            <div class="v-scroll-x">
              <table class="v-table">
                <thead><tr><th>{{ i18n.t('Based on') }}</th><th class="num">{{ i18n.t('kg / week') }}</th><th class="num">{{ i18n.t('in 1 month') }}</th><th class="num">{{ i18n.t('3 months') }}</th><th class="num">{{ i18n.t('6 months') }}</th><th class="num">{{ i18n.t('at goal date') }}</th>@if (forecast().with_eta) { <th>{{ i18n.t('goal reached') }}</th> }</tr></thead>
                <tbody>@for (r of forecast().rows; track r.window) {
                  <tr><td>{{ i18n.t('{n}-day trend', { n: r.window }) }}</td><td class="num">{{ formatSigned(r.kg_per_week, 2) }}</td><td class="num">{{ formatKg(r.m1) }}</td><td class="num">{{ formatKg(r.m3) }}</td><td class="num">{{ formatKg(r.m6) }}</td><td class="num">{{ formatKg(r.at_goal_date) }}</td>@if (forecast().with_eta) { <td>{{ r.eta ?? i18n.t('not on this trend') }}</td> }</tr>
                }</tbody>
              </table>
            </div>
          </div>
        }
        @case ('burndown') {
          <div class="v-panel">
            <h3>{{ i18n.t(block().meta.title) }} <span class="v-small v-muted">{{ formatSigned(burndown().result.gap, 1, 'kg') }} {{ i18n.t('vs. plan') }} · {{ i18n.t('actual') }} {{ formatSigned(burndown().result.actual_rate_per_week, 2, 'kg/week') }} · {{ i18n.t('required') }} {{ formatSigned(burndown().result.required_rate_per_week, 2, 'kg/week') }}</span></h3>
            <div echarts [options]="burndownChart()" class="echart" [attr.aria-label]="i18n.t('Planned versus actual weight')"></div>
            @if (burndown().result.stages.length) {
              <p class="v-small v-muted">{{ i18n.t('Below the goal line means ahead of plan. Each dotted line is one of your stages.') }}</p>
              <div class="v-scroll-x">
                <table class="v-table stages">
                  <thead><tr><th>{{ i18n.t('Stage') }}</th><th>{{ i18n.t('Date') }}</th><th class="num">{{ i18n.t('gap') }}</th><th class="num">{{ i18n.t('required kg / week') }}</th><th class="num">{{ i18n.t('eat kcal / day') }}</th><th>{{ i18n.t('feasible') }}</th></tr></thead>
                  <tbody>@for (st of burndown().result.stages; track st.name) {
                    <tr><td>{{ st.name }}</td><td>{{ st.date }}</td><td class="num">{{ formatSigned(st.gap, 1, 'kg') }}</td><td class="num">{{ formatSigned(st.required_kg_per_week, 2) }}</td><td class="num">{{ st.eat_kcal_per_day == null ? '–' : formatMacro(st.eat_kcal_per_day, 'kcal') }}</td><td>{{ st.feasible ? i18n.t('yes') : i18n.t('no') }}</td></tr>
                  }</tbody>
                </table>
              </div>
            }
          </div>
        }
        @case ('weekly_chart') {
          <div class="v-panel">
            <h3>{{ i18n.t(block().meta.title) }}</h3>
            <div echarts [options]="weeklyChart()" class="echart" [attr.aria-label]="i18n.t('Weekly intake and expenditure')"></div>
          </div>
        }
        @case ('timeline') {
          <div class="v-panel">
            <h3>{{ i18n.t(block().meta.title) }} <span class="v-small v-muted">{{ i18n.t('weight, intake, rolling {n}-day TDEE and macros on one axis', { n: timeline().tdee_window }) }}</span></h3>
            <div echarts [options]="timelineChart()" class="echart tall" [attr.aria-label]="i18n.t('Weight, intake, TDEE and macros over time')"></div>
          </div>
        }
        @case ('day_list') {
          <div class="v-panel">
            <h3>{{ i18n.t(block().meta.title) }}</h3>
            <div class="v-scroll-x"><table class="v-table">
              <thead><tr><th>{{ i18n.t('Day') }}</th>@for (c of dayList().columns; track c) { <th class="num">{{ c }}</th> }</tr></thead>
              <tbody>@for (r of dayList().rows; track r.date) {
                <tr [class.not-countable]="!r.countable"><td>{{ r.date }}</td>@for (c of dayList().columns; track c) {
                  <td class="num">
                    @if (c === 'status') { @if (r.status) { <v-status-tag [status]="r.status" /> } }
                    @else if (c === 'weight') { {{ formatKg(r.weight) }} }
                    @else if (c === 'training_type') { {{ r.training_type ?? '' }} }
                    @else if (c === 'reliable') { {{ r.reliable === null ? '?' : r.reliable ? i18n.t('yes') : i18n.t('no') }} }
                    @else { {{ formatMacro(r.macros[asMacro(c)], asMacro(c)) }} }
                  </td>
                }</tr>
              }</tbody>
            </table></div>
          </div>
        }
        @case ('text_finding') {
          <div class="v-panel finding">
            <h3>{{ i18n.t(block().meta.title) }}</h3>
            @if (finding().markdown) { <div class="v-md" [innerHTML]="finding().markdown | markdown"></div> } @else {
              <p class="v-muted">{{ i18n.t('No assessment yet. Freeze this report below to keep its numbers, then let Claude judge that moment. The text and the figures then belong together.') }}</p>
            }
          </div>
        }
        @case ('body_composition') {
          <div class="v-panel body">
            <h3>{{ i18n.t(block().meta.title) }}</h3>
            @if (body().weight_kg != null) {
              <p class="v-small v-muted">
                {{ format.number(body().weight_kg!, 1) }} kg@if (body().height_cm) { {{ i18n.t('at {cm} cm', { cm: body().height_cm! }) }} }
                @if (body().measured_at) { · {{ i18n.t('measured') }} {{ format.day(body().measured_at!) }} }
              </p>
            }
            @for (m of rated(); track m.label) {
              <div class="measure">
                <div class="head">
                  <span class="what">{{ m.label }}</span>
                  <span class="mid">
                    <span class="val">{{ format.number(m.rated.value, m.decimals) }}</span>
                    @if (m.rated.to_next != null) {
                      <span class="v-small v-muted">{{ format.number(absOf(m.rated.to_next), m.decimals) }} {{ i18n.t('to the next class') }}</span>
                    }
                  </span>
                  <span [class]="'v-tag ' + toneTag(m.rated.tone)">{{ i18n.t(m.rated.band) }}</span>
                </div>
                <div class="scale" [attr.aria-label]="m.label + ': ' + i18n.t(m.rated.band)">
                  @for (seg of segments(m.rated); track seg.name) {
                    <span [class]="seg.classes" [style.flex]="seg.weight" [title]="seg.title"></span>
                  }
                  <span class="pin" [style.left.%]="position(m.rated)"></span>
                </div>
              </div>
            }
            @if (body().bmi_weight_bands.length && body().weight_kg != null) {
              <div class="marks">
                <p class="v-small v-muted title">{{ i18n.t('What the classes mean in kilograms') }}</p>
                <div class="v-scroll-x">
                  <table class="v-table">
                    <thead>
                      <tr>
                        <th>{{ i18n.t('Class') }}</th>
                        <th class="num">BMI</th>
                        <th class="num">kg</th>
                        <th class="num">{{ i18n.t('still needed') }}</th>
                      </tr>
                    </thead>
                    <tbody>
                      @for (m of body().bmi_weight_bands; track m.name) {
                        <tr [class.here]="inBand(m)">
                          <td>{{ i18n.t(m.name) }}</td>
                          <td class="num">{{ range(m.lower, m.upper, 1) }}</td>
                          <td class="num">{{ range(m.lower_kg, m.upper_kg, 1) }}</td>
                          <td class="num">
                            @if (inBand(m)) { {{ i18n.t('you are here') }} }
                            @else if (m.to_reach_kg != null) {
                              {{ (m.to_reach_kg > 0 ? '+' : '−') + format.number(absOf(m.to_reach_kg), 1) }} kg
                            } @else { – }
                          </td>
                        </tr>
                      }
                    </tbody>
                  </table>
                </div>
              </div>
            }
            @if (circumferences().length) {
              <div class="v-scroll-x">
                <table class="v-table circ">
                  <thead><tr><th></th><th class="num">{{ i18n.t('now') }}</th><th class="num">{{ i18n.t('Change') }}</th></tr></thead>
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
              </div>
            }
            @if (body().missing.length) {
              <p class="v-small v-muted">{{ i18n.t('Not shown: {reasons}.', { reasons: reasons(body().missing) }) }}</p>
            }
          </div>
        }
        @case ('energy_split') {
          <div class="v-panel energy">
            <h3>{{ i18n.t(block().meta.title) }}</h3>
            @if (energy().tdee_kcal == null) {
              <p class="v-muted">{{ i18n.t('Not available: {reasons}.', { reasons: reasons(energy().missing) || i18n.t('no data') }) }}</p>
            } @else {
              <div class="rows">
                <div><span>{{ i18n.t('Expenditure') }}</span><b>{{ format.number(energy().tdee_kcal!) }} kcal</b><span class="v-small v-muted">{{ i18n.msg(energy().basis) }}</span></div>
                @if (energy().basal_kcal != null) {
                  <div>
                    <span>{{ i18n.t('At rest') }}</span>
                    <b>{{ format.number(energy().basal_kcal!) }} kcal</b>
                    <span class="share">{{ format.number(sharePct(energy().basal_kcal!), 0) }} %</span>
                    <span class="v-small v-muted">{{ i18n.t('age {n}', { n: energy().age_years ?? '' }) }}</span>
                  </div>
                  <div>
                    <span>{{ i18n.t('From moving') }}</span>
                    <b>{{ format.number(energy().activity_kcal!) }} kcal</b>
                    <span class="share">{{ format.number(sharePct(energy().activity_kcal!), 0) }} %</span>
                    <span class="v-small v-muted">{{ format.number(energy().pal!, 2) }} × {{ i18n.t('resting') }}</span>
                  </div>
                }
              </div>
              @if (energy().basal_kcal != null) {
                <div class="split" [attr.aria-label]="i18n.t('resting versus activity')">
                  <span class="rest" [style.flex]="energy().basal_kcal!">{{ i18n.t('at rest') }} {{ format.number(sharePct(energy().basal_kcal!), 0) }} %</span>
                  <span class="move" [style.flex]="maxOf(energy().activity_kcal!, 1)">{{ i18n.t('moving') }} {{ format.number(sharePct(energy().activity_kcal!), 0) }} %</span>
                </div>
              }
              @if (energy().caveat) { <p class="v-small warn-text">{{ i18n.msg(energy().caveat) }}</p> }
              @if (energy().missing.length) { <p class="v-small v-muted">{{ i18n.t('Not shown: {reasons}.', { reasons: reasons(energy().missing) }) }}</p> }
            }
          </div>
        }
        @default {
          <div class="v-panel v-muted">{{ i18n.t('Block type “{type}” is not supported by this version of the app.', { type: block().meta.type }) }}</div>
        }
      }
    }
  `,
  styles: `
    .body, .energy { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.6rem; }
    .measure { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.3rem; }
    /* Name on the left, the figure in the middle, the class it falls in on the right:
       the chip is the answer, so it sits where the eye stops. */
    .measure .head { display: flex; gap: 0.5rem 0.75rem; align-items: center; }
    .measure .what { color: var(--v-ink-2); }
    .measure .mid { flex: 1; display: flex; justify-content: center; align-items: baseline; gap: 0.5rem; min-width: 0; }
    .measure .val { font-size: var(--v-fs-l); font-weight: 600; font-variant-numeric: tabular-nums; }
    .measure .v-tag { flex: none; }
    .scale { position: relative; display: flex; height: 0.7rem; border-radius: 999px; overflow: hidden; background: var(--v-surface-2); }
    /* A segment is coloured by what its class means, so the bar and the chip beside it
       agree. Where a scale repeats a meaning — WHO has three classes of obesity, all of
       them "bad" — the further one takes the next step of the ramp, which is the only
       thing the ramp is for. The class the value falls in is not highlighted: the pin
       already says where it is. */
    .seg { display: block; }
    .seg.t-ok { background: var(--v-scale-1); }
    .seg.t-watch { background: var(--v-scale-2); }
    .seg.t-warn { background: var(--v-scale-3); }
    .seg.t-warn.lvl2 { background: var(--v-scale-4); }
    .seg.t-warn.lvl3 { background: var(--v-scale-5); }
    .seg.t-bad { background: var(--v-scale-5); }
    .seg.t-bad.lvl2 { background: var(--v-scale-5); filter: brightness(0.85); }
    .pin { position: absolute; top: -0.15rem; width: 2px; height: 1rem; background: var(--v-ink); transform: translateX(-1px); }
    .marks { margin-top: 0.4rem; }
    .marks .title { margin: 0 0 0.2rem; }
    /* The row the weight falls in is marked at its edge, not filled: a bright band across
       a table of numbers reads as an alert, and this is only "you are here". */
    .marks tr.here td { font-weight: 600; }
    .marks tr.here td:first-child { box-shadow: inset 3px 0 0 var(--v-primary); }
    .circ .down { color: var(--v-ok-ink); }
    .circ .up { color: var(--v-warn-ink); }
    .energy .rows { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.3rem; }
    .energy .rows > div { display: flex; gap: 0.5rem; align-items: baseline; }
    .energy .rows > div > span:first-child { min-width: 8rem; color: var(--v-ink-2); }
    .energy .rows b { font-variant-numeric: tabular-nums; }
    .energy .share { color: var(--v-ink-2); font-variant-numeric: tabular-nums; min-width: 3rem; }
    .split { display: flex; height: 1.4rem; border-radius: var(--v-radius); overflow: hidden; font-size: var(--v-fs-xs); }
    .split span { display: grid; grid-template-columns: minmax(0, 1fr); place-items: center; color: var(--v-primary-ink); }
    .split .rest { background: var(--v-primary); }
    .split .move { background: var(--v-ok); }
    .warn-text { color: var(--v-warn-ink); }

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
  readonly i18n = inject(I18nService);
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

  /** The burndown tooltip has to find this line among the hovered ones, so both read it here. */
  private actualSeries(): string {
    return this.i18n.t('Actual (7-day avg.)');
  }

  private tdeeSeries(days: number): string {
    return this.i18n.t('TDEE ({n} d)', { n: days });
  }
  gradeLabel(q: Quality | null): string {
    if (q === 'green') return this.i18n.t('reliable');
    if (q === 'yellow') return this.i18n.t('indicative');
    if (q === 'red') return this.i18n.t('too little data');
    return this.i18n.t('no grade');
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
    const day = (v: string | number) =>
      this.format.day(typeof v === 'number' ? new Date(v).toISOString() : v);
    const dot = (c?: string) => `<span style="display:inline-block;width:.55em;height:.55em;border-radius:50%;background:${c ?? 'currentColor'};margin-right:.4em"></span>`;

    const head = rows[0]?.value ? day(rows[0].value[0]) : '';
    const actualRow = rows.find((r) => r.seriesName === this.actualSeries());
    const remainingNow = actualRow?.value?.[1];
    const lines: string[] = [];

    if (actualRow && remainingNow != null) {
      const i = actualRow.dataIndex ?? -1;
      const prev = i > 0 ? actual[i - 1]?.[1] : undefined;
      const delta = prev != null ? remainingNow - prev : undefined;
      const change =
        delta == null
          ? ''
          : ' · ' +
            this.i18n.t('{delta} kg vs. the day before', {
              delta: `${delta <= 0 ? '−' : '+'}${Math.abs(delta).toFixed(2)}`,
            });
      const toGo = this.i18n.t('{kg} to go', { kg: kg(remainingNow) });
      lines.push(`${dot(actualRow.color)}<b>${kg(goal + remainingNow)}</b> · ${toGo}${change}`);
    }

    for (const r of rows) {
      if (r === actualRow || r.value == null) continue;
      const planned = r.value[1];
      const gap = remainingNow == null ? null : planned - remainingNow;
      const stand =
        gap == null
          ? ''
          : ' · ' +
            this.i18n.t(gap >= 0 ? '{kg} ahead' : '{kg} behind', { kg: kg(Math.abs(gap)) });
      const plan = this.i18n.t('plan {kg}', { kg: kg(goal + planned) });
      lines.push(`${dot(r.color)}${r.seriesName}: ${plan}${stand}`);
    }

    const last = actual.length ? actual[actual.length - 1][1] : null;
    if (last != null && rows.some((r) => r.seriesName === this.actualSeries())) {
      const goalLine = this.i18n.t('goal {kg} by {date}', { kg: kg(goal), date: bd.goal_date });
      lines.push(`<span class="v-small">${goalLine}</span>`);
    }
    return `${head}<br>${lines.join('<br>')}`;
  }

  /** "rolling_14d" reads like a database column; say it in words. */
  /** The reasons a figure is missing, each translated, as one sentence. */
  reasons(messages: (Message | string)[]): string {
    return messages.map((m) => this.i18n.msg(m)).join('; ');
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

    // The trend line answers "where am I heading", the reading on the scale "what did it
    // say this morning" — a day that has both shows both, and never the same number twice.
    const trend = row.weight_ma ?? row.weight;
    const scale = row.weight != null && row.weight !== row.weight_ma ? row.weight : null;
    const grams = [
      ['Protein', row.protein],
      ['Carbs', row.carbs],
      ['Fat', row.fat],
      ['Fiber', row.fiber],
    ] as const;
    const macros = grams
      .filter(([, v]) => v != null)
      .map(([name, v]) => `${this.i18n.t(name)} ${num(v as number)} g`)
      .join(' · ');
    const flag = row.countable ? '' : ' · ' + this.i18n.t('not counted');

    return [
      `<div style="margin-bottom:.25em"><b>${this.format.day(day ?? '')}</b>${flag}</div>`,
      line(CHART_PALETTE[0], this.i18n.t('Weight (7-day avg.)'), trend, 'kg', 1),
      line(CHART_PALETTE[4], this.i18n.t('Weigh-in'), scale, 'kg', 1),
      line(CHART_PALETTE[1], this.i18n.t('Intake'), row.kcal, 'kcal'),
      line(CHART_PALETTE[2], this.tdeeSeries(this.timeline().tdee_window), row.tdee, 'kcal'),
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
    if (t.kcal_min != null) kcalMarks.push({ yAxis: t.kcal_min, name: this.i18n.t('corridor min') });
    if (t.kcal_max != null) kcalMarks.push({ yAxis: t.kcal_max, name: this.i18n.t('corridor max') });

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
          ...line(this.i18n.t('Weight (7-day avg.)'), pick((r) => r.weight_ma), CHART_PALETTE[0]),
          areaStyle: { opacity: 0.1, color: CHART_PALETTE[0] },
          markLine: t.goal_kg
            ? { symbol: 'none', silent: true, lineStyle: { type: 'dashed', color: CHART_PALETTE[3] }, label: { formatter: this.i18n.t('goal'), fontSize: 10, position: 'insideEndTop' }, data: [{ yAxis: t.goal_kg }] }
            : undefined,
        },
        { ...line(this.i18n.t('Weigh-ins'), pick((r) => r.weight), CHART_PALETTE[4]), showSymbol: true, symbolSize: 4, lineStyle: { opacity: 0 }, connectNulls: false },
        {
          name: this.i18n.t('Intake'),
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: pick((r) => r.kcal),
          itemStyle: { color: CHART_PALETTE[1], opacity: 0.75 },
          markLine: kcalMarks.length
            ? { symbol: 'none', silent: true, lineStyle: { type: 'dotted', color: CHART_PALETTE[2] }, label: { formatter: '{b}', fontSize: 10, position: 'insideEndTop' }, data: kcalMarks }
            : undefined,
        },
        line(this.tdeeSeries(t.tdee_window), pick((r) => r.tdee), CHART_PALETTE[2], { xAxisIndex: 1, yAxisIndex: 1 }),
        line(this.i18n.t('Protein'), pick((r) => r.protein), CHART_PALETTE[0], { xAxisIndex: 2, yAxisIndex: 2 }),
        line(this.i18n.t('Carbs'), pick((r) => r.carbs), CHART_PALETTE[1], { xAxisIndex: 2, yAxisIndex: 2 }),
        line(this.i18n.t('Fat'), pick((r) => r.fat), CHART_PALETTE[3], { xAxisIndex: 2, yAxisIndex: 2 }),
        line(this.i18n.t('Fiber'), pick((r) => r.fiber), CHART_PALETTE[4], { xAxisIndex: 2, yAxisIndex: 2 }),
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
        name: this.i18n.t('kg above goal'),
        nameLocation: 'end',
        nameGap: 12,
        axisLabel: { formatter: '{value}' },
        splitLine: { lineStyle: { opacity: 0.35 } },
      },
      series: [
        {
          name: this.i18n.t('Goal {date}', { date: bd.goal_date }),
          type: 'line',
          showSymbol: false,
          data: b.target_path as [string, number][],
          lineStyle: { type: 'dashed', width: 2, color: CHART_PALETTE[3] },
          itemStyle: { color: CHART_PALETTE[3] },
        },
        ...stageSeries,
        {
          name: this.actualSeries(),
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
                label: { formatter: this.i18n.t('today'), position: 'insideEndTop', fontSize: 10 },
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

  /** One part of the day's expenditure as a share of it: a ratio reads faster than two totals. */
  sharePct(part: number): number {
    const total = this.energy().tdee_kcal;
    return total ? (part / total) * 100 : 0;
  }

  maxOf(value: number, floor: number): number {
    return Math.max(value, floor);
  }

  /** The measures that could be computed, in a fixed order with their precision. */
  rated(): { label: string; rated: RatedValue; decimals: number }[] {
    const b = this.body();
    const out: { label: string; rated: RatedValue; decimals: number }[] = [];
    if (b.bmi) out.push({ label: 'BMI', rated: b.bmi, decimals: 1 });
    if (b.waist_to_height) out.push({ label: this.i18n.t('Waist to height'), rated: b.waist_to_height, decimals: 2 });
    if (b.waist_to_hip) out.push({ label: this.i18n.t('Waist to hip'), rated: b.waist_to_hip, decimals: 2 });
    return out;
  }

  circumferences(): { key: string; label: string; value: number; change: number | null }[] {
    const b = this.body();
    return Object.entries(ReportBlockView.CIRCUMFERENCE_LABELS)
      .filter(([key]) => b.circumferences[key] != null)
      .map(([key, label]) => ({
        key,
        label: this.i18n.t(label),
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
  segments(
    r: RatedValue,
  ): { name: string; classes: string; weight: number; span: number; title: string }[] {
    const widths = r.bands
      .filter((b) => b.lower != null && b.upper != null)
      .map((b) => b.upper! - b.lower!);
    const fallback = widths.length ? widths.reduce((a, c) => a + c, 0) / widths.length : 1;
    const healthy = r.bands.findIndex((b) => b.tone === 'ok');
    const raw = r.bands.map((b) =>
      b.lower != null && b.upper != null ? b.upper - b.lower : fallback,
    );
    const total = raw.reduce((a, c) => a + c, 0) || 1;
    // A segment says what its class means, so the bar agrees with the chip beside it. Only
    // where a scale repeats a meaning does it need more: the three obesity classes are all
    // "bad", so the further one from the healthy class takes the next step of the ramp.
    const anchor = healthy < 0 ? 0 : healthy;
    const rank = new Map<number, number>();
    const perTone = new Map<string, number>();
    // Each side of the healthy class is ranked on its own: underweight and obesity I are
    // both the first "warn" of their direction, and sharing a colour at opposite ends of
    // the bar reads fine. Ranking them together is what made two neighbours identical.
    for (const { i, key } of r.bands
      .map((b, i) => ({ i, key: b.tone + (i < anchor ? '-' : '+'), distance: Math.abs(i - anchor) }))
      .sort((a, c) => a.distance - c.distance)) {
      const next = (perTone.get(key) ?? 0) + 1;
      perTone.set(key, next);
      rank.set(i, next);
    }
    return r.bands.map((b, i) => ({
      name: b.name,
      // one expression, because [class] and [class.x] together drop the flag
      classes: `seg t-${b.tone} lvl${rank.get(i) ?? 1}`,
      // normalised: flex-grow factors summing below 1 fill only that share of the bar
      weight: (raw[i] / total) * 100,
      span: raw[i],
      title: this.segmentTitle(b, r),
    }));
  }

  /** What a segment says on hover: its own range in every unit it has, and the way there. */
  private segmentTitle(b: ThresholdMark, r: RatedValue): string {
    const parts = [this.i18n.t(b.name), this.range(b.lower, b.upper, r.unit === '' ? 1 : 2)];
    if (b.lower_kg != null || b.upper_kg != null) {
      parts.push(`${this.range(b.lower_kg, b.upper_kg, 1)} kg`);
    }
    if (b.name === r.band) {
      parts.push(this.i18n.t('you are here'));
    } else if (b.to_reach_kg != null) {
      const sign = b.to_reach_kg > 0 ? '+' : '−';
      parts.push(
        this.i18n.t('{kg} kg still needed', {
          kg: sign + this.format.number(Math.abs(b.to_reach_kg), 1),
        }),
      );
    }
    return parts.join(' · ');
  }

  /** A range as one string, with an open end shown as such rather than as a dash. */
  range(lower: number | null | undefined, upper: number | null | undefined, decimals: number): string {
    const n = (v: number) => this.format.number(v, decimals);
    if (lower != null && upper != null) return `${n(lower)}–${n(upper)}`;
    if (upper != null) return `< ${n(upper)}`;
    if (lower != null) return `≥ ${n(lower)}`;
    return '–';
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
      // an open class has no range of its own, so its drawn width stands in for one
      const lower = band.lower ?? r.value - segs[i].span;
      const upper = band.upper ?? r.value + segs[i].span;
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
        { name: this.i18n.t('Ø intake'), type: 'bar', data: rows.map((r) => r.mean_kcal), itemStyle: { color: CHART_PALETTE[0] } },
        { name: this.i18n.t('Weekly TDEE'), type: 'line', data: rows.map((r) => r.tdee), itemStyle: { color: CHART_PALETTE[1] }, lineStyle: { color: CHART_PALETTE[1] } },
        { name: this.i18n.t('Ø weight'), type: 'line', yAxisIndex: 1, data: rows.map((r) => r.mean_kg), itemStyle: { color: CHART_PALETTE[2] }, lineStyle: { color: CHART_PALETTE[2] } },
      ],
    };
  }
}
