// T-WEB-043: body measurements sit with the weight, and the chart shades the BMI classes
// once a height is known (R76).
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideEchartsCore } from 'ngx-echarts';
import { beforeEach, describe, expect, it } from 'vitest';
import { WeightPage } from './weight-page';

const WEIGHT = [
  { id: 1, measured_at: '2026-09-01T07:00:00Z', kg: 96.4, source: 'scale_sync' },
  { id: 2, measured_at: '2026-09-02T07:00:00Z', kg: 96.0, source: 'manual' },
];
const BODY = [
  { id: 5, measured_at: '2026-08-07T08:00:00Z', waist_cm: 132.3, hip_cm: 126.5, source: 'manual' },
  { id: 6, measured_at: '2026-09-07T08:00:00Z', waist_cm: 126.4, hip_cm: 118.1, source: 'manual' },
];

function answer(http: HttpTestingController, settings: Record<string, unknown>): void {
  http.match((r) => r.url === '/api/v1/weight').forEach((r) => r.flush(WEIGHT));
  http.match((r) => r.url === '/api/v1/body-measurements').forEach((r) => r.flush(BODY));
  http.match((r) => r.url === '/api/v1/settings').forEach((r) =>
    r.flush({ version: 1, valid_from: '2026-01-01', data: settings }),
  );
  http.match(() => true).forEach((r) => r.flush([]));
}

describe('WeightPage', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideEchartsCore({ echarts: () => import('echarts') }),
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  it('lists the measurements newest first and only sends what was filled in', async () => {
    const f = TestBed.createComponent(WeightPage);
    f.detectChanges();
    answer(http, { body: { height_cm: 170 } });
    f.detectChanges();
    await f.whenStable();

    const el = f.nativeElement as HTMLElement;
    const rows = el.querySelectorAll('.body-log tbody tr');
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain('2026-09-07'), 'newest first';
    // an unmeasured circumference shows as a dash, not as zero
    expect(rows[0].textContent).toContain('–');

    // nothing to send while the form is empty
    expect(f.componentInstance.anyBodyValue()).toBe(false);
    f.componentInstance.bodyAt = '2026-09-09T08:00';
    f.componentInstance.body.waist_cm = 125.8;
    expect(f.componentInstance.anyBodyValue()).toBe(true);
    f.componentInstance.addBody();

    const req = http.expectOne('/api/v1/body-measurements');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toMatchObject({ waist_cm: 125.8, hip_cm: null, body_fat_pct: null });
    req.flush({ id: 7, measured_at: '2026-09-09T08:00:00Z', waist_cm: 125.8, source: 'manual' });
    answer(http, { body: { height_cm: 170 } });
  });

  it('shades the BMI classes only when a height is known', async () => {
    const withHeight = TestBed.createComponent(WeightPage);
    withHeight.detectChanges();
    answer(http, { body: { height_cm: 170 } });
    withHeight.detectChanges();
    await withHeight.whenStable();
    const area = (withHeight.componentInstance.chart().series as { markArea?: unknown }[])[0].markArea as
      | { data: unknown[] }
      | undefined;
    expect(area?.data.length).toBe(6), 'one band per WHO class';

    // without a height there is nothing to draw, and the chart still renders
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideEchartsCore({ echarts: () => import('echarts') }),
      ],
    });
    const http2 = TestBed.inject(HttpTestingController);
    const without = TestBed.createComponent(WeightPage);
    without.detectChanges();
    answer(http2, {});
    without.detectChanges();
    await without.whenStable();
    const none = (without.componentInstance.chart().series as { markArea?: unknown }[])[0].markArea;
    expect(none).toBeUndefined();
  });
});
