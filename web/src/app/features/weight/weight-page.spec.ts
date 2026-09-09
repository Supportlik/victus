// T-WEB-043: body measurements sit with the weight, and the chart shades the BMI classes
// once a height is known (R76).
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideEchartsCore } from 'ngx-echarts';
import { beforeEach, describe, expect, it } from 'vitest';
import { FormatService } from '../../core/format.service';
import { I18nService } from '../../core/i18n.service';
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

  it('puts the measures in rows and the sessions in columns, and only sends what was filled in', async () => {
    const f = TestBed.createComponent(WeightPage);
    f.detectChanges();
    answer(http, { body: { height_cm: 170 } });
    f.detectChanges();
    await f.whenStable();

    const el = f.nativeElement as HTMLElement;
    const format = TestBed.inject(FormatService);

    // sessions across the top, newest first
    const heads = [...el.querySelectorAll('.body-log thead th.session')];
    expect(heads.length).toBe(2);
    expect(heads[0].textContent).toContain(format.day('2026-09-07')), 'newest first';
    expect(heads[1].textContent).toContain(format.day('2026-08-07'));
    // a session is still removable, from its own column head
    expect(heads[0].querySelector('button.danger')).toBeTruthy();

    // only the taped measures get a row; belly, chest, neck, thigh, arm and fat are absent
    const rows = [...el.querySelectorAll('.body-log tbody tr')];
    expect(rows.map((r) => r.querySelector('.what')?.textContent?.trim().split(' ')[0])).toEqual(['Waist', 'Hip']);

    // the newest value leads the row, and the change reads as a shrink
    const waist = [...rows[0].querySelectorAll('td')].map((c) => c.textContent!.trim());
    expect(waist[0]).toBe(format.number(126.4, 1));
    expect(waist[1]).toBe(format.number(132.3, 1));
    expect(waist[2]).toBe(`−${format.number(5.9, 1)}`);
    expect(rows[0].querySelector('td.down')).toBeTruthy(), 'a smaller waist is an improvement';

    // an unmeasured value shows a dash, not a zero
    expect(el.querySelector('.body-log tbody')!.textContent).not.toContain(format.number(0, 1));
    f.componentInstance.measurements.update((m) => [{ ...m[0], hip_cm: null }, ...m.slice(1)]);
    f.detectChanges();
    const hip = [...el.querySelectorAll('.body-log tbody tr')[1].querySelectorAll('td')].map((c) => c.textContent!.trim());
    expect(hip[0]).toBe('–'), 'missing value, not zero';
    expect(hip[2]).toBe('–'), 'and no change can be worked out from a gap';

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
    // T-WEB-047: the names are the domain's own (body.py::BMI_BANDS), so the dictionary
    // has an entry for each. A second spelling, "obesity III", had none and stayed English.
    const i18n = TestBed.inject(I18nService);
    i18n.adopt('de');
    withHeight.detectChanges();
    const german = (withHeight.componentInstance.chart().series as { markArea?: unknown }[])[0]
      .markArea as { data: unknown[] } | undefined;
    const named = (german?.data ?? []).map((pair) => (pair as { name?: string }[])[0].name);
    expect(named).toContain('Adipositas Grad III'), 'the German reader gets German';
    expect(named).toEqual([
      'underweight',
      'normal weight',
      'overweight',
      'obesity class I',
      'obesity class II',
      'obesity class III',
    ].map((key) => i18n.t(key)));

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
