// T-WEB-050: a capture with two recordings shows each one's own length and text, and
// says which of them has not been listened to yet.
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it } from 'vitest';
import { Capture } from '../api';
import { CaptureCard } from './capture-card';

const TWO_RECORDINGS: Capture = {
  id: 'c1',
  kind: 'audio',
  captured_at: '2026-01-05T12:00:00Z',
  target_date: '2026-01-05',
  status: 'new',
  transcript: 'a whole tub of skyr',
  attachment_id: 'a1',
  attachment_mime: 'audio/webm',
  attachments: [
    { id: 'a1', mime: 'audio/webm', size: 1000 },
    { id: 'a2', mime: 'audio/webm', size: 2000 },
  ],
  transcripts: [{ attachment_id: 'a1', text: 'a whole tub of skyr', duration_s: 42 }],
};

function render(capture: Capture): ComponentFixture<CaptureCard> {
  const f = TestBed.createComponent(CaptureCard);
  f.componentRef.setInput('capture', capture);
  f.detectChanges();
  return f;
}

function recordings(f: ComponentFixture<CaptureCard>): HTMLElement[] {
  return Array.from((f.nativeElement as HTMLElement).querySelectorAll('.rec'));
}

describe('CaptureCard', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
  });

  it('gives every recording its own player, length and text', () => {
    const rows = recordings(render(TWO_RECORDINGS));
    expect(rows).toHaveLength(2);

    const [first, second] = rows;
    // a length is known before anything is played, so a capture can be judged at a glance
    expect(first.querySelector('audio')!.getAttribute('preload')).toBe('metadata');
    expect(first.textContent).toContain('0:42');
    expect(first.textContent).toContain('a whole tub of skyr');

    // the second borrowed its neighbour's text before, and said nothing about waiting
    expect(second.textContent).toContain('No transcript yet.');
    expect(second.textContent).not.toContain('a whole tub of skyr');
    expect(second.querySelector('audio')!.getAttribute('src')).toContain('a2');
  });

  it('tells a silent recording apart from one that is still waiting', () => {
    const rows = recordings(
      render({
        ...TWO_RECORDINGS,
        transcript: '',
        transcripts: [
          { attachment_id: 'a1', text: '', duration_s: 3 },
          { attachment_id: 'a2', text: 'and an apple', duration_s: 65 },
        ],
      }),
    );
    expect(rows[0].textContent).toContain('No speech detected in this recording.');
    expect(rows[0].textContent).toContain('0:03');
    expect(rows[1].textContent).toContain('1:05');
    expect(rows[1].textContent).toContain('and an apple');
  });

  it('reads a capture-wide text as the first recording, the only one it can be', () => {
    // a day-thread message carries one text and no per-recording rows
    const single = recordings(
      render({
        ...TWO_RECORDINGS,
        attachments: [{ id: 'a1', mime: 'audio/webm', size: 1000 }],
        transcripts: undefined,
      }),
    );
    expect(single).toHaveLength(1);
    expect(single[0].textContent).toContain('a whole tub of skyr');

    const both = recordings(render({ ...TWO_RECORDINGS, transcripts: undefined }));
    expect(both[0].textContent).toContain('a whole tub of skyr');
    expect(both[1].textContent).toContain('No transcript yet.');
  });
});
