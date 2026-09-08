// T-WEB-008: ApiClient — paths, query parameters and bodies match docs/API.md.
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApiClient } from './api-client';

describe('ApiClient', () => {
  let api: ApiClient;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    api = TestBed.inject(ApiClient);
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  it('lists days with from/to and optional status', () => {
    api.days('2026-01-01', '2026-01-14').subscribe();
    const req = http.expectOne((r) => r.url === '/api/v1/days');
    expect(req.request.params.get('from')).toBe('2026-01-01');
    expect(req.request.params.get('to')).toBe('2026-01-14');
    expect(req.request.params.has('status')).toBe(false);
    req.flush([]);
  });

  it('searches products with q and limit', () => {
    api.products('quark', { limit: 15 }).subscribe();
    const req = http.expectOne((r) => r.url === '/api/v1/products');
    expect(req.request.params.get('q')).toBe('quark');
    expect(req.request.params.get('limit')).toBe('15');
    req.flush([]);
  });

  it('adds a line item under the meal', () => {
    api.addLineItem(7, { consumable_id: 3, amount: 400, unit_code: 'g', estimated: false }).subscribe();
    const req = http.expectOne('/api/v1/meals/7/line-items');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ consumable_id: 3, amount: 400, unit_code: 'g', estimated: false });
    req.flush({});
  });

  it('renders a report as json with from/to', () => {
    api.renderReport('checkup', '2026-01-01', '2026-01-14').subscribe();
    const req = http.expectOne((r) => r.url === '/api/v1/reports/checkup/render');
    expect(req.request.method).toBe('POST');
    expect(req.request.params.get('format')).toBe('json');
    req.flush({});
  });

  it('posts a day message', () => {
    api.addDayMessage('2026-01-02', 'the chicken was 300 g').subscribe();
    const req = http.expectOne('/api/v1/days/2026-01-02/messages');
    expect(req.request.body).toEqual({ text: 'the chicken was 300 g' });
    req.flush({});
  });

  it('creates a day with POST /days/{date} and reads the discard count', () => {
    api.createDay('2026-01-03', { reliable: true, training_type: null }).subscribe();
    const req = http.expectOne('/api/v1/days/2026-01-03');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ reliable: true, training_type: null });
    req.flush({});
    let removed = -1;
    api.discardDraft('2026-01-03').subscribe((r) => (removed = r.removed));
    http.expectOne('/api/v1/drafts/2026-01-03/discard').flush({ removed: 3 });
    expect(removed).toBe(3);
  });

  it('starts an agent run', () => {
    api.startAgentRun({ mode: 'historical' }).subscribe();
    const req = http.expectOne('/api/v1/agent/runs');
    expect(req.request.body).toEqual({ mode: 'historical' });
    req.flush({});
  });

  // T-WEB-030: capture and agent client methods hit the documented endpoints.
  it('updates, transcribes and addresses captures', () => {
    api.updateCapture('c1', { target_date: '2026-01-05' }).subscribe();
    const patch = http.expectOne('/api/v1/captures/c1');
    expect(patch.request.method).toBe('PATCH');
    expect(patch.request.body).toEqual({ target_date: '2026-01-05' });
    patch.flush({});
    api.transcribeCapture('c1', true).subscribe();
    const tr = http.expectOne((r) => r.url === '/api/v1/captures/c1/transcribe');
    expect(tr.request.method).toBe('POST');
    expect(tr.request.params.get('force')).toBe('true');
    tr.flush({});
    api.captures('new', '2026-01-05').subscribe();
    const list = http.expectOne((r) => r.url === '/api/v1/captures');
    expect(list.request.params.get('status')).toBe('new');
    expect(list.request.params.get('date')).toBe('2026-01-05');
    list.flush([]);
    expect(api.attachmentUrl('a1')).toBe('/api/v1/attachments/a1');
  });

  it('lists, cancels runs and releases locks', () => {
    api.agentRuns({ limit: 10, status: 'queued' }).subscribe();
    const runs = http.expectOne((r) => r.url === '/api/v1/agent/runs');
    expect(runs.request.params.get('limit')).toBe('10');
    expect(runs.request.params.get('status')).toBe('queued');
    runs.flush([]);
    api.cancelAgentRun('r1').subscribe();
    const cancel = http.expectOne('/api/v1/agent/runs/r1/cancel');
    expect(cancel.request.method).toBe('POST');
    cancel.flush({});
    api.agentLocks().subscribe();
    http.expectOne('/api/v1/agent/locks').flush([]);
    api.forceUnlock('2026-01-05').subscribe();
    const del = http.expectOne('/api/v1/agent/locks/2026-01-05');
    expect(del.request.method).toBe('DELETE');
    del.flush(null);
  });
});
