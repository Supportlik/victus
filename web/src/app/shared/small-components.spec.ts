// T-WEB-416: the small shared pieces — status tag, macro line, Markdown pipe, the newer-data
// hint and the notice stack — render what they are given and act on their buttons.
import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { DayStatus, Macros } from '../api';
import { LiveRefresh } from '../core/live-refresh';
import { NoticeService } from '../core/notice.service';
import { MacroLine } from './macro-line';
import { MarkdownPipe } from './markdown.pipe';
import { Notices } from './notices';
import { RefreshHint } from './refresh-hint';
import { StatusTag } from './status-tag';

@Component({
  imports: [StatusTag, MacroLine, RefreshHint, Notices],
  template: `
    <v-status-tag [status]="status()" />
    <v-macro-line [m]="macros" />
    <v-refresh-hint [live]="live" />
    <v-notices />
  `,
})
class Host {
  status = signal<DayStatus>('draft');
  macros: Macros = { kcal: 1383, protein: 154.9, carbs: 116.6, fat: 28.4, fiber: 12.3, salt: 7.25 };
  refresh = vi.fn();
  live = new LiveRefresh({ accepts: () => true, refresh: () => this.refresh(), busy: () => true });
}

describe('shared components', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [Host] }).compileComponents();
  });

  it('T-WEB-416: status tag and macro line', () => {
    const fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const tag = el.querySelector('v-status-tag span') as HTMLElement;
    expect(tag.textContent).toBe('Draft');
    expect(tag.className).toContain('draft');
    fixture.componentInstance.status.set('closed');
    fixture.detectChanges();
    expect(tag.textContent).toBe('Closed');

    const line = el.querySelector('v-macro-line') as HTMLElement;
    expect(line.querySelector('.kcal')?.textContent).toContain('kcal');
    const abbrs = [...line.querySelectorAll('abbr')];
    expect(abbrs.map((a) => a.textContent)).toEqual(['P', 'C', 'F', 'Fi', 'S']);
    expect(abbrs[0].getAttribute('title')).toBe('Protein (g)');
  });

  it('T-WEB-416: the newer-data hint appears on a held change, applies and dismisses', () => {
    const fixture = TestBed.createComponent(Host);
    const host = fixture.componentInstance;
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.stale')).toBeNull();

    host.live.arrived();
    fixture.detectChanges();
    expect(el.querySelector('.stale')?.textContent).toContain('There is newer data.');
    (el.querySelector('.stale .primary') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(host.refresh).toHaveBeenCalledOnce();
    expect(el.querySelector('.stale')).toBeNull();

    host.live.arrived();
    fixture.detectChanges();
    (el.querySelector('.stale .quiet') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(el.querySelector('.stale')).toBeNull();
    expect(host.refresh).toHaveBeenCalledOnce();
  });

  it('T-WEB-416: notices show with their role and are dismissed by their button or by time', () => {
    const fixture = TestBed.createComponent(Host);
    const notices = TestBed.inject(NoticeService);
    notices.error('Saving failed');
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const shown = el.querySelector('.notice') as HTMLElement;
    expect(shown.textContent).toContain('Saving failed');
    expect(shown.getAttribute('role')).toBe('alert');
    expect(shown.classList.contains('bad')).toBe(true);
    (shown.querySelector('button.close') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(el.querySelector('.notice')).toBeNull();

    vi.useFakeTimers();
    try {
      notices.ok('Saved');
      fixture.detectChanges();
      const ok = el.querySelector('.notice') as HTMLElement;
      expect(ok.getAttribute('role')).toBe('status');
      expect(ok.getAttribute('aria-live')).toBe('polite');
      vi.runAllTimers();
      fixture.detectChanges();
      expect(el.querySelector('.notice')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('T-WEB-416: the Markdown pipe renders and sanitises, and an empty value is empty', () => {
    const pipe = TestBed.runInInjectionContext(() => new MarkdownPipe());
    expect(pipe.transform(null)).toBe('');
    expect(pipe.transform('')).toBe('');
    const html = String(pipe.transform('**bold** <script>alert(1)</script>'));
    expect(html).toContain('<strong>bold</strong>');
    expect(html).not.toContain('<script>');
  });
});
