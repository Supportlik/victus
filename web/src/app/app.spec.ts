// T-WEB-006: app shell — bare login layout when signed out, navigation rail when signed in; health line reflects the API.
// T-WEB-005: passkey nudge shown with one passkey, hidden at two.
// T-WEB-072: the footer line keeps the page alive through an outage and heals itself.
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { afterEach } from 'vitest';
import { App } from './app';
import { AuthService } from './core/auth/auth.service';
import { LiveService } from './core/live.service';
import { Me } from './api';
import { MockEventSource } from '../testing/event-source.mock';

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
    expect(el.querySelectorAll('nav.rail li a').length).toBe(8);
    expect(el.querySelector('.health')?.textContent).toContain('0.1.0.dev0');
    // every entry carries a drawn icon, not a text glyph
    expect(el.querySelectorAll('nav.rail li a v-icon svg').length).toBe(8);
  });

  // T-WEB-037: on a phone the bar holds five entries; the rest wait behind More, so nothing
  // has to be scrolled sideways to be reached.
  it('puts the remaining entries behind More in the phone bar', async () => {
    TestBed.inject(AuthService).me.set(me);
    const fixture = TestBed.createComponent(App);
    TestBed.inject(HttpTestingController).expectOne('/api/v1/health').flush({ status: 'ok', version: 'x', checks: {} });
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    // Today plus four primary entries plus the More button
    expect(el.querySelectorAll('nav.tabs .tab').length).toBe(6);
    expect(el.querySelector('.sheet')).toBeNull();

    const more = Array.from(el.querySelectorAll('nav.tabs button.tab')).find((b) =>
      b.textContent?.includes('More'),
    ) as HTMLButtonElement;
    more.click();
    await fixture.whenStable();
    const sheet = (fixture.nativeElement as HTMLElement).querySelector('.sheet')!;
    expect(sheet.querySelectorAll('a').length).toBe(4);
    expect(sheet.textContent).toContain('Recipes');
    expect(sheet.textContent).toContain('Sign out');
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
    expect(el.querySelector('nav.tabs')).toBeNull();
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

  describe('with the change stream', () => {
    afterEach(() => {
      TestBed.inject(LiveService).stop();
      MockEventSource.restore();
    });

    /** Signed in, with the stream stubbed, and the health request still to be answered. */
    async function shell() {
      MockEventSource.install();
      TestBed.inject(AuthService).me.set(me);
      const fixture = TestBed.createComponent(App);
      await fixture.whenStable();
      return fixture;
    }

    // The line was fetched exactly once, so an outage stayed on screen for the rest of the
    // session — the page looked broken long after the API was back.
    it('says the API is unreachable, keeps the page, and heals when the stream stands', async () => {
      const fixture = await shell();
      const http = TestBed.inject(HttpTestingController);
      http.expectOne('/api/v1/health').error(new ProgressEvent('error'));
      await fixture.whenStable();

      const el = fixture.nativeElement as HTMLElement;
      expect(el.querySelector('.health .dot.bad')).not.toBeNull();
      expect(el.querySelector('.health')?.textContent).toContain('API unreachable');
      // nothing was taken away: the rail, the tenant and the routed view are all still here
      expect(el.querySelector('nav.rail')).not.toBeNull();
      expect(el.textContent).toContain('Alice’s kitchen');

      MockEventSource.last.emit('hello', {
        cursor: 3,
        counts: { new_captures: 0, draft_days: 0, open_days: 0, pending_proposals: 0 },
      });
      await fixture.whenStable();
      http.expectOne('/api/v1/health').flush({ status: 'ok', version: '1.5.1', checks: {} });
      await fixture.whenStable();
      expect(el.querySelector('.health')?.textContent).toContain('API 1.5.1');
      expect(el.querySelector('.health .dot.ok')).not.toBeNull();
    });

    it('reads as reconnecting once a stream that stood is away again', async () => {
      const fixture = await shell();
      const http = TestBed.inject(HttpTestingController);
      http.expectOne('/api/v1/health').flush({ status: 'ok', version: '1.5.1', checks: {} });
      await fixture.whenStable();
      const el = fixture.nativeElement as HTMLElement;

      const stream = MockEventSource.last;
      stream.emit('hello', {
        cursor: 1,
        counts: { new_captures: 0, draft_days: 0, open_days: 0, pending_proposals: 0 },
      });
      await fixture.whenStable();
      expect(el.querySelector('.health')?.textContent).toContain('API 1.5.1');

      stream.fail();
      await fixture.whenStable();
      expect(el.querySelector('.health')?.textContent).toContain('Reconnecting…');
      expect(el.querySelector('.health .dot.warn')).not.toBeNull();
      // the API itself never said anything: the version and the page stay exactly as they were
      expect(el.querySelector('nav.rail')).not.toBeNull();
      http.expectNone('/api/v1/health');
    });
  });
});
