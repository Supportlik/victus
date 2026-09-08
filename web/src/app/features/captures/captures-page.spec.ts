// T-WEB-032: captures page renders transcript and image, re-targets a capture, discards it,
// and reports a duplicate upload as a notice instead of a new row.
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { Capture } from '../../api';
import { CapturesPage } from './captures-page';

const captures: Capture[] = [
  { id: 'c_audio', kind: 'audio', captured_at: '2026-01-05T07:41:00Z', target_date: null, status: 'new', transcript: 'a whole tub of skyr', attachment_id: 'att1', attachment_mime: 'audio/ogg' },
  { id: 'c_img', kind: 'image', captured_at: '2026-01-05T19:02:00Z', target_date: '2026-01-05', status: 'assigned', attachment_id: 'att2', attachment_mime: 'image/jpeg' },
];

function buttonWithText(root: Element, text: string): HTMLButtonElement {
  const found = Array.from(root.querySelectorAll('button')).find((b) => b.textContent?.includes(text));
  if (!found) throw new Error(`no button containing "${text}"`);
  return found;
}

describe('CapturesPage', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CapturesPage],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
  });

  async function render() {
    const fixture = TestBed.createComponent(CapturesPage);
    await fixture.whenStable();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne((r) => r.url === '/api/v1/captures').flush(captures);
    await fixture.whenStable();
    return { fixture, http, el: fixture.nativeElement as HTMLElement };
  }

  it('renders transcript, audio player and image thumbnail', async () => {
    const { el } = await render();
    const audioRow = el.querySelector('[data-capture="c_audio"]')!;
    expect(audioRow.textContent).toContain('a whole tub of skyr');
    expect(audioRow.querySelector('audio')?.getAttribute('src')).toBe('/api/v1/attachments/att1');
    expect(el.querySelector('[data-capture="c_img"] img')?.getAttribute('src')).toBe('/api/v1/attachments/att2');
    // an assigned capture offers no set-day/discard buttons; only new/failed ones do
    expect(el.querySelector('[data-capture="c_img"] .actions button')).toBeNull();
  });

  it('re-targets a new capture to a day', async () => {
    const { fixture, http, el } = await render();
    const row = el.querySelector('[data-capture="c_audio"]')!;
    buttonWithText(row, 'Set day').click();
    await fixture.whenStable();
    fixture.componentInstance.pendingDate = '2026-01-05';
    buttonWithText(row, 'Save').click();
    const req = http.expectOne('/api/v1/captures/c_audio');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ target_date: '2026-01-05' });
    req.flush({ ...captures[0], target_date: '2026-01-05' });
    await fixture.whenStable();
    expect(el.querySelector('[data-capture="c_audio"] a[href="/days/2026-01-05"]')).not.toBeNull();
  });

  it('discards a capture', async () => {
    const { fixture, http, el } = await render();
    buttonWithText(el.querySelector('[data-capture="c_audio"]')!, 'Discard').click();
    const req = http.expectOne('/api/v1/captures/c_audio');
    expect(req.request.body).toEqual({ status: 'discarded' });
    req.flush({ ...captures[0], status: 'discarded' });
    await fixture.whenStable();
    expect(el.querySelector('[data-capture="c_audio"] .v-tag')?.textContent).toContain('discarded');
  });

  it('shows a notice when an upload was a duplicate', async () => {
    const { fixture, http, el } = await render();
    fixture.componentInstance.text = 'lunch: skyr';
    fixture.componentInstance.upload();
    const req = http.expectOne('/api/v1/captures');
    expect(req.request.method).toBe('POST');
    req.flush({ ...captures[0], id: 'c_dup', kind: 'text', created: false });
    http.expectOne((r) => r.url === '/api/v1/captures').flush(captures);
    await fixture.whenStable();
    expect(el.querySelector('.v-notice')?.textContent).toContain('already exists');
  });
});
