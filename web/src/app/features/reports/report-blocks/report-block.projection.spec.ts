// T-WEB-260 … T-WEB-263: the burndown's pace projections (R85) — one dashed line per window
// that reaches zero, one table row per window, and "not at this pace" for the rest.
// Fixture shapes mirror src/victus/domain/model/reporting.py::ProjectionRow via render/json.py.
import { TestBed } from '@angular/core/testing';
import { provideEchartsCore } from 'ngx-echarts';
import { BurndownBlock, ProjectionRow } from '../../../api';
import { FormatService } from '../../../core/format.service';
import { ReportBlockView } from './report-block';

const stage = (name: string, date: string) => ({
  name, date, planned_remaining_today: 3, gap: 0.4, required_kg_per_week: 0.5,
  required_pct_per_week: 0.55, eat_kcal_per_day: 1900, feasible: true,
  path: [['2026-01-01', 5], [date, 0]] as [string, number][],
});

const projections: ProjectionRow[] = [
  { window: 7, slope_per_day: 0.02, kg_per_week: 0.14, crossing: null, days_vs_goal: null, stages: [], path: [] },
  { window: 14, slope_per_day: -0.05, kg_per_week: -0.35, crossing: '2026-03-20', days_vs_goal: -11,
    stages: [{ name: 'Stretch', date: '2026-03-01', days: 19 }, { name: 'Target', date: '2026-03-31', days: -11 }],
    path: [['2026-01-20', 3], ['2026-03-20', 0]] },
  { window: 30, slope_per_day: -0.03, kg_per_week: -0.21, crossing: '2026-04-30', days_vs_goal: 30,
    stages: [{ name: 'Stretch', date: '2026-03-01', days: 60 }, { name: 'Target', date: '2026-03-31', days: 0 }],
    path: [['2026-01-20', 3], ['2026-03-31', 0.9]] },
];

function burndown(rows: ProjectionRow[] | undefined): BurndownBlock {
  return {
    meta: { type: 'burndown', id: null, title: 'Burndown' }, error: false, goal_kg: 85, goal_date: '2026-03-31',
    result: {
      anchor: '2026-01-01', remaining_at_anchor: 5, remaining_today: 3, planned_remaining_today: 3.4, gap: 0.4,
      burned: 2, days_elapsed: 19, actual_rate_per_week: 0.7, planned_rate_per_week: 0.39, required_rate_per_week: 0.36,
      target_path: [['2026-01-01', 5], ['2026-03-31', 0]], actual: [['2026-01-01', 5], ['2026-01-20', 3]],
      stages: [stage('Stretch', '2026-03-01'), stage('Target', '2026-03-31')],
      ...(rows === undefined ? {} : { projections: rows }),
    },
  } as BurndownBlock;
}

describe('ReportBlockView burndown projections', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ReportBlockView],
      providers: [provideEchartsCore({ echarts: () => import('echarts') })],
    }).compileComponents();
    TestBed.inject(FormatService).adopt('en-GB', 'Europe/London');
  });

  async function mount(block: BurndownBlock) {
    const fixture = TestBed.createComponent(ReportBlockView);
    fixture.componentRef.setInput('block', block);
    await fixture.whenStable();
    return { el: fixture.nativeElement as HTMLElement, view: fixture.componentInstance };
  }

  type Line = { name: string; data: [string, number][]; lineStyle: { type: unknown }; endLabel?: { show: boolean; formatter: string } };

  it('draws one dashed, labelled line per window that reaches zero, none for "not at this pace"', async () => {
    // T-WEB-260
    const { view } = await mount(burndown(projections));
    const series = view.burndownChart().series as Line[];
    const paces = series.filter((s) => s.name.endsWith('-day pace'));
    expect(paces.map((s) => s.name)).toEqual(['14-day pace', '30-day pace']);
    expect(paces[0].data).toEqual(projections[1].path);
    expect(paces[1].data).toEqual(projections[2].path);
    for (const p of paces) {
      // dashed, and not the dotted style of the planned stage lines
      expect(Array.isArray(p.lineStyle.type)).toBe(true);
      expect(p.endLabel?.show).toBe(true);
      expect(p.endLabel?.formatter).toBe(p.name);
    }
    const stageLines = series.filter((s) => s.name === 'Stretch' || s.name === 'Target');
    expect(stageLines.every((s) => s.lineStyle.type === 'dotted')).toBe(true);
  });

  it('lists every window with rate, zero day and early/late per date', async () => {
    // T-WEB-261
    const { el } = await mount(burndown(projections));
    const head = [...el.querySelectorAll('.projections thead th')].map((th) => th.textContent?.trim());
    expect(head).toEqual(['Pace', 'kg / week', 'reaches zero', 'vs. goal', 'vs. Stretch', 'vs. Target']);
    const rows = [...el.querySelectorAll('.projections tbody tr')].map((tr) =>
      [...tr.querySelectorAll('td')].map((td) => td.textContent?.trim()),
    );
    expect(rows).toEqual([
      ['7-day pace', '+0.14', 'not at this pace', '–', '–', '–'],
      ['14-day pace', '-0.35', '2026-03-20', '11 d early', '19 d late', '11 d early'],
      ['30-day pace', '-0.21', '2026-04-30', '30 d late', '60 d late', 'on time'],
    ]);
    expect(el.querySelector('.projections tbody tr.no-crossing')?.textContent).toContain('7-day pace');
  });

  it('shows neither table nor lines when projections are off or the snapshot predates them', async () => {
    // T-WEB-262
    for (const rows of [[], undefined]) {
      const { el, view } = await mount(burndown(rows));
      expect(el.querySelector('.projections')).toBeNull();
      expect(el.querySelector('.stages tbody tr')).not.toBeNull();
      const names = (view.burndownChart().series as Line[]).map((s) => s.name);
      expect(names.some((n) => n.endsWith('-day pace'))).toBe(false);
    }
  });

  it('reads a pace line in the tooltip as a weight to go, not as a plan to beat', async () => {
    // T-WEB-263
    const { view } = await mount(burndown(projections));
    const html = view.burndownTooltip(
      [
        { seriesName: 'Actual (7-day avg.)', value: ['2026-01-20', 3], dataIndex: 1 },
        { seriesName: '14-day pace', value: ['2026-01-20', 3] },
        { seriesName: 'Target', value: ['2026-01-20', 3.4] },
      ],
      burndown(projections),
    );
    expect(html).toContain('14-day pace: 88.0 kg · 3.0 kg to go');
    expect(html).not.toContain('14-day pace: plan');
    expect(html).toContain('Target: plan 88.4 kg');
    expect(view.earlyLate(null)).toBe('–');
    expect(view.earlyLate(0)).toBe('on time');
    expect(view.earlyLate(-4)).toBe('4 d early');
    expect(view.earlyLate(9)).toBe('9 d late');
  });
});
