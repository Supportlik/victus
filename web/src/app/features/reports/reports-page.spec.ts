// T-WEB-403..405: the report dashboard picks a definition and a period ending on the chosen
// day, renders tiles apart from the other blocks, and shows every refusal of the API.
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { provideEchartsCore } from 'ngx-echarts';
import { ReportDefinition, ReportResult } from '../../api';
import { FormatService } from '../../core/format.service';
import { isoDate, shiftDate } from '../../shared/format';
import { ReportsPage } from './reports-page';

const DEFS: ReportDefinition[] = [
  { name: 'weekly', title: 'Weekly', builtin: true, period: { default: '7d', options: ['7d', '14d'] } },
  { name: 'checkup', title: 'Check-up', description: 'How the last weeks went', builtin: true, period: { default: '30d', options: ['7d', '30d', 'custom'] } },
  { name: 'mine', title: 'My report', builtin: false, period: undefined as never },
];

function result(blocks: unknown[]): ReportResult {
  return {
    name: 'checkup',
    title: 'Check-up',
    description: null,
    period: { start: '2026-01-01', end: '2026-01-30', days: 30 },
    today: '2026-01-30',
    generated_at: '2026-01-30T08:00:00Z',
    blocks: blocks as ReportResult['blocks'],
  };
}

const TILE = { meta: { type: 'kpi_tile', id: 'k', title: 'Mean intake' }, error: false, source: 'x', value: 2100, unit: 'kcal', decimals: 0 };
const BROKEN_TILE = { meta: { type: 'kpi_tile', id: 'b', title: 'Broken tile' }, error: true, message: 'no data' };
const FINDING = { meta: { type: 'text_finding', id: 't', title: 'Finding' }, error: false, source: 'agent', markdown: 'All **fine**' };

describe('ReportsPage', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ReportsPage],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideEchartsCore({ echarts: () => import('echarts') })],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  function renderCall(): TestRequest {
    return http.expectOne((r) => r.method === 'POST' && /\/api\/v1\/reports\/[^/]+\/render$/.test(r.url));
  }

  async function open(defs: ReportDefinition[] = DEFS) {
    const fixture = TestBed.createComponent(ReportsPage);
    fixture.detectChanges();
    http.expectOne('/api/v1/reports').flush(defs);
    fixture.detectChanges();
    await fixture.whenStable();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  async function settle(fixture: { detectChanges(): void; whenStable(): Promise<unknown> }) {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  it('T-WEB-403: opens the check-up with its default period ending today and renders tiles apart from blocks', async () => {
    const { fixture, el } = await open();
    const today = isoDate(new Date());
    // loading: the render is in flight
    expect(el.textContent).toContain('Rendering…');
    const req = renderCall();
    expect(req.request.url).toBe('/api/v1/reports/checkup/render');
    expect(req.request.params.get('format')).toBe('json');
    expect(req.request.params.get('to')).toBe(today);
    expect(req.request.params.get('as_of')).toBe(today);
    expect(req.request.params.get('from')).toBe(shiftDate(today, -29)), 'a 30-day window includes its last day';
    req.flush(result([TILE, BROKEN_TILE, FINDING]));
    await settle(fixture);
    http.match((r) => r.url === '/api/v1/reports/snapshots').forEach((r) => r.flush([]));
    await settle(fixture);

    expect(el.querySelector('h2')?.textContent).toBe('Check-up');
    expect(el.querySelector('.sub')?.textContent).toBe('How the last weeks went');
    const options = [...el.querySelectorAll('select')[0].querySelectorAll('option')].map((o) => o.textContent!.trim());
    expect(options).toEqual(['Weekly', 'Check-up', 'My report (custom)']);
    const periods = [...el.querySelectorAll('select')[1].querySelectorAll('option')].map((o) => o.textContent!.trim());
    expect(periods).toEqual(['last 7 days', 'last 30 days', 'Custom range']);
    const format = TestBed.inject(FormatService);
    const line = el.querySelector('p.v-small.v-muted')!.textContent!;
    expect(line).toContain(`${format.day('2026-01-01')} to ${format.day('2026-01-30')} (30 days)`);
    expect(line).toContain(format.moment('2026-01-30T08:00:00Z'));
    expect(el.querySelector('.v-tag.bad')?.textContent).toContain('1 block(s) failed');
    expect(el.querySelectorAll('.tiles v-report-block').length).toBe(1), 'only healthy tiles sit in the tile row';
    expect(el.querySelectorAll('.blocks v-report-block').length).toBe(2), 'the failed tile shows among the blocks';
    expect(el.querySelector('v-snapshot-list')).toBeTruthy();
    expect(el.querySelector('.range')?.classList.contains('shown')).toBe(false);
    http.verify();
  });

  it('T-WEB-403: without a check-up the first report opens; no tiles means no tile row', async () => {
    const { fixture, el } = await open([DEFS[2], DEFS[0]]);
    const req = renderCall();
    expect(req.request.url).toBe('/api/v1/reports/mine/render');
    // a definition without a default period falls back to 14 days
    const today = isoDate(new Date());
    expect(req.request.params.get('from')).toBe(shiftDate(today, -13));
    req.flush(result([FINDING]));
    await settle(fixture);
    http.match((r) => r.url === '/api/v1/reports/snapshots').forEach((r) => r.flush([]));
    await settle(fixture);
    expect(el.querySelector('.tiles')).toBeNull();
    expect(el.querySelector('.v-tag.bad')).toBeNull();
    expect(el.querySelector('.sub')).toBeNull();
    // no options of its own: the standard periods are offered
    const periods = [...el.querySelectorAll('select')[1].querySelectorAll('option')].map((o) => o.getAttribute('value'));
    expect(periods).toEqual(['7d', '14d', '30d', '90d', 'custom']);
  });

  it('T-WEB-403: an empty catalogue renders nothing and keeps the generic title', async () => {
    const { el } = await open([]);
    http.expectNone((r) => r.url.endsWith('/render'));
    expect(el.querySelector('h2')?.textContent).toBe('Reports');
    expect(el.querySelectorAll('select')[0].querySelectorAll('option').length).toBe(0);
  });

  it('T-WEB-404: changing report, period, day and custom range re-renders the matching window', async () => {
    const { fixture, el } = await open();
    renderCall().flush(result([TILE]));
    await settle(fixture);
    http.match((r) => r.url === '/api/v1/reports/snapshots').forEach((r) => r.flush([]));

    // another report from the picker
    const pick = el.querySelectorAll('select')[0] as HTMLSelectElement;
    pick.value = 'weekly';
    pick.dispatchEvent(new Event('change'));
    await settle(fixture);
    const weekly = renderCall();
    expect(weekly.request.url).toBe('/api/v1/reports/weekly/render');
    weekly.flush(result([TILE]));
    await settle(fixture);
    http.match((r) => r.url === '/api/v1/reports/snapshots').forEach((r) => r.flush([]));

    // a day in the past: the whole window moves with it
    const page = fixture.componentInstance;
    page.setPeriod('7d');
    renderCall().flush(result([TILE]));
    page.setAsOf('2026-03-10');
    const moved = renderCall();
    expect(moved.request.params.get('to')).toBe('2026-03-10');
    expect(moved.request.params.get('from')).toBe('2026-03-04');
    expect(moved.request.params.get('as_of')).toBe('2026-03-10');
    moved.flush(result([TILE]));

    // clearing the day goes back to today
    page.setAsOf('');
    const back = renderCall();
    expect(back.request.params.get('as_of')).toBe(isoDate(new Date()));
    back.flush(result([TILE]));

    // a custom range keeps from/to and shows its own row
    page.setPeriod('custom');
    const custom = renderCall();
    expect(custom.request.params.get('to')).toBe(isoDate(new Date()));
    custom.flush(result([TILE]));
    await settle(fixture);
    expect(el.querySelector('.range')?.classList.contains('shown')).toBe(true);
    const [from, to] = [...el.querySelectorAll('.range input')] as HTMLInputElement[];
    from.value = '2026-02-01';
    from.dispatchEvent(new Event('input'));
    const byFrom = renderCall();
    expect(byFrom.request.params.get('from')).toBe('2026-02-01');
    byFrom.flush(result([TILE]));
    to.value = '2026-02-10';
    to.dispatchEvent(new Event('input'));
    const byTo = renderCall();
    expect(byTo.request.params.get('from')).toBe('2026-02-01');
    expect(byTo.request.params.get('to')).toBe('2026-02-10');
    byTo.flush(result([TILE]));
    await settle(fixture);
    http.match((r) => r.url === '/api/v1/reports/snapshots').forEach((r) => r.flush([]));
    http.verify();
  });

  it('T-WEB-405: a catalogue that cannot be read shows the problem instead of "Rendering…"', async () => {
    const fixture = TestBed.createComponent(ReportsPage);
    fixture.detectChanges();
    http.expectOne('/api/v1/reports').flush({ title: 'Unauthorized', detail: 'Sign in again.' }, { status: 401, statusText: 'Unauthorized' });
    await settle(fixture);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.v-error')?.textContent).toContain('Sign in again.');
    expect(el.textContent).not.toContain('Rendering…');
    http.expectNone((r) => r.url.endsWith('/render'));
  });

  it('T-WEB-405: a failed render shows the problem; the next render clears it', async () => {
    const { fixture, el } = await open();
    renderCall().flush({ title: 'Bad Request', detail: 'from must not be after to' }, { status: 400, statusText: 'Bad Request' });
    await settle(fixture);
    expect(el.querySelector('.v-error')?.textContent).toContain('from must not be after to');
    expect(el.querySelector('v-snapshot-list')).toBeNull();
    fixture.componentInstance.setPeriod('7d');
    await settle(fixture);
    expect(el.querySelector('.v-error')).toBeNull();
    expect(el.textContent).toContain('Rendering…');
    renderCall().flush({}, { status: 0, statusText: 'Unknown Error' });
    await settle(fixture);
    expect(el.querySelector('.v-error')?.textContent).toContain('Request failed');
  });
});
