// T-WEB-008: ApiClient — paths, query parameters and bodies match docs/API.md.
// T-WEB-218: amending a proposal, finding one by its one-off, moving an item between meals.
import { TestBed } from '@angular/core/testing';
import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { Observable } from 'rxjs';
import { describeError, namesField } from '../core/problem';
import { ApiClient } from './api-client';
import { BodyMeasurementInput, CaptureStatus, ProductInput, TargetBand } from './models';

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
  it('T-WEB-218: amends a proposal, finds one by its one-off and moves an item, and passes a refusal on', () => {
    const answers: unknown[] = [];
    api.amendProposal('pr-1', { changes: { kcal: 66, protein: null }, rationale: 'label re-read' }).subscribe((p) => answers.push(p));
    const amend = http.expectOne('/api/v1/proposals/pr-1');
    expect(amend.request.method).toBe('PATCH');
    expect(amend.request.body).toEqual({ changes: { kcal: 66, protein: null }, rationale: 'label re-read' });
    amend.flush({ id: 'pr-1', status: 'pending' });
    expect(answers).toEqual([{ id: 'pr-1', status: 'pending' }]);

    api.proposals({ consumable_id: 77 }).subscribe();
    const list = http.expectOne((r) => r.url === '/api/v1/proposals');
    expect(list.request.params.get('consumable_id')).toBe('77');
    expect(list.request.params.get('status')).toBe('pending');
    expect(list.request.params.has('product_id')).toBe(false);
    list.flush([]);

    api.updateLineItem(31, { meal_id: 2 }).subscribe();
    const move = http.expectOne('/api/v1/line-items/31');
    expect(move.request.method).toBe('PATCH');
    expect(move.request.body).toEqual({ meal_id: 2 });
    move.flush({});

    const errors: number[] = [];
    api.amendProposal('pr-1', { changes: { kcal: 1 } }).subscribe({ error: (e: { status: number }) => errors.push(e.status) });
    http.expectOne('/api/v1/proposals/pr-1').flush({ title: 'Conflict', status: 409 }, { status: 409, statusText: 'Conflict' });
    api.updateLineItem(31, { meal_id: 9 }).subscribe({ error: (e: { status: number }) => errors.push(e.status) });
    http.expectOne('/api/v1/line-items/31').flush({ title: 'Validation failed', status: 422 }, { status: 422, statusText: 'Unprocessable' });
    expect(errors).toEqual([409, 422]);
  });
});

// T-WEB-300..305: every public ApiClient method, one row each. A row names the method, calls it,
// and states the request it must send: HTTP method, path, every query parameter (no more, no
// fewer) and the body. The flushed response must reach the subscriber unchanged, and a
// problem+json refusal must reach it as the HttpErrorResponse that describeError/namesField read.
// tests/unit/tooling/test_api_client_specs.py fails when a method is named by no spec.
interface ClientCase {
  name: keyof ApiClient;
  call: (api: ApiClient) => Observable<unknown>;
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  url: string;
  params?: Record<string, string>;
  body?: unknown;
}

const form = new FormData();
form.append('kind', 'photo');

const clientCases: ClientCase[] = [
  // system and auth
  { name: 'health', call: (a) => a.health(), method: 'GET', url: '/api/v1/health' },
  { name: 'backupJobs', call: (a) => a.backupJobs(5), method: 'GET', url: '/api/v1/backup/jobs', params: { limit: '5' } },
  { name: 'me', call: (a) => a.me(), method: 'GET', url: '/api/v1/auth/me' },
  { name: 'logout', call: (a) => a.logout(), method: 'POST', url: '/api/v1/auth/logout', body: {} },
  { name: 'webauthnRegisterOptions', call: (a) => a.webauthnRegisterOptions({ name: 'Laptop', invitation: 'inv-1' }), method: 'POST', url: '/api/v1/auth/webauthn/register/options', body: { name: 'Laptop', invitation: 'inv-1' } },
  { name: 'webauthnRegisterVerify', call: (a) => a.webauthnRegisterVerify({ id: 'cred-1' }), method: 'POST', url: '/api/v1/auth/webauthn/register/verify', body: { id: 'cred-1' } },
  { name: 'webauthnLoginOptions', call: (a) => a.webauthnLoginOptions({ email: 'alice@victus.example.com' }), method: 'POST', url: '/api/v1/auth/webauthn/login/options', body: { email: 'alice@victus.example.com' } },
  { name: 'webauthnLoginVerify', call: (a) => a.webauthnLoginVerify({ id: 'cred-1' }), method: 'POST', url: '/api/v1/auth/webauthn/login/verify', body: { id: 'cred-1' } },
  { name: 'recovery', call: (a) => a.recovery('ABCD-EFGH', 'alice@victus.example.com'), method: 'POST', url: '/api/v1/auth/recovery', body: { code: 'ABCD-EFGH', email: 'alice@victus.example.com' } },
  { name: 'passkeys', call: (a) => a.passkeys(), method: 'GET', url: '/api/v1/auth/passkeys' },
  { name: 'deletePasskey', call: (a) => a.deletePasskey('pk-1'), method: 'DELETE', url: '/api/v1/auth/passkeys/pk-1' },
  { name: 'tokens', call: (a) => a.tokens(), method: 'GET', url: '/api/v1/auth/tokens' },
  { name: 'createToken', call: (a) => a.createToken({ name: 'agent', scopes: ['read'], expires_at: null }), method: 'POST', url: '/api/v1/auth/tokens', body: { name: 'agent', scopes: ['read'], expires_at: null } },
  { name: 'revokeToken', call: (a) => a.revokeToken('tok-1'), method: 'DELETE', url: '/api/v1/auth/tokens/tok-1' },
  // master data
  { name: 'units', call: (a) => a.units(), method: 'GET', url: '/api/v1/units' },
  { name: 'categories', call: (a) => a.categories(), method: 'GET', url: '/api/v1/categories' },
  { name: 'products', call: (a) => a.products('oats', { category: 2, limit: 20, offset: 40, on: '2026-01-05' }), method: 'GET', url: '/api/v1/products', params: { q: 'oats', category: '2', limit: '20', offset: '40', on: '2026-01-05' } },
  { name: 'product', call: (a) => a.product(12), method: 'GET', url: '/api/v1/products/12' },
  { name: 'createProduct', call: (a) => a.createProduct({ name: 'Oats', kcal: 370 } as unknown as ProductInput), method: 'POST', url: '/api/v1/products', body: { name: 'Oats', kcal: 370 } },
  { name: 'productUsage', call: (a) => a.productUsage(12), method: 'GET', url: '/api/v1/products/12/usage', params: { limit: '100' } },
  { name: 'updateProduct', call: (a) => a.updateProduct(12, { name: 'Rolled oats' }), method: 'PATCH', url: '/api/v1/products/12', body: { name: 'Rolled oats' } },
  { name: 'deleteProduct', call: (a) => a.deleteProduct(12), method: 'DELETE', url: '/api/v1/products/12' },
  { name: 'matchProducts', call: (a) => a.matchProducts('two eggs'), method: 'POST', url: '/api/v1/products/match', body: { text: 'two eggs' } },
  { name: 'createPortion', call: (a) => a.createPortion(12, { unit_code: 'cup', label: 'cup', amount: 80, amount_unit: 'g', is_default: false }), method: 'POST', url: '/api/v1/products/12/portions', body: { unit_code: 'cup', label: 'cup', amount: 80, amount_unit: 'g', is_default: false } },
  { name: 'updatePortion', call: (a) => a.updatePortion(5, { amount: 90 }), method: 'PATCH', url: '/api/v1/portions/5', body: { amount: 90 } },
  { name: 'deletePortion', call: (a) => a.deletePortion(5), method: 'DELETE', url: '/api/v1/portions/5' },
  { name: 'recipes', call: (a) => a.recipes(), method: 'GET', url: '/api/v1/recipes' },
  { name: 'recipe', call: (a) => a.recipe(3), method: 'GET', url: '/api/v1/recipes/3' },
  { name: 'cookBatch', call: (a) => a.cookBatch(3, { cooked_at: '2026-01-05', servings: 4, total_weight_g: 1200 }), method: 'POST', url: '/api/v1/recipes/3/batches', body: { cooked_at: '2026-01-05', servings: 4, total_weight_g: 1200 } },
  { name: 'updateRecipe', call: (a) => a.updateRecipe(3, { name: 'Chili', default_servings: 4 }), method: 'PATCH', url: '/api/v1/recipes/3', body: { name: 'Chili', default_servings: 4 } },
  { name: 'replaceIngredients', call: (a) => a.replaceIngredients(3, [{ position: 1, product_id: 12, amount: 200, unit_code: 'g' }]), method: 'PUT', url: '/api/v1/recipes/3/ingredients', body: { ingredients: [{ position: 1, product_id: 12, amount: 200, unit_code: 'g' }] } },
  { name: 'batch', call: (a) => a.batch(9), method: 'GET', url: '/api/v1/batches/9' },
  // days
  { name: 'days', call: (a) => a.days('2026-01-01', '2026-01-14', 'closed'), method: 'GET', url: '/api/v1/days', params: { from: '2026-01-01', to: '2026-01-14', status: 'closed' } },
  { name: 'day', call: (a) => a.day('2026-01-05'), method: 'GET', url: '/api/v1/days/2026-01-05' },
  { name: 'createDay', call: (a) => a.createDay('2026-01-05', { reliable: false, notes: 'travel' }), method: 'POST', url: '/api/v1/days/2026-01-05', body: { reliable: false, notes: 'travel' } },
  { name: 'updateDay', call: (a) => a.updateDay('2026-01-05', { reliable: true, training_type: null }), method: 'PUT', url: '/api/v1/days/2026-01-05', body: { reliable: true, training_type: null } },
  { name: 'updateMeal', call: (a) => a.updateMeal(4, { name: 'Lunch', time: '12:30' }), method: 'PATCH', url: '/api/v1/meals/4', body: { name: 'Lunch', time: '12:30' } },
  { name: 'deleteMeal', call: (a) => a.deleteMeal(4), method: 'DELETE', url: '/api/v1/meals/4' },
  { name: 'addMeal', call: (a) => a.addMeal('2026-01-05', { name: 'Dinner', time: null }), method: 'POST', url: '/api/v1/days/2026-01-05/meals', body: { name: 'Dinner', time: null } },
  { name: 'addLineItem', call: (a) => a.addLineItem(4, { consumable_id: 12, amount: 50, unit_code: 'g' }), method: 'POST', url: '/api/v1/meals/4/line-items', body: { consumable_id: 12, amount: 50, unit_code: 'g' } },
  { name: 'updateLineItem', call: (a) => a.updateLineItem(8, { amount: 60 }), method: 'PATCH', url: '/api/v1/line-items/8', body: { amount: 60 } },
  { name: 'approveLineItem', call: (a) => a.approveLineItem(8), method: 'POST', url: '/api/v1/line-items/8/approve', body: {} },
  { name: 'deleteLineItem', call: (a) => a.deleteLineItem(8), method: 'DELETE', url: '/api/v1/line-items/8' },
  { name: 'closeDay', call: (a) => a.closeDay('2026-01-05'), method: 'POST', url: '/api/v1/days/2026-01-05/close', body: {} },
  { name: 'reopenDay', call: (a) => a.reopenDay('2026-01-05'), method: 'POST', url: '/api/v1/days/2026-01-05/reopen', body: {} },
  { name: 'dayMessages', call: (a) => a.dayMessages('2026-01-05'), method: 'GET', url: '/api/v1/days/2026-01-05/messages' },
  { name: 'addDayMessage', call: (a) => a.addDayMessage('2026-01-05', 'lunch was 300 g'), method: 'POST', url: '/api/v1/days/2026-01-05/messages', body: { text: 'lunch was 300 g' } },
  // drafts
  { name: 'drafts', call: (a) => a.drafts(), method: 'GET', url: '/api/v1/drafts' },
  { name: 'draftSummary', call: (a) => a.draftSummary('2026-01-05'), method: 'GET', url: '/api/v1/drafts/2026-01-05/summary' },
  { name: 'approveDraft', call: (a) => a.approveDraft('2026-01-05', { corrections: [], close: true }), method: 'POST', url: '/api/v1/drafts/2026-01-05/approve', body: { corrections: [], close: true } },
  { name: 'discardDraft', call: (a) => a.discardDraft('2026-01-05'), method: 'POST', url: '/api/v1/drafts/2026-01-05/discard', body: {} },
  // weight and body
  { name: 'weight', call: (a) => a.weight('2026-01-01', '2026-01-31'), method: 'GET', url: '/api/v1/weight', params: { from: '2026-01-01', to: '2026-01-31' } },
  { name: 'addWeight', call: (a) => a.addWeight({ measured_at: '2026-01-05', kg: 70.4 }), method: 'POST', url: '/api/v1/weight', body: { measured_at: '2026-01-05', kg: 70.4 } },
  { name: 'deleteWeight', call: (a) => a.deleteWeight(6), method: 'DELETE', url: '/api/v1/weight/6' },
  { name: 'bodyMeasurements', call: (a) => a.bodyMeasurements({ from: '2026-01-01', to: '2026-02-01', limit: 10 }), method: 'GET', url: '/api/v1/body-measurements', params: { from: '2026-01-01', to: '2026-02-01', limit: '10' } },
  { name: 'addBodyMeasurement', call: (a) => a.addBodyMeasurement({ measured_at: '2026-01-05', waist_cm: 80 } as BodyMeasurementInput), method: 'POST', url: '/api/v1/body-measurements', body: { measured_at: '2026-01-05', waist_cm: 80 } },
  { name: 'deleteBodyMeasurement', call: (a) => a.deleteBodyMeasurement(2), method: 'DELETE', url: '/api/v1/body-measurements/2' },
  // settings
  { name: 'targetBands', call: (a) => a.targetBands(), method: 'GET', url: '/api/v1/target-bands' },
  { name: 'upsertTargetBand', call: (a) => a.upsertTargetBand({ name: 'rest', valid_from: '2026-01-01' } as Omit<TargetBand, 'id'>), method: 'POST', url: '/api/v1/target-bands', body: { name: 'rest', valid_from: '2026-01-01' } },
  { name: 'rules', call: (a) => a.rules(), method: 'GET', url: '/api/v1/settings/rules' },
  { name: 'putRule', call: (a) => a.putRule({ name: 'eggs', when: 'egg', then: '60 g' }), method: 'PUT', url: '/api/v1/settings/rules', body: { name: 'eggs', when: 'egg', then: '60 g' } },
  { name: 'deleteRule', call: (a) => a.deleteRule('eggs & toast'), method: 'DELETE', url: '/api/v1/settings/rules/eggs%20%26%20toast' },
  { name: 'settings', call: (a) => a.settings(), method: 'GET', url: '/api/v1/settings' },
  { name: 'putSettings', call: (a) => a.putSettings({ language: 'en' }), method: 'PUT', url: '/api/v1/settings', body: { data: { language: 'en' } } },
  { name: 'settingsVersions', call: (a) => a.settingsVersions(), method: 'GET', url: '/api/v1/settings/versions' },
  // captures, snapshots, proposals
  { name: 'captures', call: (a) => a.captures('new', '2026-01-05', 12), method: 'GET', url: '/api/v1/captures', params: { status: 'new', date: '2026-01-05', product_id: '12' } },
  { name: 'capture', call: (a) => a.capture('c1'), method: 'GET', url: '/api/v1/captures/c1' },
  { name: 'deleteCapture', call: (a) => a.deleteCapture('c1'), method: 'DELETE', url: '/api/v1/captures/c1' },
  { name: 'snapshots', call: (a) => a.snapshots('checkup'), method: 'GET', url: '/api/v1/reports/snapshots', params: { report: 'checkup', limit: '50' } },
  { name: 'snapshot', call: (a) => a.snapshot('s1'), method: 'GET', url: '/api/v1/reports/snapshots/s1' },
  { name: 'createSnapshot', call: (a) => a.createSnapshot('checkup', { from: '2026-01-01', to: '2026-01-14', label: 'week 2', asOf: '2026-01-15' }), method: 'POST', url: '/api/v1/reports/checkup/snapshots', params: { from: '2026-01-01', to: '2026-01-14', label: 'week 2', as_of: '2026-01-15' }, body: {} },
  { name: 'assessSnapshot', call: (a) => a.assessSnapshot('s1', '## Findings'), method: 'POST', url: '/api/v1/reports/snapshots/s1/assess', body: { markdown: '## Findings' } },
  { name: 'deleteSnapshot', call: (a) => a.deleteSnapshot('s1'), method: 'DELETE', url: '/api/v1/reports/snapshots/s1' },
  { name: 'proposals', call: (a) => a.proposals(), method: 'GET', url: '/api/v1/proposals', params: { status: 'pending' } },
  { name: 'amendProposal', call: (a) => a.amendProposal('p1', { changes: { kcal: 71 } }), method: 'PATCH', url: '/api/v1/proposals/p1', body: { changes: { kcal: 71 } } },
  { name: 'approveProposal', call: (a) => a.approveProposal('p1', { fields: ['kcal'] }), method: 'POST', url: '/api/v1/proposals/p1/approve', body: { fields: ['kcal'] } },
  { name: 'rejectProposal', call: (a) => a.rejectProposal('p1'), method: 'POST', url: '/api/v1/proposals/p1/reject', body: {} },
  { name: 'uploadCapture', call: (a) => a.uploadCapture(form), method: 'POST', url: '/api/v1/captures', body: form },
  { name: 'updateCapture', call: (a) => a.updateCapture('c1', { status: 'done' as CaptureStatus, target_date: null }), method: 'PATCH', url: '/api/v1/captures/c1', body: { status: 'done', target_date: null } },
  { name: 'transcribeCapture', call: (a) => a.transcribeCapture('c1'), method: 'POST', url: '/api/v1/captures/c1/transcribe', params: {}, body: {} },
  { name: 'productVersions', call: (a) => a.productVersions(12), method: 'GET', url: '/api/v1/products/12/versions' },
  { name: 'createProductVersion', call: (a) => a.createProductVersion(12, '2026-02-01', { kcal: 380 }), method: 'POST', url: '/api/v1/products/12/versions', body: { valid_from: '2026-02-01', changes: { kcal: 380 } } },
  // agent
  { name: 'agentStatus', call: (a) => a.agentStatus(), method: 'GET', url: '/api/v1/agent/status' },
  { name: 'startAgentRun', call: (a) => a.startAgentRun({ mode: 'historical', from: '2026-01-01', to: '2026-01-07' }), method: 'POST', url: '/api/v1/agent/runs', body: { mode: 'historical', from: '2026-01-01', to: '2026-01-07' } },
  { name: 'agentRun', call: (a) => a.agentRun('r1'), method: 'GET', url: '/api/v1/agent/runs/r1' },
  { name: 'agentRuns', call: (a) => a.agentRuns(), method: 'GET', url: '/api/v1/agent/runs', params: {} },
  { name: 'cancelAgentRun', call: (a) => a.cancelAgentRun('r1'), method: 'POST', url: '/api/v1/agent/runs/r1/cancel', body: {} },
  { name: 'agentLocks', call: (a) => a.agentLocks(), method: 'GET', url: '/api/v1/agent/locks' },
  { name: 'forceUnlock', call: (a) => a.forceUnlock('2026-01-05'), method: 'DELETE', url: '/api/v1/agent/locks/2026-01-05' },
  // reports
  { name: 'reports', call: (a) => a.reports(), method: 'GET', url: '/api/v1/reports' },
  { name: 'renderReport', call: (a) => a.renderReport('checkup', '2026-01-01', '2026-01-14', '2026-01-15'), method: 'POST', url: '/api/v1/reports/checkup/render', params: { format: 'json', from: '2026-01-01', to: '2026-01-14', as_of: '2026-01-15' }, body: {} },
];

function paramsOf(req: TestRequest): Record<string, string> {
  const out: Record<string, string> = {};
  for (const k of req.request.params.keys()) out[k] = req.request.params.get(k)!;
  return out;
}

describe('T-WEB-300..305: every ApiClient method', () => {
  let api: ApiClient;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    api = TestBed.inject(ApiClient);
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  it('T-WEB-300: the table has exactly one row per request-sending method of the client', () => {
    const names = clientCases.map((c) => c.name as string);
    expect(new Set(names).size).toBe(names.length);
    const own = Object.getOwnPropertyNames(ApiClient.prototype).filter(
      (n) => n !== 'constructor' && n !== 'attachmentUrl',
    );
    expect([...names].sort()).toEqual(own.sort());
  });

  it.each(clientCases.map((c) => [c.name, c] as const))(
    'T-WEB-301: %s sends the documented request and passes the response through',
    (_name, c) => {
      const response = { marker: c.name, items: [1, 2] };
      let received: unknown = 'nothing';
      c.call(api).subscribe((r) => (received = r));
      const req = http.expectOne((r) => r.url === c.url);
      expect(req.request.method).toBe(c.method);
      expect(paramsOf(req)).toEqual(c.params ?? {});
      if (c.method === 'GET' || c.method === 'DELETE') {
        expect(req.request.body).toBeNull();
      } else {
        expect(req.request.body).toEqual(c.body);
      }
      req.flush(response);
      expect(received).toEqual(response);
    },
  );

  it.each(clientCases.map((c) => [c.name, c] as const))(
    'T-WEB-302: %s hands a problem+json refusal to describeError and namesField',
    (_name, c) => {
      let error: unknown;
      let nexted = false;
      c.call(api).subscribe({ next: () => (nexted = true), error: (e: unknown) => (error = e) });
      http.expectOne((r) => r.url === c.url).flush(
        {
          type: 'about:blank',
          title: 'Unprocessable Content',
          status: 422,
          detail: `${c.name} was refused`,
          errors: [{ field: 'amount', message: 'must be positive' }],
        },
        { status: 422, statusText: 'Unprocessable Content', headers: { 'Content-Type': 'application/problem+json' } },
      );
      expect(nexted).toBe(false);
      expect(error).toBeInstanceOf(HttpErrorResponse);
      expect((error as HttpErrorResponse).status).toBe(422);
      expect(describeError(error)).toBe(`${c.name} was refused — amount: must be positive`);
      expect(namesField(error, 'amount')).toBe(true);
      expect(namesField(error, 'unit_code')).toBe(false);
    },
  );

  it('T-WEB-303: attachmentUrl builds the attachment path without a request', () => {
    expect(api.attachmentUrl('a-9')).toBe('/api/v1/attachments/a-9');
  });

  it('T-WEB-304: optional query parameters are left out when empty, null, false or absent', () => {
    api.products('', { category: undefined, on: null }).subscribe();
    expect(paramsOf(http.expectOne((r) => r.url === '/api/v1/products'))).toEqual({});
    api.proposals({ status: 'approved', product_id: 4 }).subscribe();
    expect(paramsOf(http.expectOne((r) => r.url === '/api/v1/proposals'))).toEqual({ status: 'approved', product_id: '4' });
    api.productUsage(1, 5).subscribe();
    expect(paramsOf(http.expectOne((r) => r.url === '/api/v1/products/1/usage'))).toEqual({ limit: '5' });
    api.createSnapshot('checkup').subscribe();
    expect(paramsOf(http.expectOne((r) => r.url === '/api/v1/reports/checkup/snapshots'))).toEqual({});
    api.renderReport('checkup', '2026-01-01', '2026-01-14').subscribe();
    expect(paramsOf(http.expectOne((r) => r.url === '/api/v1/reports/checkup/render'))).toEqual({ format: 'json', from: '2026-01-01', to: '2026-01-14' });
    api.bodyMeasurements().subscribe();
    expect(paramsOf(http.expectOne((r) => r.url === '/api/v1/body-measurements'))).toEqual({});
    api.transcribeCapture('c2', false).subscribe();
    expect(paramsOf(http.expectOne((r) => r.url === '/api/v1/captures/c2/transcribe'))).toEqual({});
    api.captures().subscribe();
    expect(paramsOf(http.expectOne((r) => r.url === '/api/v1/captures'))).toEqual({});
    api.snapshots(undefined, 5).subscribe();
    expect(paramsOf(http.expectOne((r) => r.url === '/api/v1/reports/snapshots'))).toEqual({ limit: '5' });
  });

  it('T-WEB-305: omitted request bodies default to an empty object', () => {
    api.webauthnRegisterOptions().subscribe();
    expect(http.expectOne('/api/v1/auth/webauthn/register/options').request.body).toEqual({});
    api.webauthnLoginOptions().subscribe();
    expect(http.expectOne('/api/v1/auth/webauthn/login/options').request.body).toEqual({});
    api.approveProposal('p2').subscribe();
    expect(http.expectOne('/api/v1/proposals/p2/approve').request.body).toEqual({});
    api.approveLineItem(3, { amount: 20 }).subscribe();
    expect(http.expectOne('/api/v1/line-items/3/approve').request.body).toEqual({ amount: 20 });
  });
});
