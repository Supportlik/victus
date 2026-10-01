// T-WEB-150: ApiClient — the backup jobs list and the backup fields of /health.
import { provideHttpClient } from '@angular/common/http';
import { HttpErrorResponse } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ApiClient } from './api-client';
import { BackupJob, Health } from './models';

const JOB: BackupJob = {
  id: 'j1',
  tenant_id: null,
  started_at: '2026-09-15T03:00:00Z',
  finished_at: '2026-09-15T03:00:00Z',
  status: 'finished',
  path: '/mnt/backup/victus-data.tar.gpg',
  size: 123_456_789,
  verified: false,
  error: null,
};

describe('ApiClient backup', () => {
  let api: ApiClient;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    api = TestBed.inject(ApiClient);
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  it('lists backup jobs with GET /backup/jobs and an optional limit', () => {
    let got: BackupJob[] = [];
    api.backupJobs(5).subscribe((j) => (got = j));
    const req = http.expectOne((r) => r.url === '/api/v1/backup/jobs');
    expect(req.request.method).toBe('GET');
    expect(req.request.params.get('limit')).toBe('5');
    req.flush([JOB]);
    expect(got).toEqual([JOB]);

    api.backupJobs().subscribe();
    const plain = http.expectOne((r) => r.url === '/api/v1/backup/jobs');
    expect(plain.request.params.has('limit')).toBe(false);
    plain.flush([]);
  });

  it('hands a refusal to the caller as an HttpErrorResponse with its status', () => {
    let status = 0;
    api.backupJobs(5).subscribe({ error: (e: unknown) => (status = e instanceof HttpErrorResponse ? e.status : -1) });
    http
      .expectOne((r) => r.url === '/api/v1/backup/jobs')
      .flush({ title: 'Forbidden', status: 403, detail: "scope 'admin' required" }, { status: 403, statusText: 'Forbidden' });
    expect(status).toBe(403);
  });

  it('reads the backup fields of GET /health', () => {
    let got: Health | null = null;
    api.health().subscribe((h) => (got = h));
    const body: Health = {
      status: 'degraded',
      version: '1.7.0',
      checks: { process: 'ok', backup: 'degraded' },
      backup_age_hours: null,
      backup_last_at: null,
      backup_max_age_hours: 30,
    };
    http.expectOne('/api/v1/health').flush(body);
    expect(got).toEqual(body);
  });
});
