// T-WEB-376: AuthService beyond the basics — the session is loaded once, the e-mail hint and
// the invitation reach the server, and a lost session remembers where the person was.
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import * as webauthn from '@simplewebauthn/browser';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Me } from '../../api';
import { AuthService } from './auth.service';

vi.mock('@simplewebauthn/browser', () => ({
  startAuthentication: vi.fn(),
  startRegistration: vi.fn(),
}));

const me: Me = {
  user: { id: 'u1', display_name: 'Alice', email: 'alice@example.com', role: 'owner' },
  tenant: { id: 't1', slug: 'alice', name: 'Alice' },
  csrf_token: 'csrf-1',
  passkeys: 1,
  recovery_session: false,
};

const settle = async () => {
  for (let i = 0; i < 5; i++) await Promise.resolve();
};

describe('T-WEB-376: AuthService (coverage)', () => {
  let service: AuthService;
  let http: HttpTestingController;
  let router: Router;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
  });

  afterEach(() => http.verify());

  it('T-WEB-376: asks /auth/me once and answers later calls from memory', async () => {
    const first = service.load();
    http.expectOne('/api/v1/auth/me').flush(me);
    expect(await first).toEqual(me);
    expect(service.needsSecondPasskey()).toBe(true);
    expect(await service.load()).toEqual(me);
    http.expectNone('/api/v1/auth/me');
  });

  it('T-WEB-376: sends the e-mail hint with the login options and marks the session loaded', async () => {
    vi.mocked(webauthn.startAuthentication).mockResolvedValue({ id: 'c', rawId: 'c', type: 'public-key' } as never);
    const p = service.loginWithPasskey('alice@example.com');
    const opts = http.expectOne('/api/v1/auth/webauthn/login/options');
    expect(opts.request.body).toEqual({ email: 'alice@example.com' });
    opts.flush({ ceremony_id: 'c-1', challenge: 'x' });
    await settle();
    http.expectOne('/api/v1/auth/webauthn/login/verify').flush(me);
    await p;
    expect(service.loaded()).toBe(true);
    expect(service.isAuthenticated()).toBe(true);
  });

  it('T-WEB-376: a refused login options request rejects with the server problem', async () => {
    const p = service.loginWithPasskey();
    http
      .expectOne('/api/v1/auth/webauthn/login/options')
      .flush({ title: 'Too Many Requests', detail: 'Wait a minute.' }, { status: 429, statusText: 'Too Many Requests' });
    await expect(p).rejects.toMatchObject({ status: 429 });
    expect(service.isAuthenticated()).toBe(false);
  });

  it('T-WEB-376: registering with an invitation and no session leaves the session empty', async () => {
    vi.mocked(webauthn.startRegistration).mockResolvedValue({ id: 'n', rawId: 'n', type: 'public-key' } as never);
    const p = service.registerPasskey(undefined, 'inv-1');
    const opts = http.expectOne('/api/v1/auth/webauthn/register/options');
    expect(opts.request.body).toEqual({ name: undefined, invitation: 'inv-1' });
    opts.flush({ ceremony_id: 'c-2', challenge: 'y' });
    await settle();
    http.expectOne('/api/v1/auth/webauthn/register/verify').flush({ id: 'pk', name: null });
    await p;
    expect(service.me()).toBeNull();
  });

  it('T-WEB-376: logout calls the API, clears the session and opens the login page', async () => {
    service.me.set(me);
    const nav = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    const p = service.logout();
    http.expectOne('/api/v1/auth/logout').flush(null);
    await p;
    expect(service.me()).toBeNull();
    expect(nav).toHaveBeenCalledWith('/login');
  });

  it('T-WEB-376: a lost session remembers the page, but not the login page itself', () => {
    const nav = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    vi.spyOn(router, 'url', 'get').mockReturnValue('/weight');
    service.me.set(me);
    service.sessionLost();
    expect(service.me()).toBeNull();
    expect(service.loaded()).toBe(true);
    expect(nav).toHaveBeenLastCalledWith(['/login'], { queryParams: { returnUrl: '/weight' } });

    vi.spyOn(router, 'url', 'get').mockReturnValue('/login?returnUrl=%2Fweight');
    service.sessionLost();
    expect(nav).toHaveBeenLastCalledWith(['/login'], {});
  });
});
