// T-WEB-006: app shell — bare login layout when signed out, navigation rail when signed in; health line reflects the API.
// T-WEB-005: passkey nudge shown with one passkey, hidden at two.
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { App } from './app';
import { AuthService } from './core/auth/auth.service';
import { Me } from './api';

const me: Me = {
  user: { id: 'u1', display_name: 'Alice', email: 'alice@example.com', role: 'owner' },
  tenant: { id: 't1', slug: 'alice', name: 'Alice’s kitchen' },
  csrf_token: 'csrf',
  passkeys: 1,
  recovery_session: false,
};

describe('App', () => {
  beforeEach(() => localStorage.clear());
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
  });

  it('renders the bare layout while signed out', async () => {
    const fixture = TestBed.createComponent(App);
    TestBed.inject(HttpTestingController).expectOne('/api/v1/health').flush({ status: 'ok', version: '0.1.0.dev0', checks: {} });
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('nav.rail')).toBeNull();
    expect(el.querySelector('main.bare')).not.toBeNull();
  });

  it('shows the navigation rail, the tenant and the API version when signed in', async () => {
    TestBed.inject(AuthService).me.set(me);
    const fixture = TestBed.createComponent(App);
    TestBed.inject(HttpTestingController).expectOne('/api/v1/health').flush({ status: 'ok', version: '0.1.0.dev0', checks: {} });
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('h1')?.textContent).toContain('Victus');
    expect(el.textContent).toContain('Alice’s kitchen');
    expect(el.querySelectorAll('nav.rail li a').length).toBe(9);
    expect(el.querySelector('.health')?.textContent).toContain('0.1.0.dev0');
  });

  it('nudges for a second passkey when only one is registered', async () => {
    TestBed.inject(AuthService).me.set(me);
    const fixture = TestBed.createComponent(App);
    TestBed.inject(HttpTestingController).expectOne('/api/v1/health').flush({ status: 'ok', version: 'x', checks: {} });
    await fixture.whenStable();
    expect((fixture.nativeElement as HTMLElement).querySelector('.passkey-nudge')).not.toBeNull();

    TestBed.inject(AuthService).me.set({ ...me, passkeys: 2 });
    await fixture.whenStable();
    expect((fixture.nativeElement as HTMLElement).querySelector('.passkey-nudge')).toBeNull();
  });

  it('hides navigation and explains the restriction in a recovery session', async () => {
    TestBed.inject(AuthService).me.set({ ...me, passkeys: 0, recovery_session: true });
    const fixture = TestBed.createComponent(App);
    TestBed.inject(HttpTestingController).expectOne('/api/v1/health').flush({ status: 'ok', version: 'x', checks: {} });
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelectorAll('nav.rail li a').length).toBe(0);
    expect(el.querySelector('.recovery-notice')).not.toBeNull();
    expect(el.querySelector('.passkey-nudge')).toBeNull();
  });

  it('shows an error when the API is unreachable', async () => {
    TestBed.inject(AuthService).me.set(me);
    const fixture = TestBed.createComponent(App);
    TestBed.inject(HttpTestingController).expectOne('/api/v1/health').error(new ProgressEvent('error'));
    await fixture.whenStable();
    expect((fixture.nativeElement as HTMLElement).querySelector('.health .dot.bad')).not.toBeNull();
  });
});
