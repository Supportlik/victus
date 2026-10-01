// T-WEB-100…103: the API token form offers the server's scopes and nothing else, the scope
// profiles as presets beside them with a link to their explanation, and every token call
// (list, create, revoke) answers on screen whether it succeeds or fails.
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { NoticeService } from '../../core/notice.service';
import { SCOPE_PRESETS, SCOPE_PROFILES_DOC, SCOPES, presetFor } from './scope-profiles';
import { SettingsPage } from './settings-page';

const SERVER_SCOPES = ['read', 'write', 'approve', 'capture:read', 'capture:write', 'agent:write', 'admin'];
const TOKEN = {
  id: 'tok_1',
  name: 'phone',
  prefix: 'vct_abcd1234',
  scopes: ['capture:write'],
  expires_at: '2027-01-01T00:00:00Z',
  last_used_at: null,
  revoked_at: null,
};

describe('SettingsPage — API tokens', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
  });

  async function open(tokens: object[] | Error = [TOKEN]) {
    const f = TestBed.createComponent(SettingsPage);
    f.detectChanges();
    http.match((r) => r.url === '/api/v1/auth/tokens' && r.method === 'GET').forEach((r) =>
      tokens instanceof Error ? r.flush({ detail: 'scope required' }, { status: 403, statusText: 'Forbidden' }) : r.flush(tokens),
    );
    http.match((r) => r.url === '/api/v1/settings').forEach((r) => r.flush({ version: 1, valid_from: '2026-01-01', data: {} }));
    http.match((r) => r.url === '/api/v1/health').forEach((r) => r.flush({ status: 'ok', version: '1.0.0', checks: {} }));
    http.match(() => true).forEach((r) => r.flush([]));
    f.detectChanges();
    await f.whenStable();
    f.detectChanges();
    return { f, el: f.nativeElement as HTMLElement, page: f.componentInstance };
  }

  function scopeBoxes(el: HTMLElement): HTMLInputElement[] {
    return [...el.querySelectorAll<HTMLInputElement>('fieldset.scopes input[type=checkbox]')];
  }

  async function tick(f: { detectChanges(): void; whenStable(): Promise<unknown> }, el: HTMLElement, scope: string) {
    el.querySelector<HTMLInputElement>(`fieldset.scopes input[data-scope="${scope}"]`)!.click();
    f.detectChanges();
    await f.whenStable();
    f.detectChanges();
  }

  async function submit(f: { detectChanges(): void; whenStable(): Promise<unknown> }, el: HTMLElement, name = 'claude') {
    const input = el.querySelector<HTMLInputElement>('input[name=tn]')!;
    input.value = name;
    input.dispatchEvent(new Event('input'));
    f.detectChanges();
    await f.whenStable();
    el.querySelector<HTMLFormElement>('#tokens form.add')!.dispatchEvent(new Event('submit'));
    f.detectChanges();
  }

  it('T-WEB-100 offers exactly the scopes the server knows, and sends every one it ticks', async () => {
    const { f, el, page } = await open();
    const labels = [...el.querySelectorAll('fieldset.scopes label')].map((l) => l.textContent!.trim());
    expect(labels).toEqual(SERVER_SCOPES);
    expect([...SCOPES]).toEqual(SERVER_SCOPES);
    expect(labels).not.toContain('settings');
    expect(labels).not.toContain('backup');

    for (const s of SERVER_SCOPES) if (!page.tokenScopes.has(s)) await tick(f, el, s);
    expect(scopeBoxes(el).every((b) => b.checked)).toBe(true);
    await submit(f, el);
    const req = http.expectOne((r) => r.url === '/api/v1/auth/tokens' && r.method === 'POST');
    expect(req.request.body).toEqual({ name: 'claude', scopes: SERVER_SCOPES, expires_at: null });
    req.flush({ ...TOKEN, id: 'tok_2', name: 'claude', scopes: SERVER_SCOPES, token: 'vct_secret.once' });
    f.detectChanges();
    expect(el.querySelector('.v-notice code')!.textContent).toBe('vct_secret.once');
    const rows = [...el.querySelectorAll('#tokens tbody tr')];
    expect(rows[0].textContent).toContain('claude');
    expect(rows.length).toBe(2);
  });

  it.each(SCOPE_PRESETS.map((p) => [p.key, p] as const))('T-WEB-101 the %s preset ticks exactly its scopes', async (_key, preset) => {
    const { f, el } = await open();
    const button = el.querySelector<HTMLButtonElement>(`button.preset[data-preset="${preset.key}"]`)!;
    expect(button.textContent!.trim()).toBe(preset.title);
    button.click();
    f.detectChanges();
    await f.whenStable();
    f.detectChanges();
    const ticked = scopeBoxes(el).filter((b) => b.checked).map((b) => b.dataset['scope']);
    expect(ticked).toEqual(SERVER_SCOPES.filter((s) => preset.scopes.includes(s)));
    expect(button.classList.contains('active')).toBe(true);
    expect(button.getAttribute('aria-pressed')).toBe('true');
    expect(el.querySelector('.preset-intent')!.textContent!.trim()).toBe(preset.intent);
    expect(preset.scopes).not.toContain('admin');

    await submit(f, el, preset.key);
    const req = http.expectOne((r) => r.url === '/api/v1/auth/tokens' && r.method === 'POST');
    expect([...req.request.body.scopes].sort()).toEqual([...preset.scopes].sort());
    req.flush({ ...TOKEN, id: `tok_${preset.key}`, name: preset.key, scopes: preset.scopes, token: 'vct_x.y' });
  });

  it('T-WEB-102 links the profiles next to the boxes and recognises a preset ticked by hand', async () => {
    const { f, el } = await open();
    const link = el.querySelector<HTMLAnchorElement>('.presets a.profiles-doc')!;
    expect(link.href).toBe(SCOPE_PROFILES_DOC);
    expect(link.target).toBe('_blank');
    expect(link.rel).toContain('noopener');
    // the page opens with read ticked, which is the read-only profile
    expect(el.querySelector('button.preset.active')!.getAttribute('data-preset')).toBe('read-only');

    await tick(f, el, 'read');
    await tick(f, el, 'capture:write');
    expect(el.querySelector('button.preset.active')!.getAttribute('data-preset')).toBe('capture-uploader');
    await tick(f, el, 'admin');
    expect(el.querySelector('button.preset.active')).toBeNull();
    expect(el.querySelector('.preset-intent')).toBeNull();
    expect(presetFor(new Set(['read', 'write']))).toBeUndefined();
  });

  it('T-WEB-103 a refused token creation is a notice and keeps what was entered', async () => {
    const { f, el, page } = await open();
    const notices = TestBed.inject(NoticeService);
    el.querySelector<HTMLButtonElement>('button.preset[data-preset="full-delegate"]')!.click();
    f.detectChanges();
    await submit(f, el, 'delegate');
    http
      .expectOne((r) => r.url === '/api/v1/auth/tokens' && r.method === 'POST')
      .flush({ detail: 'cannot grant scopes you do not hold: approve' }, { status: 403, statusText: 'Forbidden' });
    f.detectChanges();
    expect(notices.notices().at(-1)!.kind).toBe('error');
    expect(notices.notices().at(-1)!.text).toContain('cannot grant scopes you do not hold');
    expect(page.tokenName).toBe('delegate');
    expect(el.querySelector('.v-notice code')).toBeNull();
    expect(el.querySelectorAll('#tokens tbody tr').length).toBe(1);
  });

  it('T-WEB-103 revoking marks the row, and a failed revoke says why', async () => {
    const { f, el } = await open();
    const notices = TestBed.inject(NoticeService);
    el.querySelector<HTMLButtonElement>('#tokens tbody button.danger')!.click();
    http.expectOne((r) => r.url === '/api/v1/auth/tokens/tok_1' && r.method === 'DELETE').flush(null);
    f.detectChanges();
    expect(el.querySelector('#tokens tbody tr')!.classList.contains('revoked')).toBe(true);
    expect(el.querySelector('#tokens tbody .v-tag')!.textContent).toContain('revoked');

    const again = await open([{ ...TOKEN, id: 'tok_9' }]);
    again.el.querySelector<HTMLButtonElement>('#tokens tbody button.danger')!.click();
    http
      .expectOne((r) => r.url === '/api/v1/auth/tokens/tok_9' && r.method === 'DELETE')
      .flush({ detail: 'token not found' }, { status: 404, statusText: 'Not Found' });
    again.f.detectChanges();
    expect(notices.notices().at(-1)!.text).toContain('token not found');
    expect(again.el.querySelector('#tokens tbody tr')!.classList.contains('revoked')).toBe(false);
  });

  it('T-WEB-103 a token list the session may not read shows the refusal on the page', async () => {
    const { el } = await open(new Error('forbidden'));
    expect(el.querySelector('.v-error')!.textContent).toContain('scope required');
    expect(el.querySelector('#tokens tbody')!.textContent).toContain('No tokens yet.');
  });
});
