// T-WEB-382..386: sign-in with a passkey, and the recovery code behind its disclosure — the
// requests that go out, where the person lands, what the button says while it waits, and the
// sentence shown when the server refuses.
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';
import * as webauthn from '@simplewebauthn/browser';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Me } from '../../api';
import { PrefsService } from '../../core/prefs.service';
import { LoginPage } from './login-page';

vi.mock('@simplewebauthn/browser', () => ({
  startAuthentication: vi.fn(),
  startRegistration: vi.fn(),
}));

const me: Me = {
  user: { id: 'u1', display_name: 'Alice', email: 'alice@example.com', role: 'owner' },
  tenant: { id: 't1', slug: 'alice', name: 'Alice' },
  csrf_token: 'csrf-1',
  passkeys: 2,
  recovery_session: false,
};

const settle = async () => {
  for (let i = 0; i < 6; i++) await Promise.resolve();
};

describe('LoginPage', () => {
  let http: HttpTestingController;
  let router: Router;
  let returnUrl: string | null;

  function render(): ComponentFixture<LoginPage> {
    const f = TestBed.createComponent(LoginPage);
    f.detectChanges();
    return f;
  }

  const el = (f: ComponentFixture<LoginPage>) => f.nativeElement as HTMLElement;
  const signInButton = (f: ComponentFixture<LoginPage>) =>
    el(f).querySelector('button.primary') as HTMLButtonElement;

  async function redraw(f: ComponentFixture<LoginPage>): Promise<void> {
    await settle();
    await f.whenStable();
    f.detectChanges();
  }

  function type(f: ComponentFixture<LoginPage>, name: string, value: string): void {
    const input = el(f).querySelector(`input[name="${name}"]`) as HTMLInputElement;
    input.value = value;
    input.dispatchEvent(new Event('input'));
    f.detectChanges();
  }

  beforeEach(() => {
    returnUrl = null;
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              get queryParamMap() {
                return convertToParamMap(returnUrl ? { returnUrl } : {});
              },
            },
          },
        },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    vi.mocked(webauthn.startAuthentication).mockReset();
  });

  afterEach(() => http.verify());

  it('T-WEB-382: offers one passkey button, with recovery folded away and no error', () => {
    const f = render();
    expect(el(f).querySelector('h1')?.textContent).toContain('Sign in');
    expect(signInButton(f).textContent).toContain('Sign in with passkey');
    expect(signInButton(f).disabled).toBe(false);
    expect((el(f).querySelector('details.recovery') as HTMLDetailsElement).open).toBe(false);
    expect(el(f).querySelector('[role="alert"]')).toBeNull();
  });

  it('T-WEB-383: signs in with the passkey and returns to the page that was asked for', async () => {
    returnUrl = '/weight';
    const nav = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    vi.mocked(webauthn.startAuthentication).mockResolvedValue({ id: 'c', rawId: 'c', type: 'public-key' } as never);
    const f = render();
    signInButton(f).click();
    await redraw(f);

    // loading: the button says what it waits for and cannot be pressed twice
    expect(signInButton(f).disabled).toBe(true);
    expect(signInButton(f).textContent).toContain('Waiting for your passkey…');

    const opts = http.expectOne('/api/v1/auth/webauthn/login/options');
    expect(opts.request.method).toBe('POST');
    expect(opts.request.body).toEqual({});
    opts.flush({ ceremony_id: 'cer-1', challenge: 'abc' });
    await settle();
    const verify = http.expectOne('/api/v1/auth/webauthn/login/verify');
    expect(verify.request.body).toEqual({ id: 'c', rawId: 'c', type: 'public-key', ceremony_id: 'cer-1' });
    verify.flush(me);
    await redraw(f);

    expect(nav).toHaveBeenCalledWith('/weight');
    expect(signInButton(f).disabled).toBe(false);
    expect(signInButton(f).textContent).toContain('Sign in with passkey');
  });

  it('T-WEB-383: without a return address, or with the login page as one, opens the landing page', async () => {
    const nav = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    const prefs = TestBed.inject(PrefsService);
    prefs.landing.set('reports');
    vi.mocked(webauthn.startAuthentication).mockResolvedValue({ id: 'c', rawId: 'c', type: 'public-key' } as never);
    const f = render();

    for (const back of [null, '/login?returnUrl=%2Fdays']) {
      returnUrl = back;
      signInButton(f).click();
      await settle();
      http.expectOne('/api/v1/auth/webauthn/login/options').flush({ ceremony_id: 'x', challenge: 'y' });
      await settle();
      http.expectOne('/api/v1/auth/webauthn/login/verify').flush(me);
      await redraw(f);
    }
    expect(nav.mock.calls).toEqual([['/reports'], ['/reports']]);
  });

  it('T-WEB-384: says what the server said when it refuses the sign-in', async () => {
    const nav = vi.spyOn(router, 'navigateByUrl');
    const f = render();
    signInButton(f).click();
    await settle();
    http
      .expectOne('/api/v1/auth/webauthn/login/options')
      .flush(
        { type: 'about:blank', title: 'Too Many Requests', status: 429, detail: 'Too many sign-in attempts. Wait a minute.' },
        { status: 429, statusText: 'Too Many Requests' },
      );
    await redraw(f);

    expect(el(f).querySelector('[role="alert"]')?.textContent).toContain('Too many sign-in attempts. Wait a minute.');
    expect(signInButton(f).disabled).toBe(false), 'the person can try again';
    expect(nav).not.toHaveBeenCalled();
  });

  it('T-WEB-384: a passkey prompt the person cancels is shown, and cleared on the next attempt', async () => {
    vi.mocked(webauthn.startAuthentication).mockRejectedValueOnce(new Error('The operation either timed out or was not allowed.'));
    const f = render();
    signInButton(f).click();
    await settle();
    http.expectOne('/api/v1/auth/webauthn/login/options').flush({ ceremony_id: 'x', challenge: 'y' });
    await redraw(f);
    expect(el(f).querySelector('[role="alert"]')?.textContent).toContain('timed out or was not allowed');

    signInButton(f).click();
    await redraw(f);
    expect(el(f).querySelector('[role="alert"]')).toBeNull();
    http.expectOne('/api/v1/auth/webauthn/login/options').error(new ProgressEvent('error'));
    await redraw(f);
    // A network failure reaches describeError with a ProgressEvent (XHR) or a TypeError
    // (fetch) as its body, so it reads as status 0 rather than as "not reachable".
    expect(el(f).querySelector('[role="alert"]')?.textContent).toContain('Request failed (0).');
  });

  it('T-WEB-385: the recovery form opens on request and only submits with both fields', async () => {
    const f = render();
    const details = el(f).querySelector('details.recovery') as HTMLDetailsElement;
    (details.querySelector('summary') as HTMLElement).click();
    f.detectChanges();
    expect(f.componentInstance.showRecovery()).toBe(true);
    expect(details.open).toBe(true);

    await f.whenStable();
    const submit = el(f).querySelector('button[type="submit"]') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    type(f, 'email', 'alice@example.com');
    expect(submit.disabled).toBe(true), 'the code is still missing';
    type(f, 'code', 'ABCD-EFGH');
    expect(submit.disabled).toBe(false);

    (details.querySelector('summary') as HTMLElement).click();
    f.detectChanges();
    expect(f.componentInstance.showRecovery()).toBe(false);
  });

  it('T-WEB-385: a recovery code signs in with trimmed values and opens passkey registration', async () => {
    const nav = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    const f = render();
    await f.whenStable();
    type(f, 'email', '  alice@example.com ');
    type(f, 'code', ' ABCD-EFGH ');
    (el(f).querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit'));
    await redraw(f);

    expect(signInButton(f).disabled).toBe(true), 'loading: nothing else can start meanwhile';
    const req = http.expectOne('/api/v1/auth/recovery');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ code: 'ABCD-EFGH', email: 'alice@example.com' });
    req.flush({ ...me, passkeys: 0, recovery_session: true });
    await redraw(f);

    expect(nav).toHaveBeenCalledWith(['/settings'], { fragment: 'passkeys' });
    expect(signInButton(f).disabled).toBe(false);
  });

  it('T-WEB-386: a refused recovery code shows the problem and stays on the page', async () => {
    const nav = vi.spyOn(router, 'navigate');
    const f = render();
    await f.whenStable();
    type(f, 'email', 'alice@example.com');
    type(f, 'code', 'WRONG');
    (el(f).querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit'));
    await settle();
    http
      .expectOne('/api/v1/auth/recovery')
      .flush(
        { title: 'Unauthorized', status: 401, detail: 'The recovery code is not valid.' },
        { status: 401, statusText: 'Unauthorized' },
      );
    await redraw(f);

    expect(el(f).querySelector('[role="alert"]')?.textContent).toContain('The recovery code is not valid.');
    expect(nav).not.toHaveBeenCalled();
    expect((el(f).querySelector('button[type="submit"]') as HTMLButtonElement).disabled).toBe(false);
  });
});
