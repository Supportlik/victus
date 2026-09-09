import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgxEchartsDirective } from 'ngx-echarts';
import type { EChartsOption, ScatterSeriesOption } from 'echarts';
import { ApiClient, BodyMeasurement, WeightEntry } from '../../api';
import { I18nService } from '../../core/i18n.service';
import { FormatService, isoDayIn } from '../../core/format.service';
import { describeError } from '../../core/problem';
import { isoDate, KgPipe, shiftDate } from '../../shared/format';
import { CHART_PALETTE } from '../reports/report-blocks/palette';

/** The circumferences a session may carry. */
type CircumferenceKey = 'waist_cm' | 'belly_cm' | 'hip_cm' | 'chest_cm' | 'neck_cm' | 'thigh_cm' | 'arm_cm';

/** How many sessions fit across the table before the older ones only clutter it. */
const BODY_COLUMNS = 4;

/** A measure across the shown sessions: newest value first, oldest last. */
interface BodyRow {
  key: string;
  label: string;
  unit: string;
  values: (number | null)[];
  change: number | null;
}

/**
 * Value for a `datetime-local` field: the wall clock of the configured zone, not UTC.
 * `toISOString().slice(0, 16)` would offer the wrong hour, and just after midnight the
 * wrong day (R69).
 */
function localDateTimeValue(at: Date = new Date()): string {
  const day = isoDayIn(at);
  const time = at.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${day}T${time}`;
}

/** Weigh-ins from the scale sync plus manual entries; the moving average is computed here for display. */
@Component({
  selector: 'v-weight-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, NgxEchartsDirective, KgPipe],
  template: `
    <div class="v-page">
      <header class="v-page-head">
        <div><h2>{{ i18n.t('Weight') }}</h2><p class="sub">{{ i18n.t('Your scale syncs automatically. Add an entry by hand only when it was not around.') }}</p></div>
        <label class="v-field"><span>{{ i18n.t('Range') }}</span>
          <select [ngModel]="days()" (ngModelChange)="days.set(+$event); load()"><option [value]="30">{{ i18n.t('30 days') }}</option><option [value]="90">{{ i18n.t('90 days') }}</option><option [value]="365">{{ i18n.t('1 year') }}</option><option [value]="3650">{{ i18n.t('all') }}</option></select>
        </label>
      </header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
      <div class="v-panel chart">
        @if (entries().length) {
          <div echarts [options]="chart()" class="echart" [attr.aria-label]="i18n.t('Weight over time')"></div>
        } @else { <div class="v-empty">{{ i18n.t('No weigh-ins in this range.') }}</div> }
      </div>
      <div class="grid">
        <form class="v-panel add" (ngSubmit)="add()">
          <h3>{{ i18n.t('Add a weigh-in') }}</h3>
          <div class="v-form-row">
            <label class="v-field"><span>{{ i18n.t('Date and time') }}</span><input name="at" type="datetime-local" [(ngModel)]="measuredAt" required /></label>
            <label class="v-field"><span>kg</span><input name="kg" type="number" step="0.1" min="30" max="300" [(ngModel)]="kg" required /></label>
          </div>
          <button type="submit" class="v-btn primary" [disabled]="!kg">{{ i18n.t('Add weigh-in') }}</button>
        </form>
        <form class="v-panel add" (ngSubmit)="addBody()">
          <h3>{{ i18n.t('Add body measurements') }}</h3>
          <p class="v-small v-muted">{{ i18n.t('The scale says how heavy, the tape says where it sits. Fill in only what you measured; the rest stays empty rather than becoming zero.') }}</p>
          <label class="v-field"><span>{{ i18n.t('Date and time') }}</span><input name="bat" type="datetime-local" [(ngModel)]="bodyAt" required /></label>
          <div class="v-form-row cm">
            @for (f of bodyFields; track f.key) {
              <label class="v-field">
                <span>{{ i18n.t(f.label) }} <span class="v-muted">cm</span></span>
                <input [name]="f.key" type="number" step="0.1" min="10" max="250" [(ngModel)]="body[f.key]" />
              </label>
            }
            <label class="v-field"><span>{{ i18n.t('Body fat') }} <span class="v-muted">%</span></span><input name="bf" type="number" step="0.1" min="3" max="70" [(ngModel)]="bodyFat" /></label>
          </div>
          <label class="v-field"><span>{{ i18n.t('Note') }}</span><input name="bnote" [(ngModel)]="bodyNote" [placeholder]="i18n.t('tape, morning, before breakfast')" /></label>
          <button type="submit" class="v-btn primary" [disabled]="!anyBodyValue()">{{ i18n.t('Add measurements') }}</button>
        </form>
        <div class="v-scroll-x">
          <table class="v-table">
            <thead><tr><th>{{ i18n.t('When') }}</th><th class="num">kg</th><th>{{ i18n.t('Source') }}</th><th></th></tr></thead>
            <tbody>
              @for (w of recent(); track w.id) {
                <tr>
                  <td>{{ w.measured_at.replace('T', ' ').slice(0, 16) }}</td><td class="num">{{ w.kg | kg }}</td>
                  <td>@if (w.source === 'manual') { <span class="v-tag">{{ i18n.t('manual') }}</span> } @else { <span class="v-small v-muted">{{ i18n.t(w.source === 'scale_sync' ? 'scale' : w.source) }}</span> }</td>
                  <td class="num">@if (w.source === 'manual') { <button type="button" class="v-btn quiet small danger" (click)="remove(w)">{{ i18n.t('remove') }}</button> }</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      </div>
      @if (bodyRows().length) {
        <section class="v-panel body-log">
          <h3>{{ i18n.t('Body measurements') }}</h3>
          <div class="v-scroll-x">
            <table class="v-table">
              <thead>
                <tr>
                  <th class="what">{{ i18n.t('Measure') }}</th>
                  @for (c of bodyColumns(); track c.m.id) {
                    <th class="num session">
                      <span class="day">{{ format.day(c.day) }}</span>
                      <button type="button" class="v-btn quiet small danger" (click)="removeBody(c.m)">{{ i18n.t('remove') }}</button>
                    </th>
                  }
                  <th class="num">{{ i18n.t('Change') }}</th>
                </tr>
              </thead>
              <tbody>
                @for (r of bodyRows(); track r.key) {
                  <tr>
                    <th scope="row" class="what">{{ i18n.t(r.label) }} <span class="v-muted">{{ r.unit }}</span></th>
                    @for (v of r.values; track $index) {
                      <td class="num">{{ v == null ? '–' : format.number(v, 1) }}</td>
                    }
                    <td class="num" [class.down]="(r.change ?? 0) < 0" [class.up]="(r.change ?? 0) > 0">
                      {{ r.change == null ? '–' : (r.change > 0 ? '+' : '−') + format.number(abs(r.change), 1) }}
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </section>
      }
    </div>
  `,
  styles: `
    .chart { margin-bottom: 1.25rem; } .echart { height: 20rem; width: 100%; }
    .grid { display: grid; grid-template-columns: minmax(16rem, 1fr) minmax(0, 2fr); gap: 1.5rem; align-items: start; }
    .add { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.75rem; }
    .add .cm { grid-template-columns: repeat(auto-fit, minmax(7rem, 1fr)); }
    .body-log { margin-top: 1.5rem; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.6rem; }
    /* the measure names stay put while the sessions scroll past on a narrow screen */
    .body-log .what { position: sticky; left: 0; background: var(--v-surface); white-space: nowrap; text-align: left; }
    .body-log .session { white-space: nowrap; }
    .body-log .session .day { display: block; }
    .body-log .down { color: var(--v-ok-ink); }
    .body-log .up { color: var(--v-warn-ink); }
    @media (max-width: 52rem) { .grid { grid-template-columns: 1fr; } }
  `,
})
export class WeightPage {
  private readonly api = inject(ApiClient);
  readonly i18n = inject(I18nService);
  readonly days = signal(90);
  readonly entries = signal<WeightEntry[]>([]);
  readonly measurements = signal<BodyMeasurement[]>([]);
  readonly settings = signal<Record<string, unknown> | null>(null);
  readonly error = signal<string | null>(null);
  readonly format = inject(FormatService);
  measuredAt = localDateTimeValue();
  kg: number | null = null;

  /** The circumferences, in the order they are asked for and shown. */
  readonly bodyFields: { key: CircumferenceKey; label: string }[] = [
    { key: 'waist_cm', label: 'Waist' },
    { key: 'belly_cm', label: 'Belly' },
    { key: 'hip_cm', label: 'Hip' },
    { key: 'chest_cm', label: 'Chest' },
    { key: 'neck_cm', label: 'Neck' },
    { key: 'thigh_cm', label: 'Thigh' },
    { key: 'arm_cm', label: 'Arm' },
  ];
  bodyAt = localDateTimeValue();
  body: Record<CircumferenceKey, number | null> = {
    waist_cm: null, belly_cm: null, hip_cm: null, chest_cm: null,
    neck_cm: null, thigh_cm: null, arm_cm: null,
  };
  bodyFat: number | null = null;
  bodyNote = '';

  /** Height from the settings; without it the chart cannot show BMI classes. */
  readonly heightCm = computed(() => {
    const data = this.settings();
    const section = (data?.['body'] ?? {}) as { height_cm?: number };
    return typeof section.height_cm === 'number' ? section.height_cm : null;
  });

  /**
   * The BMI classes as shaded bands behind the curve, in kilograms.
   *
   * A weight on its own says little: the same 96 kg is one class at 170 cm and another at
   * 190. Without a height in the settings there is nothing to draw and the chart stays as
   * it was (R76). Attached to the weigh-in series rather than a series of its own, so the
   * legend keeps two entries.
   */
  private bmiArea(): ScatterSeriesOption['markArea'] {
    const height = this.heightCm();
    if (!height) return undefined;
    const metres = height / 100;
    const kg = (bmi: number) => Math.round(bmi * metres * metres * 10) / 10;
    // WHO classes; the outer two are open and are left open here too
    const classes: { name: string; from: number | null; to: number | null; tone: string }[] = [
      { name: 'underweight', from: null, to: 18.5, tone: 'warn' },
      { name: 'normal weight', from: 18.5, to: 25, tone: 'ok' },
      { name: 'overweight', from: 25, to: 30, tone: 'watch' },
      // the domain's own names (domain/services/body.py::BMI_BANDS), so the dictionary
      // finds them; "obesity III" was a second spelling with no entry anywhere
      { name: 'obesity class I', from: 30, to: 35, tone: 'warn' },
      { name: 'obesity class II', from: 35, to: 40, tone: 'warn' },
      { name: 'obesity class III', from: 40, to: null, tone: 'bad' },
    ];
    const colour: Record<string, string> = {
      ok: 'rgba(27, 175, 122, 0.10)',
      watch: 'rgba(235, 168, 52, 0.10)',
      warn: 'rgba(235, 104, 52, 0.10)',
      bad: 'rgba(214, 62, 62, 0.10)',
    };
    return {
      silent: true,
      label: { show: true, position: 'insideTopLeft', fontSize: 10, opacity: 0.8 },
      data: classes.map(
        (c) =>
          [
            {
              ...(c.from == null ? {} : { yAxis: kg(c.from) }),
              name: this.i18n.t(c.name),
              itemStyle: { color: colour[c.tone] },
            },
            c.to == null ? {} : { yAxis: kg(c.to) },
          ] as NonNullable<NonNullable<ScatterSeriesOption['markArea']>['data']>[number],
      ),
    };
  }

  anyBodyValue(): boolean {
    return Object.values(this.body).some((v) => v != null) || this.bodyFat != null;
  }

  abs(value: number): number {
    return Math.abs(value);
  }

  /**
   * The sessions shown as columns, newest first.
   *
   * The day is resolved in the tenant's zone rather than sliced off the UTC timestamp: a
   * measurement taken late in the evening otherwise lands on the next day (R69).
   */
  readonly bodyColumns = computed(() =>
    this.measurements()
      .slice(0, BODY_COLUMNS)
      .map((m) => ({ m, day: isoDayIn(new Date(m.measured_at), this.format.timezone()) })),
  );

  /**
   * One row per measure across the shown sessions.
   *
   * A tape measure is kept as measures down the side and dates across the top, and with
   * seven measures against two or three sessions that is also the shape that fits a screen.
   * A measure nobody ever taped would be a row of dashes, so it is dropped entirely.
   */
  readonly bodyRows = computed<BodyRow[]>(() => {
    const sessions = this.bodyColumns().map((c) => c.m);
    const sources: { key: string; label: string; unit: string; read: (m: BodyMeasurement) => number | null }[] = [
      ...this.bodyFields.map((f) => ({ key: f.key, label: f.label, unit: 'cm', read: (m: BodyMeasurement) => m[f.key] ?? null })),
      { key: 'body_fat_pct', label: 'Body fat', unit: '%', read: (m: BodyMeasurement) => m.body_fat_pct ?? null },
    ];
    return sources
      .map(({ key, label, unit, read }) => {
        const values = sessions.map(read);
        const [now, before] = values;
        // a gap on either side is not a change of zero, so it stays unanswered
        const change = now != null && before != null ? now - before : null;
        return { key, label, unit, values, change };
      })
      .filter((r) => r.values.some((v) => v != null));
  });

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
        { name: this.i18n.t('Weigh-in'), type: 'scatter', symbolSize: 5, data: daily, itemStyle: { color: CHART_PALETTE[0], opacity: 0.6 }, markArea: this.bmiArea() },
        { name: this.i18n.t('7-day average'), type: 'line', showSymbol: false, smooth: false, data: ma, lineStyle: { width: 2, color: CHART_PALETTE[1] }, itemStyle: { color: CHART_PALETTE[1] } },
      ],
    };
  });

  constructor() {
    this.load();
  }

  addBody(): void {
    if (!this.anyBodyValue()) return;
    this.api
      .addBodyMeasurement({
        measured_at: new Date(this.bodyAt).toISOString(),
        ...this.body,
        body_fat_pct: this.bodyFat,
        note: this.bodyNote.trim() || null,
      })
      .subscribe({
        next: () => {
          for (const key of Object.keys(this.body) as CircumferenceKey[]) this.body[key] = null;
          this.bodyFat = null;
          this.bodyNote = '';
          this.load();
        },
        error: (e: unknown) => this.error.set(describeError(e)),
      });
  }

  removeBody(m: BodyMeasurement): void {
    this.api.deleteBodyMeasurement(m.id).subscribe({
      next: () => this.load(),
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }
  load(): void {
    const to = isoDate(new Date());
    this.api.weight(shiftDate(to, -this.days()), to).subscribe({ next: (w) => this.entries.set(w), error: (e: unknown) => this.error.set(describeError(e)) });
    this.api.bodyMeasurements({ limit: 40 }).subscribe({ next: (m) => this.measurements.set([...m].reverse()), error: () => undefined });
    if (!this.settings()) {
      this.api.settings().subscribe({ next: (v) => this.settings.set(v.data), error: () => undefined });
    }
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
