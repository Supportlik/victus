// T-WEB-004: every block type renders through v-report-block; failed blocks show their message,
// unknown types a placeholder. Fixture shapes mirror src/victus/reports/results.py (render/json.py).
import { TestBed } from '@angular/core/testing';
import { provideEchartsCore } from 'ngx-echarts';
import { ReportBlock } from '../../../api';
import { FormatService } from '../../../core/format.service';
import { ReportBlockView } from './report-block';

const meta = (type: string, title: string) => ({ type, id: null, title });
const stat = { below_min: 1, below_optimum: 2, optimal: 9, above_optimum: 1, above_max: 1, mean: 158.2, n: 14 };
const band = { min: 105, opt_min: 150, opt_max: 185, target: 165, max: 200 };

const blocks: ReportBlock[] = [
  { meta: meta('kpi_tile', 'Weight (MA7)'), error: false, source: 'weight.ma7', value: 86.4, unit: 'kg', decimals: 1, delta: -0.6, quality: 'green' },
  { meta: meta('band_distribution', 'Days in band'), error: false, rows: [{ macro: 'protein', stat, band, days_rated: 14 }] },
  { meta: meta('tdee_windows', 'Energy expenditure'), error: false, show_quality: true, reference_tdee: 2410, reference_basis: 'rolling 14 d',
    rows: [{ window_days: 14, start: '2026-01-01', end: '2026-01-14', mean_kcal: 1810, delta_ma_kg: -1.1, tdee: 2410, rejected_tdee: null, coverage_pct: 86, days_with_kcal: 12, measured_days: 13, days_without_macros: 1, in_corridor: 10, above_corridor: 2, below_corridor: 0, mean_protein: 155, quality: 'green' }] },
  { meta: meta('trend', 'Trend'), error: false, rows: [{ window: 14, slope_per_day: -0.081, kg_per_week: -0.57, actual_delta: -1.1, start: '2026-01-01', end: '2026-01-14', points: 14, measured_days: 13 }] },
  { meta: meta('forecast', 'Forecast'), error: false, horizons: ['1m', '3m', '6m'], with_eta: true, current_kg: 86.4, goal_kg: 85, goal_date: '2027-03-31',
    rows: [{ window: 14, kg_per_week: -0.57, m1: 84.6, m3: 79.9, m6: 72.8, at_goal_date: 70.1, eta: '2026-12-01' }] },
  { meta: meta('burndown', 'Burndown'), error: false, goal_kg: 85, goal_date: '2027-03-31',
    result: { anchor: '2026-01-01', remaining_at_anchor: 5, remaining_today: 1.4, planned_remaining_today: 1.8, gap: 0.4, burned: 3.6, days_elapsed: 20, actual_rate_per_week: -0.5, planned_rate_per_week: -0.45, required_rate_per_week: -0.5,
      target_path: [['2026-01-01', 90], ['2026-03-01', 85]], actual: [['2026-01-01', 90.2], ['2026-01-20', 88.7]],
      stages: [{ name: 'Target', date: '2027-03-31', planned_remaining_today: 1.8, gap: 0.4, required_kg_per_week: -0.5, required_pct_per_week: -0.55, eat_kcal_per_day: 1900, feasible: true }] } },
  { meta: meta('weekly_chart', 'Weeks'), error: false, series: ['mean_kcal', 'tdee', 'mean_kg'], rows: [{ week_start: '2026-01-05', mean_kg: 89.1, delta_kg: -0.4, mean_kcal: 1900, days_with_kcal: 6, tdee: 2500 }] },
  { meta: meta('day_list', 'Days'), error: false, columns: ['kcal', 'protein', 'weight', 'status'],
    rows: [{ date: '2026-01-05', macros: { kcal: 1800, protein: 150 }, weight: 89.1, training_type: null, status: 'closed', reliable: true, countable: true }] },
  { meta: meta('text_finding', 'Agent finding'), error: false, source: 'agent', markdown: '**On track.** Protein average 158 g.' },
  { meta: meta('histogram_3d', 'Something new'), error: false } as unknown as ReportBlock,
  { meta: meta('tdee_windows', 'Energy expenditure'), error: true, message: 'no weigh-ins in period' },
  { meta: meta('body_composition', 'Body'), error: false, weight_kg: 100.0, height_cm: 180,
    bmi: { value: 30.86, unit: '', band: 'obesity class I', tone: 'warn', to_next: 0.86,
      bands: [
        { name: 'underweight', lower: null, upper: 18.5, tone: 'warn' },
        { name: 'normal weight', lower: 18.5, upper: 25, tone: 'ok' },
        { name: 'overweight', lower: 25, upper: 30, tone: 'watch' },
        { name: 'obesity class I', lower: 30, upper: 35, tone: 'warn' },
        { name: 'obesity class III', lower: 40, upper: null, tone: 'bad' },
      ] },
    bmi_weight_bands: [
      { name: 'normal weight', lower: 18.5, upper: 25, tone: 'ok', lower_kg: 59.9, upper_kg: 81.0, to_reach_kg: -19.0 },
      { name: 'overweight', lower: 25, upper: 30, tone: 'watch', lower_kg: 81.0, upper_kg: 97.2, to_reach_kg: -2.8 },
      { name: 'obesity class I', lower: 30, upper: 35, tone: 'warn', lower_kg: 97.2, upper_kg: 113.4, to_reach_kg: null },
    ],
    waist_to_height: null, waist_to_hip: null, measured_at: '2026-01-05',
    circumferences: { waist_cm: 96, hip_cm: 108 }, changes: { waist_cm: -4 },
    body_fat_pct: null, missing: ['no waist measurement'] },
  { meta: meta('energy_split', 'Where the energy goes'), error: false, tdee_kcal: 2800,
    basal_kcal: 1750, activity_kcal: 1050, pal: 1.6, age_years: 36, basis: 'rolling_14d',
    caveat: null, missing: [] },
  { meta: meta('timeline', 'One time axis'), error: false, tdee_window: 14, goal_kg: 85, kcal_min: 1700, kcal_max: 2300,
    rows: [
      { date: '2026-01-05', weight: 89.1, weight_ma: 89.4, countable: true, tdee: 2500, kcal: 1900, protein: 150, carbs: 180, fat: 70, fiber: 32, salt: 6 },
      { date: '2026-01-06', weight: null, weight_ma: 89.2, countable: false, tdee: 2490, kcal: null, protein: null, carbs: null, fat: null, fiber: null, salt: null },
    ] },
];

describe('ReportBlockView', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ReportBlockView],
      providers: [provideEchartsCore({ echarts: () => import('echarts') })],
    }).compileComponents();
  });

  beforeEach(() => {
    // the formatters read the mirrored locale, so pin it rather than inheriting a default
    TestBed.inject(FormatService).adopt('en-GB', 'Europe/London');
  });

  async function render(block: ReportBlock): Promise<HTMLElement> {
    const fixture = TestBed.createComponent(ReportBlockView);
    fixture.componentRef.setInput('block', block);
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  }

  it('renders a kpi tile with value, unit and tone from quality', async () => {
    const el = await render(blocks[0]);
    expect(el.querySelector('.tile.ok')).not.toBeNull();
    expect(el.textContent).toContain('86.4');
    expect(el.textContent).toContain('Weight (MA7)');
  });

  it('renders each tabular block with its rows', async () => {
    const dist = await render(blocks[1]);
    expect(dist.querySelectorAll('tbody tr').length).toBe(1);
    expect(dist.textContent).toContain('158.2');
    const tdee = await render(blocks[2]);
    expect(tdee.textContent).toContain('2,410');
    expect(tdee.querySelector('.v-tag.ok')?.textContent).toContain('reliable');
    expect((await render(blocks[3])).textContent).toContain('-0.57');
    expect((await render(blocks[4])).textContent).toContain('2026-12-01');
    const days = await render(blocks[7]);
    expect(days.querySelectorAll('thead th').length).toBe(5);
    expect(days.querySelector('v-status-tag')?.textContent).toContain('Closed');
  });

  it('renders charts as echarts hosts and the burndown stage table', async () => {
    const bd = await render(blocks[5]);
    expect(bd.querySelector('[echarts]')).not.toBeNull();
    expect(bd.querySelector('.stages tbody tr')?.textContent).toContain('Target');
    expect((await render(blocks[6])).querySelector('[echarts]')).not.toBeNull();
  });

  it('renders markdown findings as HTML', async () => {
    const el = await render(blocks[8]);
    expect(el.querySelector('.v-md strong')?.textContent).toBe('On track.');
  });

  // T-WEB-034: the three timeline panels share one day, so the tooltip must read the same
  // from any of them: weight, then intake, then TDEE.
  it('builds the timeline tooltip in a fixed order, whatever panel is hovered', async () => {
    const timeline = blocks.find((b) => b.meta.type === 'timeline')!;
    const fixture = TestBed.createComponent(ReportBlockView);
    fixture.componentRef.setInput('block', timeline);
    await fixture.whenStable();

    // ECharts hands over whichever series sit under the pointer; only the day matters
    const fromWeightPanel = fixture.componentInstance.timelineTooltip([
      { axisValue: '2026-01-05', seriesName: 'Weight (7-day avg.)' },
    ]);
    const fromMacroPanel = fixture.componentInstance.timelineTooltip([
      { axisValue: '2026-01-05', seriesName: 'Fat' },
      { axisValue: '2026-01-05', seriesName: 'Protein' },
    ]);
    expect(fromMacroPanel).toBe(fromWeightPanel);
    expect(fromWeightPanel.indexOf('Weight')).toBeLessThan(fromWeightPanel.indexOf('Intake'));
    expect(fromWeightPanel.indexOf('Intake')).toBeLessThan(fromWeightPanel.indexOf('TDEE'));
    expect(fromWeightPanel).toContain('TDEE (14 d)');
    expect(fromWeightPanel).toContain('Protein 150 g');
    // T-WEB-034: the trend and the reading on the scale are two different numbers
    expect(fromWeightPanel).toContain('Weight (7-day avg.)');
    expect(fromWeightPanel).toContain('89.4');
    expect(fromWeightPanel).toContain('Weigh-in');
    expect(fromWeightPanel).toContain('89.1');

    // a day without intake keeps the order and simply drops the missing lines
    const thin = fixture.componentInstance.timelineTooltip([{ axisValue: '2026-01-06' }]);
    expect(thin).toContain('not counted');
    expect(thin).not.toContain('Intake');
    expect(thin).not.toContain('Weigh-in');  // no reading that day, only the trend
    expect(thin).toContain('TDEE');
  });

  // T-WEB-038: numbers follow the tenant's locale, so a European reader sees 1.234,5 (R69).
  it('writes the tooltip numbers in the configured locale', async () => {
    const timeline = blocks.find((b) => b.meta.type === 'timeline')!;
    const format = TestBed.inject(FormatService);
    const fixture = TestBed.createComponent(ReportBlockView);
    fixture.componentRef.setInput('block', timeline);
    await fixture.whenStable();

    format.adopt('de-DE', 'Europe/Berlin');
    const german = fixture.componentInstance.timelineTooltip([{ axisValue: '2026-01-05' }]);
    expect(german).toContain('89,4');
    expect(german).toContain('1.900');

    format.adopt('en-GB', 'Europe/London');
    const english = fixture.componentInstance.timelineTooltip([{ axisValue: '2026-01-05' }]);
    expect(english).toContain('89.4');
    expect(english).toContain('1,900');
  });

  // T-WEB-042: a class is only useful with the scale around it, so the block draws the
  // whole range, marks the class the value sits in and pins the value itself (R76).
  it('draws the BMI scale, the kilogram classes and the circumference changes', async () => {
    const el = await render(blocks.find((b) => b.meta.type === 'body_composition')!);
    expect(el.textContent).toContain('BMI');
    expect(el.textContent).toContain('obesity class I');
    expect(el.textContent).toContain('to the next class');

    // one segment per class, each coloured by what its class means, and the pin inside the
    // bar — the pin is what marks the current class, the segments are not highlighted
    const segments = el.querySelectorAll('.scale .seg');
    expect(segments.length).toBe(5);
    const classes = [...segments].map((s) => s.getAttribute('class') ?? '').join(' ');
    expect(classes).toContain('t-ok');
    expect(classes).toContain('t-bad');
    const left = Number((el.querySelector('.scale .pin') as HTMLElement).style.left.replace('%', ''));
    expect(left).toBeGreaterThan(0);
    expect(left).toBeLessThan(100);

    // the classes as kilograms, with the one the weight falls in highlighted. The row is
    // found by weight against the kilogram edges: comparing 100 kg to a BMI of 18.5 put
    // every reader in whichever class has no upper bound.
    expect(el.querySelectorAll('.marks tr.here').length).toBe(1);
    expect(el.querySelector('.marks tr.here')?.textContent).toContain('obesity class I');
    // both scales are readable as themselves, and the distance is in kilograms
    const here = el.querySelector('.marks tr.here')!;
    expect(here.textContent).toContain('30.0–35.0');
    expect(here.textContent).toContain('97.2–113.4');
    expect(here.textContent).toContain('you are here');
    expect([...el.querySelectorAll('.marks tbody tr')][1].textContent).toContain('2.8 kg');
    // a shrinking waist reads as an improvement
    expect(el.querySelector('.circ .down')?.textContent).toContain('4');
    expect(el.textContent).toContain('Not shown: no waist measurement');
  });

  it('splits the expenditure into resting and moving', async () => {
    const el = await render(blocks.find((b) => b.meta.type === 'energy_split')!);
    expect(el.textContent).toContain('At rest');
    expect(el.textContent).toContain('From moving');
    expect(el.textContent).toContain('1.60');
    expect(el.querySelector('.split .rest')).not.toBeNull();
    expect(el.querySelector('.warn-text')).toBeNull();
  });

  it('shows a placeholder for unknown block types', async () => {
    const el = await render(blocks[9]);
    expect(el.textContent).toContain('histogram_3d');
    expect(el.textContent).toContain('not supported');
  });

  it('shows the message of a failed block instead of breaking', async () => {
    const el = await render(blocks[10]);
    expect(el.querySelector('.failed')).not.toBeNull();
    expect(el.textContent).toContain('no weigh-ins in period');
  });
});
