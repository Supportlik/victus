// T-WEB-418: the capture form's other paths — files in the tray go up with the text as one
// capture (for a product, without a day), a duplicate is reported instead of emitted, a
// refused upload shows the problem and keeps the tray, and a browser without camera or
// microphone says why.
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Capture } from '../api';
import { CaptureInput } from './capture-input';

const CAPTURE: Capture = {
  id: 'c1',
  kind: 'image',
  captured_at: '2026-01-05T12:00:00Z',
  target_date: null,
  text: 'label',
  status: 'new',
  transcript: null,
  attachment_id: 'a1',
  attachment_mime: 'image/png',
  attachments: [],
};

function addFiles(f: ComponentFixture<CaptureInput>, files: File[]): void {
  const input = (f.nativeElement as HTMLElement).querySelector('input[type="file"]') as HTMLInputElement;
  expect(input).toBeTruthy();
  Object.defineProperty(input, 'files', { configurable: true, value: files });
  input.dispatchEvent(new Event('change'));
  f.detectChanges();
}

describe('CaptureInput (tray, upload outcomes, media)', () => {
  let http: HttpTestingController;
  let f: ComponentFixture<CaptureInput>;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    f = TestBed.createComponent(CaptureInput);
    // jsdom's object URLs only take its own Blob; the tray only needs some URL back
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:preview');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
  });
  afterEach(() => {
    http.verify();
    vi.restoreAllMocks();
  });

  it('T-WEB-418: files and text go up as one capture for a product; the tray empties', () => {
    f.componentRef.setInput('productId', 7);
    f.componentRef.setInput('targetDate', '2026-01-05');
    f.detectChanges();
    const c = f.componentInstance;
    const emitted: Capture[] = [];
    c.uploaded.subscribe((x) => emitted.push(x));
    addFiles(f, [
      new File(['png'], 'label.png', { type: 'image/png' }),
      new File(['ogg'], 'note.ogg', { type: 'audio/ogg' }),
      new File(['pdf'], 'sheet.pdf', { type: 'application/pdf' }),
    ]);
    expect(c.pending().map((p) => p.kind)).toEqual(['image', 'audio', 'other']);
    expect(c.saveLabel()).toBe('Save capture (3 files)');
    c.drop(c.pending()[2]);
    expect(c.saveLabel()).toBe('Save capture (2 files)');
    c.drop(c.pending()[1]);
    expect(c.saveLabel()).toBe('Save capture (1 file)');
    expect(c.dirty()).toBe(true);
    c.onNote({ target: { value: '  new label  ' } } as unknown as Event);

    c.submit();
    expect(c.busy()).toBe(true);
    const req = http.expectOne('/api/v1/captures');
    expect(req.request.method).toBe('POST');
    const body = req.request.body as FormData;
    expect(body.get('product_id')).toBe('7');
    expect(body.get('target_date')).toBeNull();
    expect(body.get('text')).toBe('new label');
    expect(body.getAll('file')).toHaveLength(1);
    req.flush({ ...CAPTURE, created: true });
    expect(emitted.map((x) => x.id)).toEqual(['c1']);
    expect(c.pending()).toEqual([]);
    expect(c.busy()).toBe(false);
  });

  it('T-WEB-418: a duplicate is a notice, not an upload event', () => {
    f.detectChanges();
    const c = f.componentInstance;
    const emitted: Capture[] = [];
    c.uploaded.subscribe((x) => emitted.push(x));
    c.submit(); // empty: nothing is sent
    c.onNote({ target: { value: 'tea' } } as unknown as Event);
    c.submit();
    http.expectOne('/api/v1/captures').flush({ ...CAPTURE, created: false });
    expect(emitted).toEqual([]);
    expect(c.notice()).toContain('Already captured');
  });

  it('T-WEB-418: a refused upload shows the problem and keeps what was typed', () => {
    f.detectChanges();
    const c = f.componentInstance;
    c.onNote({ target: { value: 'tea' } } as unknown as Event);
    c.submit();
    http
      .expectOne('/api/v1/captures')
      .flush({ title: 'Payload too large', detail: 'the upload exceeds 50 MB', status: 413 }, { status: 413, statusText: 'Too Large' });
    expect(c.error()).toContain('the upload exceeds 50 MB');
    expect(c.note()).toBe('tea');
    expect(c.busy()).toBe(false);
    c.clear();
    expect(c.hasContent()).toBe(false);
  });

  it('T-WEB-418: camera and microphone refusals are explained', async () => {
    f.detectChanges();
    const c = f.componentInstance;
    const devices = (navigator as { mediaDevices?: unknown }).mediaDevices;
    try {
      Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: undefined });
      await c.takePhoto();
      expect(c.error()).toContain('no camera API');

      const denied = Object.assign(new Error('denied'), { name: 'NotAllowedError' });
      const missing = Object.assign(new Error('none'), { name: 'NotFoundError' });
      const busy = Object.assign(new Error('busy'), { name: 'NotReadableError' });
      const getUserMedia = vi.fn().mockRejectedValue(denied);
      Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } });
      await c.takePhoto();
      expect(c.error()).toContain('Camera blocked');
      expect(c.cameraOpen()).toBe(false);

      getUserMedia.mockRejectedValue(missing);
      await c.startRecording();
      expect(c.error()).toContain('No microphone found');
      getUserMedia.mockRejectedValue(busy);
      await c.startRecording();
      expect(c.error()).toContain('in use by another program');
      getUserMedia.mockRejectedValue(new Error('odd'));
      await c.startRecording();
      expect(c.error()).toBe('Microphone not available: odd.');

      const track = { stop: vi.fn() };
      getUserMedia.mockReset();
      getUserMedia.mockRejectedValueOnce(Object.assign(new Error('x'), { name: 'OverconstrainedError' }));
      getUserMedia.mockResolvedValueOnce({ getTracks: () => [track] });
      Object.defineProperty(navigator, 'mediaDevices', {
        configurable: true,
        value: { getUserMedia, enumerateDevices: vi.fn().mockResolvedValue([{ kind: 'videoinput' }, { kind: 'videoinput' }]) },
      });
      await c.takePhoto();
      expect(getUserMedia).toHaveBeenCalledTimes(2), 'a rejected constraint is retried bare';
      expect(c.cameraOpen()).toBe(true);
      await Promise.resolve();
      await Promise.resolve();
      expect(c.canSwitch()).toBe(true);
      c.shoot(false); // no video frame yet: nothing happens
      c.closeCamera();
      expect(track.stop).toHaveBeenCalled();
      expect(c.cameraOpen()).toBe(false);
      c.stopRecording();
      expect(c.recording()).toBe(false);
    } finally {
      Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: devices });
    }
  });
});
