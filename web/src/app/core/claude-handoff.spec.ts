// T-WEB-374, T-WEB-375: a job is handed to the user's own Claude (R67) — a chat opened with
// the instruction in the box, or the instruction on the clipboard.
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ClaudeHandoff } from './claude-handoff';

describe('ClaudeHandoff', () => {
  let handoff: ClaudeHandoff;
  const hadClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');

  beforeEach(() => {
    handoff = TestBed.inject(ClaudeHandoff);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    if (hadClipboard) Object.defineProperty(navigator, 'clipboard', hadClipboard);
    else delete (navigator as unknown as Record<string, unknown>)['clipboard'];
  });

  it('T-WEB-374: the capture instruction names the tools and leaves approval to the person', () => {
    expect(handoff.processCaptures).toContain('agent_run_start');
    expect(handoff.processCaptures).toContain('captures_open');
    expect(handoff.processCaptures).toContain('draft_create');
    expect(handoff.processCaptures).toContain('Do not approve anything');
  });

  it('T-WEB-374: the snapshot instruction carries its title and id', () => {
    const prompt = handoff.assessSnapshot('snap-7', 'September check-up');
    expect(prompt).toContain('"September check-up"');
    expect(prompt).toContain('report_snapshot_get with id snap-7,');
    expect(prompt).toContain('report_assess');
  });

  it('T-WEB-374: opens a new Claude chat with the instruction encoded in the link', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    handoff.open('Assess "this" & that');
    expect(open).toHaveBeenCalledWith(
      'https://claude.ai/new?q=Assess%20%22this%22%20%26%20that',
      '_blank',
      'noopener',
    );
  });

  it('T-WEB-375: resolves true once the instruction is on the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    expect(await handoff.copy('hello')).toBe(true);
    expect(writeText).toHaveBeenCalledWith('hello');
  });

  it('T-WEB-375: resolves false when the browser refuses or has no clipboard', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new DOMException('denied', 'NotAllowedError')) },
    });
    expect(await handoff.copy('hello')).toBe(false);

    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
    expect(await handoff.copy('hello')).toBe(false);
  });
});
