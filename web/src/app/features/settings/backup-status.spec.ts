// T-WEB-151…154: the last backup on the settings page — never, fresh, stale, and the
// list of recent backups with its refusal and failure paths.
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { BackupJob, Health } from '../../api';
import { FormatService } from '../../core/format.service';
import { I18nService } from '../../core/i18n.service';
import { BackupStatus, RECENT_BACKUPS } from './backup-status';

const NEVER: Health = {
  status: 'degraded',
  version: '1.7.0',
  checks: { process: 'ok', db: 'ok', backup: 'degraded' },
  backup_age_hours: null,
  backup_last_at: null,
  backup_max_age_hours: 30,
};
const FRESH: Health = {
  ...NEVER,
  status: 'ok',
  checks: { process: 'ok', db: 'ok', backup: 'ok' },
  backup_age_hours: 2.5,
  backup_last_at: '2026-09-15T03:00:00Z',
};
const STALE: Health = { ...NEVER, backup_age_hours: 41.2, backup_last_at: '2026-09-13T19:00:00Z', backup_max_age_hours: 36 };

const JOBS: BackupJob[] = [
  {
    id: 'j2',
    tenant_id: null,
    started_at: '2026-09-15T03:00:00Z',
    finished_at: '2026-09-15T03:00:00Z',
    status: 'finished',
    path: '/mnt/backup/victus-data.tar.gpg',
    size: 123_456_789,
    verified: false,
    error: null,
  },
  {
    id: 'j1',
    tenant_id: null,
    started_at: '2026-09-14T03:00:00Z',
    finished_at: '2026-09-14T03:00:02Z',
    status: 'failed',
    path: '/mnt/backup/victus-data.tar.gpg',
    size: null,
    verified: false,
    error: 'tar: no space left on device',
  },
  {
    id: 'j0',
    tenant_id: null,
    started_at: '2026-09-13T03:00:00Z',
    finished_at: '2026-09-13T03:01:00Z',
    status: 'verify_failed',
    path: '/backups/victus-all-20260913T030000Z.zip',
    size: 2_000_000,
    verified: false,
    error: 'verification failed: day_log',
  },
];

describe('BackupStatus', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    TestBed.inject(I18nService).adopt('en');
    TestBed.inject(FormatService).adopt('en-GB', 'UTC');
  });
  afterEach(() => {
    http.verify();
    TestBed.inject(I18nService).adopt('en');
  });

  async function render(health: Health, answer: (req: ReturnType<HttpTestingController['expectOne']>) => void) {
    const f = TestBed.createComponent(BackupStatus);
    f.componentRef.setInput('health', health);
    f.detectChanges();
    const req = http.expectOne((r) => r.url === '/api/v1/backup/jobs');
    expect(req.request.params.get('limit')).toBe(String(RECENT_BACKUPS));
    answer(req);
    f.detectChanges();
    await f.whenStable();
    return f.nativeElement as HTMLElement;
  }

  it('T-WEB-151: says "never" and where to read up when Victus knows of no backup', async () => {
    const el = await render(NEVER, (r) => r.flush([]));
    expect(el.querySelector('.last .age')?.textContent?.trim()).toBe('never');
    const hint = el.querySelector('.hint');
    expect(hint?.textContent).toContain('Victus knows of no backup of this instance');
    expect(hint?.textContent).toContain('victus backup record');
    expect(hint?.querySelector('code')?.textContent).toBe('docs/BACKUP.md');
    expect(el.querySelector('.backup')?.classList.contains('warn')).toBe(true);
    expect(el.querySelector('table.jobs')).toBeNull();
  });

  it('T-WEB-152: a fresh backup shows its age and time, no warning, and the recent jobs', async () => {
    const format = TestBed.inject(FormatService);
    const el = await render(FRESH, (r) => r.flush(JOBS));
    expect(el.querySelector('.last .age')?.textContent?.trim()).toBe('2.5 h ago');
    expect(el.querySelector('.last .at')?.textContent).toContain(format.moment('2026-09-15T03:00:00Z'));
    expect(el.querySelector('.hint')).toBeNull();
    expect(el.querySelector('.backup')?.classList.contains('warn')).toBe(false);
    const rows = [...el.querySelectorAll('table.jobs tbody tr')];
    expect(rows.length).toBe(3);
    expect(rows[0].textContent).toContain('finished');
    expect(rows[0].textContent).toContain('/mnt/backup/victus-data.tar.gpg');
    expect(rows[0].textContent).toContain('123.5 MB');
    expect(rows[0].classList.contains('bad')).toBe(false);
    expect(rows[1].classList.contains('bad')).toBe(true);
    expect(rows[1].textContent).toContain('failed');
    expect(rows[1].textContent).toContain('tar: no space left on device');
    expect(rows[1].querySelector('td.num')?.textContent?.trim()).toBe('–');
    expect(rows[2].textContent).toContain('verification failed');
  });

  it('T-WEB-156: a small archive reads in kilobytes, not as 0.0 MB', async () => {
    const small: BackupJob[] = [{ ...JOBS[0], size: 4096 }, { ...JOBS[0], id: 'b9', size: 512 }];
    const el = await render(FRESH, (r) => r.flush(small));
    const cells = [...el.querySelectorAll('table.jobs tbody td.num')].map((c) => c.textContent?.trim());
    expect(cells).toEqual(['4.1 KB', '0.5 KB']);
  });

  it('T-WEB-153: a stale backup shows its age and names the configured limit', async () => {
    const el = await render(STALE, (r) => r.flush([]));
    expect(el.querySelector('.last .age')?.textContent?.trim()).toBe('41.2 h ago');
    const hint = el.querySelector('.hint')?.textContent ?? '';
    expect(hint).toContain('The newest backup is older than 36 h.');
    expect(hint).not.toContain('knows of no backup');
    expect(el.querySelector('.hint code')?.textContent).toBe('docs/BACKUP.md');
  });

  it('T-WEB-154: without admin the list is left out quietly; a failure says so', async () => {
    let el = await render(FRESH, (r) =>
      r.flush({ title: 'Forbidden', status: 403, detail: "scope 'admin' required" }, { status: 403, statusText: 'Forbidden' }),
    );
    expect(el.querySelector('table.jobs')).toBeNull();
    expect(el.textContent).not.toContain('Backup history unavailable.');
    expect(el.querySelector('.last .age')?.textContent?.trim()).toBe('2.5 h ago');

    el = await render(FRESH, (r) => r.flush({ title: 'Oops', status: 500 }, { status: 500, statusText: 'Server Error' }));
    expect(el.querySelector('table.jobs')).toBeNull();
    expect(el.textContent).toContain('Backup history unavailable.');
  });

  it('T-WEB-151: speaks the interface language', async () => {
    TestBed.inject(I18nService).adopt('de');
    const el = await render(NEVER, (r) => r.flush([]));
    expect(el.querySelector('.last .label')?.textContent).toBe('Letzte Sicherung');
    expect(el.querySelector('.last .age')?.textContent?.trim()).toBe('nie');
    expect(el.querySelector('.hint')?.textContent).toContain('Victus kennt keine Sicherung');
  });
});
