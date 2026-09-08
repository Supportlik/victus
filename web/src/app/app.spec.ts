// T-WEB-001/002/003: app shell renders and reflects API health.
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { App } from './app';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
  });

  it('renders the title', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('h1')?.textContent).toContain('Victus');
  });

  it('shows the API version once /api/v1/health answers', async () => {
    const fixture = TestBed.createComponent(App);
    const httpMock = TestBed.inject(HttpTestingController);
    httpMock
      .expectOne('/api/v1/health')
      .flush({ status: 'ok', version: '0.1.0.dev0', checks: { process: 'ok' } });
    await fixture.whenStable();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.status.ok')?.textContent).toContain('0.1.0.dev0');
    httpMock.verify();
  });

  it('shows an error when the API is unreachable', async () => {
    const fixture = TestBed.createComponent(App);
    const httpMock = TestBed.inject(HttpTestingController);
    httpMock.expectOne('/api/v1/health').error(new ProgressEvent('error'));
    await fixture.whenStable();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.status.error')).not.toBeNull();
    httpMock.verify();
  });
});
