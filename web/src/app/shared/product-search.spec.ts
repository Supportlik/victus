// T-WEB-002: product search debounces 300 ms and sends one request per pause.
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ProductSearch } from './product-search';

describe('ProductSearch', () => {
  beforeEach(async () => {
    vi.useFakeTimers();
    await TestBed.configureTestingModule({
      imports: [ProductSearch],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
  });
  afterEach(() => vi.useRealTimers());

  it('issues a single request after typing pauses and emits the picked product', async () => {
    const fixture = TestBed.createComponent(ProductSearch);
    const http = TestBed.inject(HttpTestingController);
    const picked: unknown[] = [];
    fixture.componentInstance.picked.subscribe((p) => picked.push(p));

    fixture.componentInstance.query.setValue('q');
    fixture.componentInstance.query.setValue('qu');
    fixture.componentInstance.query.setValue('qua');
    vi.advanceTimersByTime(100);
    http.expectNone((r) => r.url === '/api/v1/products');
    fixture.componentInstance.query.setValue('quark');
    vi.advanceTimersByTime(300);

    const req = http.expectOne((r) => r.url === '/api/v1/products');
    expect(req.request.params.get('q')).toBe('quark');
    req.flush([{ id: 1, name: 'Skyr natural', reference_amount: 100, reference_unit: 'g', verified: true, kcal: 63, protein: 11 }]);
    fixture.detectChanges();
    await fixture.whenStable();

    const hit = (fixture.nativeElement as HTMLElement).querySelector('button.hit') as HTMLButtonElement;
    expect(hit?.textContent).toContain('Skyr natural');
    hit.click();
    expect(picked.length).toBe(1);
    http.verify();
  });
});
