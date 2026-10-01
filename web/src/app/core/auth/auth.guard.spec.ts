// T-WEB-360, T-WEB-361: the route guard lets a signed-in session through and sends
// everyone else to the login page, remembering where they wanted to go.
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, provideRouter, RouterStateSnapshot, UrlTree } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { Me } from '../../api';
import { authGuard } from './auth.guard';

const me: Me = {
  user: { id: 'u1', display_name: 'Alice', email: 'alice@example.com', role: 'owner' },
  tenant: { id: 't1', slug: 'alice', name: 'Alice' },
  csrf_token: 'csrf-1',
  passkeys: 2,
  recovery_session: false,
};

function run(url: string): Promise<boolean | UrlTree> {
  return TestBed.runInInjectionContext(
    () =>
      authGuard({} as ActivatedRouteSnapshot, { url } as RouterStateSnapshot) as Promise<boolean | UrlTree>,
  );
}

describe('authGuard', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('T-WEB-360: lets the route open once /auth/me answers with a session', async () => {
    const result = run('/weight');
    http.expectOne('/api/v1/auth/me').flush(me);
    expect(await result).toBe(true);
  });

  it('T-WEB-361: sends a signed-out visitor to /login with the page they asked for', async () => {
    const result = run('/days/2026-09-12');
    http
      .expectOne('/api/v1/auth/me')
      .flush({ title: 'Unauthorized' }, { status: 401, statusText: 'Unauthorized' });
    const tree = (await result) as UrlTree;
    expect(tree).toBeInstanceOf(UrlTree);
    expect(tree.toString()).toBe('/login?returnUrl=%2Fdays%2F2026-09-12');
  });

  it('T-WEB-361: an API that is down reads as signed out, not as an open door', async () => {
    const result = run('/reports');
    http.expectOne('/api/v1/auth/me').error(new ProgressEvent('error'));
    expect(((await result) as UrlTree).toString()).toBe('/login?returnUrl=%2Freports');
  });
});
