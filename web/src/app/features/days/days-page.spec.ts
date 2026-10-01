// T-WEB-414: the day list asks for the last four weeks, sorts newest first, flags missing and
// estimated reliability, refetches when the status filter changes, and shows the API's
// refusal.
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { DaySummary } from '../../api';
import { DaysPage } from './days-page';

const MACROS = { kcal: 1800, protein: 120, carbs: 180, fat: 60, fiber: 30, salt: 5 };
const DAYS: DaySummary[] = [
  { date: '2026-03-01', status: 'closed', reliable: true, training_type: 'rest', macros: MACROS, weight_kg: 80.4 },
  { date: '2026-03-03', status: 'open', reliable: null, training_type: null, macros: MACROS, has_drafts: true },
  { date: '2026-03-02', status: 'draft', reliable: false, training_type: null, macros: MACROS, has_drafts: true },
];

describe('DaysPage', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DaysPage],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  function expectList(): TestRequest {
    const req = http.expectOne((r) => r.url === '/api/v1/days');
    expect(req.request.method).toBe('GET');
    return req;
  }

  it('T-WEB-414: lists days newest first with their flags', async () => {
    const fixture = TestBed.createComponent(DaysPage);
    const req = expectList();
    const page = fixture.componentInstance;
    expect(req.request.params.get('from')).toBe(page.from());
    expect(req.request.params.get('to')).toBe(page.today);
    expect(req.request.params.has('status')).toBe(false);
    expect(page.loading()).toBe(true);
    req.flush(DAYS);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const rows = [...el.querySelectorAll('tbody tr')];
    expect(rows.map((r) => r.querySelector('a')?.getAttribute('href'))).toEqual([
      '/days/2026-03-03',
      '/days/2026-03-02',
      '/days/2026-03-01',
    ]);
    expect(rows[0].textContent).toContain('flag missing');
    expect(rows[0].textContent).toContain('items');
    expect(rows[1].textContent).toContain('estimated day');
    expect(rows[2].textContent).toContain('80.4');
    expect(page.count()).toBe(3);
    expect(page.loading()).toBe(false);
  });

  it('T-WEB-414: an empty range offers today, and a status filter is sent', async () => {
    const fixture = TestBed.createComponent(DaysPage);
    expectList().flush([]);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.v-empty')?.textContent).toContain('No days in this range yet.');
    expect(el.querySelector('.v-empty a')?.getAttribute('href')).toBe(`/days/${fixture.componentInstance.today}`);

    const select = el.querySelector('select') as HTMLSelectElement;
    select.value = 'draft';
    select.dispatchEvent(new Event('change'));
    const filtered = expectList();
    expect(filtered.request.params.get('status')).toBe('draft');
    filtered.flush([DAYS[2]]);
    fixture.detectChanges();
    expect(el.querySelectorAll('tbody tr').length).toBe(1);
  });

  it('T-WEB-414: a refused list shows the problem detail', async () => {
    const fixture = TestBed.createComponent(DaysPage);
    expectList().flush(
      { title: 'Forbidden', detail: 'scope read required' },
      { status: 403, statusText: 'Forbidden' },
    );
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.v-error')?.textContent).toContain('scope read required');
    expect(fixture.componentInstance.loading()).toBe(false);
  });
});
