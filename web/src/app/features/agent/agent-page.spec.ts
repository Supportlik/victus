// T-WEB-031: agent page lists runs, shows a run's sessions and summary, cancels an active run,
// and releases a lock only after inline confirmation.
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { AgentLock, AgentRun } from '../../api';
import { FormatService } from '../../core/format.service';
import { AgentPage } from './agent-page';

const runs: AgentRun[] = [
  {
    id: 'run_aaaaaaaa1', runner: 'worker', mode: 'historical', status: 'finished', created_at: '2026-01-05T08:00:00Z',
    started_at: '2026-01-05T08:00:02Z', finished_at: '2026-01-05T08:01:40Z', days: ['2026-01-04'],
    input_tokens: 12000, output_tokens: 800, cost_usd: 0.08, model: 'claude-opus-5', summary_md: '## Drafts 2026-01-04',
    sessions: [{ date: '2026-01-04', model: 'claude-opus-5', input_tokens: 12000, output_tokens: 800, cost_usd: 0.08, outcome: 'drafted', started_at: null, finished_at: null }],
  },
  { id: 'run_bbbbbbbb2', runner: 'external', mode: 'follow_up', status: 'running', started_at: '2026-01-05T09:00:00Z', finished_at: null, days: ['2026-01-05'] },
];
const locks: AgentLock[] = [{ date: '2026-01-05', runner: 'external', run_id: 'run_bbbbbbbb2', locked_until: '2026-01-05T09:05:00Z' }];

function buttonWithText(root: Element, text: string): HTMLButtonElement {
  const found = Array.from(root.querySelectorAll('button')).find((b) => b.textContent?.includes(text));
  if (!found) throw new Error(`no button containing "${text}"`);
  return found;
}

describe('AgentPage', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AgentPage],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
  });

  async function render() {
    const fixture = TestBed.createComponent(AgentPage);
    await fixture.whenStable();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne((r) => r.url === '/api/v1/agent/runs').flush(runs);
    http.expectOne('/api/v1/agent/locks').flush(locks);
    await fixture.whenStable();
    return { fixture, http, el: fixture.nativeElement as HTMLElement };
  }

  it('lists runs with status, tokens and cost, and the locked days', async () => {
    const { el } = await render();
    const rows = el.querySelectorAll('table.runs tbody tr');
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain('finished');
    expect(rows[0].textContent).toContain('12,800');
    // the cost follows the tenant's number format, not a fixed English one
    expect(rows[0].textContent).toContain(`${TestBed.inject(FormatService).number(0.08, 2)} USD`);
    expect(rows[1].textContent).toContain('external');
    expect(el.querySelector('[data-lock="2026-01-05"]')?.textContent).toContain('external');
  });

  it('shows sessions and the summary for a selected run', async () => {
    const { fixture, http, el } = await render();
    buttonWithText(el.querySelector('[data-run="run_aaaaaaaa1"]')!, 'Details').click();
    http.expectOne('/api/v1/agent/runs/run_aaaaaaaa1').flush(runs[0]);
    await fixture.whenStable();
    expect(el.querySelector('.detail')?.textContent).toContain('Sessions (one per day)');
    expect(el.querySelector('.detail table.sessions tbody')?.textContent).toContain('drafted');
    expect(el.querySelector('.detail .summary h2')?.textContent).toContain('Drafts 2026-01-04');
  });

  it('cancels an active run', async () => {
    const { fixture, http, el } = await render();
    buttonWithText(el.querySelector('[data-run="run_bbbbbbbb2"]')!, 'Cancel').click();
    const req = http.expectOne('/api/v1/agent/runs/run_bbbbbbbb2/cancel');
    expect(req.request.method).toBe('POST');
    req.flush({ ...runs[1], status: 'cancelled' });
    http.expectOne('/api/v1/agent/locks').flush([]);
    await fixture.whenStable();
    expect(el.querySelector('[data-run="run_bbbbbbbb2"]')?.textContent).toContain('cancelled');
  });

  it('releases a lock only after confirmation', async () => {
    const { fixture, http, el } = await render();
    const row = el.querySelector('[data-lock="2026-01-05"]')!;
    buttonWithText(row, 'Force unlock').click();
    await fixture.whenStable();
    http.expectNone('/api/v1/agent/locks/2026-01-05');
    expect(row.querySelector('.confirm')?.textContent).toContain('Release?');
    buttonWithText(row, 'Yes').click();
    const req = http.expectOne('/api/v1/agent/locks/2026-01-05');
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
    await fixture.whenStable();
    expect(el.querySelector('[data-lock="2026-01-05"]')).toBeNull();
  });
});
