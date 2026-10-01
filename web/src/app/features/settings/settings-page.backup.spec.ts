// T-WEB-155: the System panel of the settings page shows the backup state from /health.
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { Health } from '../../api';
import { I18nService } from '../../core/i18n.service';
import { SettingsPage } from './settings-page';

const NEVER: Health = {
  status: 'degraded',
  version: '1.7.0',
  checks: { process: 'ok', db: 'ok', migrations: 'ok', storage: 'ok', backup: 'degraded' },
  backup_age_hours: null,
  backup_last_at: null,
  backup_max_age_hours: 30,
};

describe('SettingsPage backup', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    TestBed.inject(I18nService).adopt('en');
  });
  afterEach(() => {
    http.match(() => true).forEach((r) => r.flush([]));
    TestBed.inject(I18nService).adopt('en');
  });

  function answerAllBut(health: (r: ReturnType<HttpTestingController['expectOne']>) => void): void {
    health(http.expectOne('/api/v1/health'));
    http.match((r) => r.url === '/api/v1/settings').forEach((r) => r.flush({ version: 1, valid_from: '2026-01-01', data: {} }));
    http.match((r) => r.url !== '/api/v1/backup/jobs').forEach((r) => r.flush([]));
  }

  it('shows the degraded backup check, "never" and the pointer to the docs', async () => {
    const f = TestBed.createComponent(SettingsPage);
    f.detectChanges();
    answerAllBut((r) => r.flush(NEVER));
    f.detectChanges();
    // the backup block asks for its list once it is on screen
    http.expectOne((r) => r.url === '/api/v1/backup/jobs').flush([]);
    f.detectChanges();
    await f.whenStable();

    const el = f.nativeElement as HTMLElement;
    const checks = [...el.querySelectorAll('dl.sys > div')].map((d) => d.textContent?.trim());
    expect(checks).toContain('backupdegraded');
    const status = el.querySelector('v-backup-status');
    expect(status).toBeTruthy();
    expect(status?.querySelector('.last .age')?.textContent?.trim()).toBe('never');
    expect(status?.querySelector('.hint code')?.textContent).toBe('docs/BACKUP.md');
  });

  it('shows neither the backup block nor asks for jobs when /health fails', async () => {
    const f = TestBed.createComponent(SettingsPage);
    f.detectChanges();
    answerAllBut((r) => r.flush({ title: 'Bad gateway' }, { status: 502, statusText: 'Bad Gateway' }));
    f.detectChanges();
    await f.whenStable();

    const el = f.nativeElement as HTMLElement;
    expect(el.textContent).toContain('API health unavailable.');
    expect(el.querySelector('v-backup-status')).toBeNull();
    http.expectNone((r) => r.url === '/api/v1/backup/jobs');
  });
});
