// T-WEB-406..410: report snapshots ("moments") are listed, opened, frozen, annotated and
// deleted; every call shows its loading, empty and error state.
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideEchartsCore } from 'ngx-echarts';
import { ReportSnapshot } from '../../api';
import { FormatService } from '../../core/format.service';
import { SnapshotList } from './snapshot-list';

const FROZEN: ReportSnapshot = {
  id: 'snap-a', report_name: 'checkup', title: 'Check-up', label: null, period_start: '2026-01-01', period_end: '2026-01-14',
  today: '2026-01-14', status: 'frozen', created_at: '2026-01-14T08:00:00Z',
};
const ASSESSED: ReportSnapshot = {
  id: 'snap-b', report_name: 'checkup', title: 'Check-up', label: 'Before the holidays', period_start: '2025-12-01', period_end: '2025-12-14',
  today: '2025-12-14', status: 'assessed', created_at: '2025-12-14T08:00:00Z',
};
const FAILED: ReportSnapshot = { ...FROZEN, id: 'snap-c', status: 'failed' };

const TILE = { meta: { type: 'kpi_tile', id: 'k', title: 'Mean intake' }, error: false, source: 'x', value: 2100, unit: 'kcal', decimals: 0 };

type Fixture = ReturnType<typeof TestBed.createComponent<SnapshotList>>;

describe('SnapshotList', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SnapshotList],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideEchartsCore({ echarts: () => import('echarts') })],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  async function settle(f: Fixture) {
    f.detectChanges();
    await f.whenStable();
    f.detectChanges();
  }

  async function render(list: ReportSnapshot[] = [FROZEN, ASSESSED, FAILED]) {
    const fixture = TestBed.createComponent(SnapshotList);
    fixture.componentRef.setInput('report', 'checkup');
    fixture.componentRef.setInput('from', '2026-01-01');
    fixture.componentRef.setInput('to', '2026-01-14');
    fixture.componentRef.setInput('asOf', '2026-01-14');
    fixture.detectChanges();
    const req = http.expectOne((r) => r.url === '/api/v1/reports/snapshots');
    expect(req.request.params.get('report')).toBe('checkup');
    expect(req.request.params.get('limit')).toBe('50');
    req.flush(list);
    await settle(fixture);
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  function row(el: HTMLElement, id: string): HTMLElement {
    return el.querySelector(`[data-snapshot="${id}"]`) as HTMLElement;
  }

  async function openDetail(f: Fixture, el: HTMLElement, id: string, detail: ReportSnapshot) {
    (row(el, id).querySelector('button.row') as HTMLButtonElement).click();
    await settle(f);
    expect(row(el, id).querySelector('.detail')?.textContent).toContain('Loading…');
    http.expectOne(`/api/v1/reports/snapshots/${id}`).flush(detail);
    await settle(f);
  }

  it('T-WEB-406: lists moments with label or title, period and status tag', async () => {
    const { el } = await render();
    const format = TestBed.inject(FormatService);
    expect(el.querySelectorAll('li[data-snapshot]').length).toBe(3);
    const frozen = row(el, 'snap-a');
    expect(frozen.querySelector('.when')?.textContent).toBe('2026-01-14');
    expect(frozen.querySelector('.what')?.textContent).toContain('Check-up');
    expect(frozen.querySelector('.what')?.textContent).toContain(`${format.day('2026-01-01')} → ${format.day('2026-01-14')}`);
    expect(frozen.querySelector('.v-tag')?.textContent).toBe('no assessment yet');
    expect(frozen.querySelector('.v-tag')?.classList.contains('warn')).toBe(true);
    expect(frozen.querySelector('.chev')?.textContent).toBe('▸');
    expect(row(el, 'snap-b').querySelector('.what')?.textContent).toContain('Before the holidays');
    expect(row(el, 'snap-b').querySelector('.v-tag')?.classList.contains('closed')).toBe(true);
    expect(row(el, 'snap-c').querySelector('.v-tag')?.textContent).toBe('failed');
    expect(row(el, 'snap-c').querySelector('.v-tag')?.classList.contains('bad')).toBe(true);
  });

  it('T-WEB-406: an empty list invites freezing; a list that cannot be read shows the problem', async () => {
    const { el } = await render([]);
    expect(el.querySelector('li.empty')?.textContent).toContain('No moments yet.');

    const f2 = TestBed.createComponent(SnapshotList);
    f2.componentRef.setInput('report', 'weekly');
    f2.detectChanges();
    http.expectOne((r) => r.url === '/api/v1/reports/snapshots').flush({ detail: 'Missing scope reports:read' }, { status: 403, statusText: 'Forbidden' });
    await settle(f2);
    expect((f2.nativeElement as HTMLElement).querySelector('.v-error')?.textContent).toContain('Missing scope reports:read');
  });

  it('T-WEB-406: loads again only when the report changes', async () => {
    const { fixture } = await render();
    fixture.componentRef.setInput('from', '2026-01-02');
    await settle(fixture);
    http.expectNone((r) => r.url === '/api/v1/reports/snapshots');
    fixture.componentRef.setInput('report', 'weekly');
    await settle(fixture);
    const req = http.expectOne((r) => r.url === '/api/v1/reports/snapshots');
    expect(req.request.params.get('report')).toBe('weekly');
    req.flush([]);
  });

  it('T-WEB-407: opening a moment loads it and shows the assessment with model and cost; clicking again closes it', async () => {
    const { fixture, el } = await render();
    await openDetail(fixture, el, 'snap-b', {
      ...ASSESSED, assessment_md: '## Steady\n\nIntake was **even**.', model: 'claude-opus-5', cost_usd: 0.123,
      result: { blocks: [TILE] },
    });
    const detail = row(el, 'snap-b').querySelector('.detail')!;
    expect(row(el, 'snap-b').classList.contains('open')).toBe(true);
    expect(row(el, 'snap-b').querySelector('.chev')?.textContent).toBe('▾');
    expect(detail.querySelector('.assessment h4')?.textContent).toContain('claude-opus-5 · 0.12 USD');
    expect(detail.querySelector('.v-md h2')?.textContent).toBe('Steady');
    expect(detail.querySelector('.v-md strong')?.textContent).toBe('even');
    expect(detail.querySelectorAll('.numbers v-report-block').length).toBe(1);
    expect(detail.querySelector('form.own')).toBeNull();

    (row(el, 'snap-b').querySelector('button.row') as HTMLButtonElement).click();
    await settle(fixture);
    expect(row(el, 'snap-b').querySelector('.detail')).toBeNull();
    http.expectNone('/api/v1/reports/snapshots/snap-b');
  });

  it('T-WEB-407: an assessment without model or cost, and a moment without frozen numbers', async () => {
    const { fixture, el } = await render();
    await openDetail(fixture, el, 'snap-b', { ...ASSESSED, assessment_md: 'Fine.', model: 'claude-opus-5', cost_usd: 0 });
    expect(row(el, 'snap-b').querySelector('.assessment h4')?.textContent).not.toContain('USD');
    expect(row(el, 'snap-b').querySelector('.numbers .blocks')).toBeNull();
    await openDetail(fixture, el, 'snap-c', { ...FAILED, assessment_md: 'Plain.', result: {} });
    expect(row(el, 'snap-c').querySelector('.assessment h4 .v-small')).toBeNull();
    expect(row(el, 'snap-c').querySelector('.numbers .blocks v-report-block')).toBeNull(), 'a result without blocks shows none';
    expect(row(el, 'snap-b').querySelector('.detail')).toBeNull(), 'only one moment is open at a time';
  });

  it('T-WEB-407: a moment that cannot be loaded shows the problem', async () => {
    const { fixture, el } = await render();
    (row(el, 'snap-a').querySelector('button.row') as HTMLButtonElement).click();
    http.expectOne('/api/v1/reports/snapshots/snap-a').flush({ title: 'Not Found' }, { status: 404, statusText: 'Not Found' });
    await settle(fixture);
    expect(el.querySelector('.v-error')?.textContent).toContain('Not Found');
  });

  it('T-WEB-408: freezing posts the period, disables the button while busy and puts the new moment first', async () => {
    const { fixture, el } = await render([ASSESSED]);
    const created: ReportSnapshot[] = [];
    fixture.componentInstance.created.subscribe((s) => created.push(s));
    const button = el.querySelector('header button.primary') as HTMLButtonElement;
    expect(button.textContent).toContain('Freeze this period');
    button.click();
    await settle(fixture);
    expect(button.disabled).toBe(true);
    expect(button.textContent).toContain('Freezing…');
    const req = http.expectOne((r) => r.url === '/api/v1/reports/checkup/snapshots');
    expect(req.request.method).toBe('POST');
    expect(req.request.params.get('from')).toBe('2026-01-01');
    expect(req.request.params.get('to')).toBe('2026-01-14');
    expect(req.request.params.get('as_of')).toBe('2026-01-14');
    req.flush(FROZEN);
    await settle(fixture);
    expect(button.disabled).toBe(false);
    expect(el.querySelector('.v-notice')?.textContent).toContain('Frozen. Ask the agent for its assessment');
    expect(el.querySelectorAll('li[data-snapshot]')[0].getAttribute('data-snapshot')).toBe('snap-a');
    expect(created).toEqual([FROZEN]);
  });

  it('T-WEB-408: a refused freeze shows the problem and frees the button', async () => {
    const { fixture, el } = await render([]);
    fixture.componentInstance.freeze();
    http.expectOne((r) => r.url === '/api/v1/reports/checkup/snapshots').flush(
      { detail: 'A moment for this period exists already.' }, { status: 409, statusText: 'Conflict' },
    );
    await settle(fixture);
    expect(el.querySelector('.v-error')?.textContent).toContain('A moment for this period exists already.');
    expect(el.querySelector('.v-notice')).toBeNull();
    expect((el.querySelector('header button.primary') as HTMLButtonElement).disabled).toBe(false);
    expect(el.querySelector('li.empty')).toBeTruthy();
  });

  it('T-WEB-409: a moment without assessment takes an own note; it is saved and the moment reads assessed', async () => {
    const { fixture, el } = await render();
    await openDetail(fixture, el, 'snap-a', { ...FROZEN, result: { blocks: [TILE] } });
    const form = row(el, 'snap-a').querySelector('form.own') as HTMLFormElement;
    expect(row(el, 'snap-a').textContent).toContain('report_assess');
    const save = form.querySelector('button[type=submit]') as HTMLButtonElement;
    expect(save.disabled).toBe(true), 'nothing typed, nothing to save';

    // whitespace only is not a note
    const area = form.querySelector('textarea') as HTMLTextAreaElement;
    area.value = '   ';
    area.dispatchEvent(new Event('input'));
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    http.expectNone('/api/v1/reports/snapshots/snap-a/assess');

    area.value = '  Held steady.  ';
    area.dispatchEvent(new Event('input'));
    await settle(fixture);
    expect(save.disabled).toBe(false);
    const submit = new Event('submit', { cancelable: true });
    form.dispatchEvent(submit);
    expect(submit.defaultPrevented).toBe(true);
    const req = http.expectOne('/api/v1/reports/snapshots/snap-a/assess');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ markdown: 'Held steady.' });
    req.flush({ ...FROZEN, status: 'assessed', assessment_md: 'Held steady.' });
    await settle(fixture);
    expect(row(el, 'snap-a').querySelector('.v-md')?.textContent).toContain('Held steady.');
    expect(row(el, 'snap-a').querySelector('.v-tag')?.textContent).toBe('assessed');
    expect(row(el, 'snap-a').querySelectorAll('.numbers v-report-block').length).toBe(1), 'the frozen numbers stay';
    expect(fixture.componentInstance.ownText).toBe('');
  });

  it('T-WEB-409: a refused note shows the problem and keeps the text', async () => {
    const { fixture, el } = await render();
    await openDetail(fixture, el, 'snap-a', FROZEN);
    fixture.componentInstance.ownText = 'Mine';
    const form = row(el, 'snap-a').querySelector('form.own') as HTMLFormElement;
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    http.expectOne('/api/v1/reports/snapshots/snap-a/assess').flush({ detail: 'Already assessed.' }, { status: 409, statusText: 'Conflict' });
    await settle(fixture);
    expect(el.querySelector('.v-error')?.textContent).toContain('Already assessed.');
    expect(fixture.componentInstance.ownText).toBe('Mine');
    expect(fixture.componentInstance.busy()).toBe(false);
  });

  it('T-WEB-410: deleting asks first; "No" keeps it, "Yes" deletes and closes it', async () => {
    const { fixture, el } = await render();
    await openDetail(fixture, el, 'snap-b', { ...ASSESSED, assessment_md: 'x' });
    const actions = () => row(el, 'snap-b').querySelector('.detail .v-actions') as HTMLElement;
    const button = (text: string) => [...actions().querySelectorAll('button')].find((b) => b.textContent?.trim() === text) as HTMLButtonElement;
    button('Delete').click();
    await settle(fixture);
    expect(actions().textContent).toContain('Delete this moment?');
    http.expectNone('/api/v1/reports/snapshots/snap-b');
    button('No').click();
    await settle(fixture);
    expect(actions().textContent).not.toContain('Delete this moment?');
    button('Delete').click();
    await settle(fixture);
    button('Yes').click();
    const req = http.expectOne('/api/v1/reports/snapshots/snap-b');
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
    await settle(fixture);
    expect(row(el, 'snap-b')).toBeNull();
    expect(fixture.componentInstance.open()).toBeNull();
    expect(el.querySelectorAll('li[data-snapshot]').length).toBe(2);
  });

  it('T-WEB-410: a refused delete shows the problem and keeps the moment', async () => {
    const { fixture, el } = await render();
    await openDetail(fixture, el, 'snap-b', { ...ASSESSED, assessment_md: 'x' });
    fixture.componentInstance.remove(ASSESSED);
    http.expectOne('/api/v1/reports/snapshots/snap-b').flush({ detail: 'Missing scope reports:write' }, { status: 403, statusText: 'Forbidden' });
    await settle(fixture);
    expect(el.querySelector('.v-error')?.textContent).toContain('Missing scope reports:write');
    expect(row(el, 'snap-b')).toBeTruthy();
    expect(row(el, 'snap-b').querySelector('.detail')).toBeTruthy();
  });
});
