// T-WEB-001: day view renders meals, totals, ⚠️ on estimates, draft tint and band gauges from a fixture.
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { DayLog } from '../../api';
import { DayView } from './day-view';

const band = { min: 105, opt_min: 150, opt_max: 185, target: 165, max: 200, stretch: 185 };
const day: DayLog = {
  date: '2026-01-02',
  status: 'open',
  reliable: true,
  training_type: 'rest',
  macros: { kcal: 1383, protein: 154.9, carbs: 116.6, fat: 28.4, fiber: 12.3, salt: 7.25 },
  target_band: {
    id: 1, name: 'Rest day', training_type: 'rest', valid_from: '2026-01-01', valid_until: null,
    protein: band, carbs: { min: 120, opt_min: 155, opt_max: 200, target: 180, max: 230 },
    fat: { min: 45, opt_min: 55, opt_max: 70, target: 58, max: 75 }, fiber: { min: 25, opt_min: 32, opt_max: 38, target: 35, max: 50 },
    salt: { min: 4, opt_min: 6, opt_max: 8, target: 7, max: 15 },
  },
  zones: { protein: 'optimal', fiber: 'below_min', kcal: 'optimal' },
  findings: [],
  meals: [
    {
      id: 1, position: 1, name: 'Breakfast', time: '07:40', totals: { kcal: 252, protein: 44 },
      line_items: [
        { id: 11, meal_id: 1, position: 1, consumable_id: 5, consumable_name: 'Skyr natural', consumable_kind: 'product', amount: 400, unit_code: 'g', base_amount: 400, base_unit: 'g', estimated: false, amount_estimated: false, is_draft: false, kcal: 252, protein: 44 },
        { id: 12, meal_id: 1, position: 2, consumable_id: 9, consumable_name: 'Paprika chicken', consumable_kind: 'product', amount: 396, unit_code: 'g', base_amount: 396, base_unit: 'g', estimated: true, amount_estimated: true, is_draft: true, kcal: 420, protein: 67 },
      ],
    },
  ],
};

describe('DayView', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DayView],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
  });

  async function render() {
    const fixture = TestBed.createComponent(DayView);
    fixture.componentRef.setInput('date', '2026-01-02');
    await fixture.whenStable();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/api/v1/units').flush([{ code: 'g', singular: 'g', plural: 'g', unit_type: 'mass' }]);
    http.expectOne('/api/v1/days/2026-01-02').flush(day);
    await fixture.whenStable();
    // The thread panel mounts once the day is loaded and then asks for its messages.
    http.expectOne('/api/v1/days/2026-01-02/messages').flush([]);
    await fixture.whenStable();
    return fixture;
  }

  it('renders meals, items and totals', async () => {
    const fixture = await render();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.meal h3')?.textContent).toContain('Breakfast');
    expect(el.querySelectorAll('.meal tbody tr:not(.total)').length).toBe(2);
    expect(el.querySelector('tr.total')?.textContent).toContain('252');
  });

  it('marks estimated items with ⚠️ and drafts with a tag', async () => {
    const el = (await render()).nativeElement as HTMLElement;
    const rows = el.querySelectorAll('.meal tbody tr');
    expect(rows[0].textContent).not.toContain('⚠️');
    expect(rows[1].textContent).toContain('⚠️');
    expect(rows[1].classList.contains('draft')).toBe(true);
    expect(rows[1].querySelector('.v-tag.draft')?.textContent).toContain('draft');
  });

  it('shows one gauge per macro with the server zone colour', async () => {
    const el = (await render()).nativeElement as HTMLElement;
    const gauges = el.querySelectorAll('v-band-gauge');
    expect(gauges.length).toBe(6);
    const protein = gauges[1];
    expect(protein.querySelector('.value')?.classList.contains('ok')).toBe(true);
    const fiber = gauges[4];
    expect(fiber.querySelector('.value')?.classList.contains('bad')).toBe(true);
    expect(protein.querySelector('.strip')?.getAttribute('aria-label')).toContain('in the optimal range');
  });

  it('shows "Create this day" on 404 and posts reliable + training_type', async () => {
    const fixture = TestBed.createComponent(DayView);
    fixture.componentRef.setInput('date', '2026-01-03');
    await fixture.whenStable();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/api/v1/units').flush([]);
    http.expectOne('/api/v1/days/2026-01-03').flush({ title: 'Not found' }, { status: 404, statusText: 'Not Found' });
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.create-day')).not.toBeNull();
    expect(el.querySelector('.v-error')).toBeNull();

    fixture.componentInstance.newReliable = 'false';
    fixture.componentInstance.newTraining = 'strength';
    fixture.componentInstance.createDay();
    const req = http.expectOne('/api/v1/days/2026-01-03');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ reliable: false, training_type: 'strength' });
    req.flush({ ...day, date: '2026-01-03', reliable: false, training_type: 'strength', meals: [] });
    await fixture.whenStable();
    http.expectOne('/api/v1/days/2026-01-03/messages').flush([]);
    await fixture.whenStable();
    expect(el.querySelector('.create-day')).toBeNull();
    expect(el.querySelector('.gauges')).not.toBeNull();
  });

  it('offers "Close day" for an open day and posts to /close', async () => {
    const fixture = await render();
    const el = fixture.nativeElement as HTMLElement;
    const btn = [...el.querySelectorAll('button')].find((b) => b.textContent?.includes('Close day'));
    expect(btn).toBeDefined();
    btn!.click();
    const req = TestBed.inject(HttpTestingController).expectOne('/api/v1/days/2026-01-02/close');
    expect(req.request.method).toBe('POST');
    req.flush({ ...day, status: 'closed' });
    await fixture.whenStable();
    expect(el.querySelector('v-status-tag')?.textContent).toContain('Closed');
  });
});
