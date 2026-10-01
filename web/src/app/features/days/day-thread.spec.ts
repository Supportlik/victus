// T-WEB-415: the day thread reads the day's messages, leaves the verdict out, renders agent
// entries as Markdown with their kind, shows captures as cards, reloads on a new revision, and
// shows the API's refusal.
import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { vi } from 'vitest';
import { DayMessage } from '../../api';
import { BadgesService } from '../../core/badges.service';
import { DayThread } from './day-thread';

const DAY = '2026-03-10';
const URL = `/api/v1/days/${DAY}/messages`;
const MESSAGES: DayMessage[] = [
  { id: 'm1', role: 'agent', kind: 'summary', content: 'The verdict.', created_at: '2026-03-10T20:00:00Z' },
  { id: 'm2', role: 'agent', kind: 'question', content: '**How much** rice?', created_at: '2026-03-10T20:01:00Z' },
  { id: 'm3', role: 'system', kind: 'text', content: 'Run finished.', created_at: '2026-03-10T20:02:00Z' },
  { id: 'm4', role: 'user', kind: 'text', content: 'it was 150 g', created_at: '2026-03-10T20:03:00Z' },
  {
    id: 'm5',
    role: 'user',
    kind: 'text',
    content: 'two eggs',
    created_at: '2026-03-10T20:04:00Z',
    capture_id: 'cap1',
    capture_kind: 'text',
    processing_state: 'new',
  },
];

@Component({
  imports: [DayThread],
  template: `<v-day-thread [date]="date" [revision]="revision()" />`,
})
class Host {
  date = DAY;
  revision = signal(0);
}

describe('DayThread', () => {
  let http: HttpTestingController;
  const badges = { refresh: vi.fn() };

  beforeEach(async () => {
    badges.refresh.mockClear();
    await TestBed.configureTestingModule({
      imports: [Host],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: BadgesService, useValue: badges },
      ],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  it('T-WEB-415: shows notes, questions and captures, not the verdict', async () => {
    const fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    const req = http.expectOne(URL);
    expect(req.request.method).toBe('GET');
    req.flush(MESSAGES);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const items = [...el.querySelectorAll('ol.messages > li')];
    expect(items.length).toBe(4);
    expect(el.textContent).not.toContain('The verdict.');
    expect(items[0].querySelector('strong')?.textContent).toBe('How much');
    expect(items[0].querySelector('.v-tag.warn')?.textContent).toContain('question');
    expect(items[1].textContent).toContain('System');
    expect(items[1].querySelector('.v-tag')).toBeNull();
    expect(items[2].textContent).toContain('You');
    expect(items[2].textContent).toContain('it was 150 g');
    expect(items[3].querySelector('v-capture-card')).toBeTruthy();
    expect(badges.refresh).toHaveBeenCalled();

    fixture.componentInstance.revision.set(1);
    fixture.detectChanges();
    http.expectOne(URL).flush([]);
    fixture.detectChanges();
    expect(el.textContent).toContain('No messages yet.');
  });

  it('T-WEB-415: a refused thread shows the problem detail', async () => {
    const fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    http.expectOne(URL).flush({ title: 'Not found', detail: 'no day log' }, { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('.v-error')?.textContent).toContain('no day log');
  });

  it('T-WEB-415: a capture entry becomes a card model; kinds map to their tag class', () => {
    const thread = TestBed.createComponent(DayThread);
    thread.componentRef.setInput('date', DAY);
    const t = thread.componentInstance;
    const card = t.asCapture({ ...MESSAGES[4], capture_kind: 'audio', content: 'ignored' });
    expect(card).toMatchObject({ id: 'cap1', kind: 'audio', text: null, target_date: DAY, status: 'new', attachments: [] });
    expect(t.asCapture({ ...MESSAGES[4], capture_kind: null, processing_state: null })).toMatchObject({
      kind: 'text',
      status: 'new',
    });
    expect(t.asCapture(MESSAGES[4]).text).toBe('two eggs');
    expect(t.kindClass('question')).toBe('warn');
    expect(t.kindClass('summary')).toBe('closed');
    expect(t.kindClass('correction')).toBe('draft');
    expect(t.kindClass('note')).toBe('');
    thread.detectChanges();
    expect(t.dirty()).toBe(false);
    http.expectOne(URL).flush([]);
  });
});
