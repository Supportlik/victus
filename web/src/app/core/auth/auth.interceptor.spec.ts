// T-WEB-362, T-WEB-363: the interceptor puts the CSRF token on writes only, and turns a 401
// on a protected request (and only there) into a lost session.
import { HttpClient, HttpErrorResponse, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Me } from '../../api';
import { authInterceptor } from './auth.interceptor';
import { AuthService } from './auth.service';

const me: Me = {
  user: { id: 'u1', display_name: 'Alice', email: 'alice@example.com', role: 'owner' },
  tenant: { id: 't1', slug: 'alice', name: 'Alice' },
  csrf_token: 'csrf-abc',
  passkeys: 2,
  recovery_session: false,
};

describe('authInterceptor', () => {
  let http: HttpTestingController;
  let client: HttpClient;
  let auth: AuthService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpTestingController);
    client = TestBed.inject(HttpClient);
    auth = TestBed.inject(AuthService);
  });

  afterEach(() => http.verify());

  it('T-WEB-362: sends the token on every write method and never on a read', () => {
    auth.me.set(me);
    client.get('/api/v1/days').subscribe();
    client.head('/api/v1/days').subscribe();
    client.options('/api/v1/days').subscribe();
    client.post('/api/v1/weight', {}).subscribe();
    client.put('/api/v1/settings', {}).subscribe();
    client.patch('/api/v1/meals/1', {}).subscribe();
    client.delete('/api/v1/weight/1').subscribe();

    const seen = http.match(() => true);
    const header = Object.fromEntries(seen.map((r) => [r.request.method, r.request.headers.get('X-CSRF-Token')]));
    expect(header).toEqual({
      GET: null,
      HEAD: null,
      OPTIONS: null,
      POST: 'csrf-abc',
      PUT: 'csrf-abc',
      PATCH: 'csrf-abc',
      DELETE: 'csrf-abc',
    });
    seen.forEach((r) => r.flush({}));
  });

  it('T-WEB-362: a write without a session goes out without a header rather than an empty one', () => {
    client.post('/api/v1/auth/webauthn/login/options', {}).subscribe();
    const req = http.expectOne('/api/v1/auth/webauthn/login/options');
    expect(req.request.headers.has('X-CSRF-Token')).toBe(false);
    req.flush({});
  });

  it('T-WEB-363: a 401 from a sign-in endpoint is an answer, not a lost session', () => {
    auth.me.set(me);
    const lost = vi.spyOn(auth, 'sessionLost');
    const errors: number[] = [];
    for (const url of [
      '/api/v1/auth/me',
      '/api/v1/auth/webauthn/login/verify',
      '/api/v1/auth/recovery',
      '/api/v1/health',
      '/api/v1/version',
    ]) {
      client.get(url).subscribe({ error: (e: HttpErrorResponse) => errors.push(e.status) });
      http.expectOne(url).flush({ title: 'Unauthorized' }, { status: 401, statusText: 'Unauthorized' });
    }
    expect(lost).not.toHaveBeenCalled();
    expect(errors).toEqual([401, 401, 401, 401, 401]), 'the caller still sees the refusal';
    expect(auth.isAuthenticated()).toBe(true);
  });

  it('T-WEB-363: any other failure passes through untouched and keeps the session', () => {
    auth.me.set(me);
    const lost = vi.spyOn(auth, 'sessionLost');
    let status = 0;
    client.get('/api/v1/days').subscribe({ error: (e: HttpErrorResponse) => (status = e.status) });
    http.expectOne('/api/v1/days').flush({ title: 'Forbidden' }, { status: 403, statusText: 'Forbidden' });
    expect(status).toBe(403);

    let other: unknown = null;
    client.get('/api/v1/days').subscribe({ error: (e: unknown) => (other = e) });
    http.expectOne('/api/v1/days').error(new ProgressEvent('error'));
    expect(other).toBeInstanceOf(HttpErrorResponse);
    expect(lost).not.toHaveBeenCalled();
  });

  it('T-WEB-363: a 401 on a protected request ends the session', () => {
    auth.me.set(me);
    const lost = vi.spyOn(auth, 'sessionLost').mockImplementation(() => undefined);
    client.get('/api/v1/days').subscribe({ error: () => undefined });
    http.expectOne('/api/v1/days').flush({ title: 'Unauthorized' }, { status: 401, statusText: 'Unauthorized' });
    expect(lost).toHaveBeenCalledOnce();
  });
});
