// T-WEB-007: AuthService — session load, 401 as "not signed in", logout, CSRF header on writes,
// ceremony_id echoed back to the verify endpoints, recovery session flag.
import { TestBed } from '@angular/core/testing';
import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';
import * as webauthn from '@simplewebauthn/browser';
import { AuthService } from './auth.service';
import { authInterceptor } from './auth.interceptor';
import { Me } from '../../api';

vi.mock('@simplewebauthn/browser', () => ({
  startAuthentication: vi.fn(),
  startRegistration: vi.fn(),
}));

const me: Me = {
  user: { id: 'u1', display_name: 'Alice', email: 'alice@example.com', role: 'owner' },
  tenant: { id: 't1', slug: 'alice', name: 'Alice' },
  csrf_token: 'csrf-123',
  passkeys: 2,
  recovery_session: false,
};

/** Lets the pending microtasks between two HTTP round trips settle. */
const settle = async () => {
  for (let i = 0; i < 5; i++) await Promise.resolve();
};

describe('AuthService', () => {
  let service: AuthService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(withInterceptors([authInterceptor])), provideHttpClientTesting()],
    });
    service = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('loads the session from /auth/me', async () => {
    const p = service.load();
    http.expectOne('/api/v1/auth/me').flush(me);
    expect(await p).toEqual(me);
    expect(service.isAuthenticated()).toBe(true);
    expect(service.needsSecondPasskey()).toBe(false);
    expect(service.isRecoverySession()).toBe(false);
  });

  it('treats 401 on /auth/me as signed out, without redirecting', async () => {
    const router = TestBed.inject(Router);
    const spy = vi.spyOn(router, 'navigate');
    const p = service.load();
    http.expectOne('/api/v1/auth/me').flush({ title: 'Unauthorized' }, { status: 401, statusText: 'Unauthorized' });
    expect(await p).toBeNull();
    expect(service.isAuthenticated()).toBe(false);
    expect(service.loaded()).toBe(true);
    expect(spy).not.toHaveBeenCalled();
  });

  it('hands the options without ceremony_id to the browser and echoes it on login/verify', async () => {
    const start = vi.mocked(webauthn.startAuthentication).mockResolvedValue({ id: 'cred', rawId: 'cred', type: 'public-key' } as never);
    const p = service.loginWithPasskey();
    http.expectOne('/api/v1/auth/webauthn/login/options').flush({ ceremony_id: 'cer-1', challenge: 'abc', rpId: 'victus.example.com' });
    await settle();
    expect(start).toHaveBeenCalledWith({ optionsJSON: { challenge: 'abc', rpId: 'victus.example.com' } });
    const verify = http.expectOne('/api/v1/auth/webauthn/login/verify');
    expect(verify.request.body).toEqual({ id: 'cred', rawId: 'cred', type: 'public-key', ceremony_id: 'cer-1' });
    verify.flush(me);
    expect(await p).toEqual(me);
  });

  it('echoes ceremony_id and the passkey name on register/verify and counts the new passkey', async () => {
    service.me.set({ ...me, passkeys: 1 });
    vi.mocked(webauthn.startRegistration).mockResolvedValue({ id: 'new', rawId: 'new', type: 'public-key' } as never);
    const p = service.registerPasskey('Laptop');
    const opts = http.expectOne('/api/v1/auth/webauthn/register/options');
    expect(opts.request.body).toEqual({ name: 'Laptop', invitation: undefined });
    opts.flush({ ceremony_id: 'cer-2', challenge: 'xyz' });
    await settle();
    const verify = http.expectOne('/api/v1/auth/webauthn/register/verify');
    expect(verify.request.body).toEqual({ id: 'new', rawId: 'new', type: 'public-key', ceremony_id: 'cer-2', name: 'Laptop' });
    verify.flush({ id: 'pk2', name: 'Laptop', created_at: '2026-01-01T00:00:00Z', last_used_at: null });
    await p;
    expect(service.me()?.passkeys).toBe(2);
  });

  it('marks a recovery-code login as restricted session', async () => {
    const p = service.recover('alice@example.com', 'ABCD-EFGH');
    const req = http.expectOne('/api/v1/auth/recovery');
    expect(req.request.body).toEqual({ code: 'ABCD-EFGH', email: 'alice@example.com' });
    req.flush({ ...me, passkeys: 0, recovery_session: true });
    await p;
    expect(service.isRecoverySession()).toBe(true);
  });

  it('adds the CSRF token to writes and sends 401 on protected routes to /login', async () => {
    service.me.set(me);
    const client = TestBed.inject(HttpClient);
    const router = TestBed.inject(Router);
    const nav = vi.spyOn(router, 'navigate').mockResolvedValue(true);

    client.post('/api/v1/days/2026-01-01/close', {}).subscribe({ error: () => undefined });
    const req = http.expectOne('/api/v1/days/2026-01-01/close');
    expect(req.request.headers.get('X-CSRF-Token')).toBe('csrf-123');
    req.flush({ title: 'Unauthorized' }, { status: 401, statusText: 'Unauthorized' });

    expect(service.isAuthenticated()).toBe(false);
    expect(nav).toHaveBeenCalledWith(['/login'], expect.objectContaining({ queryParams: expect.anything() }));
  });

  it('logout clears the session even when the API call fails', async () => {
    service.me.set(me);
    const router = TestBed.inject(Router);
    vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    const p = service.logout();
    http.expectOne('/api/v1/auth/logout').flush(null, { status: 500, statusText: 'boom' });
    await p;
    expect(service.me()).toBeNull();
  });
});
