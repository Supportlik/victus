// T-WEB-004: every block type renders through v-report-block; failed blocks show their message,
// unknown types a placeholder. Fixture shapes mirror src/victus/reports/results.py (render/json.py).
import { TestBed } from '@angular/core/testing';
import { provideEchartsCore } from 'ngx-echarts';
import { ReportBlock } from '../../../api';
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
];

describe('ReportBlockView', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ReportBlockView],
      providers: [provideEchartsCore({ echarts: () => import('echarts') })],
    }).compileComponents();
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
