import { Injectable } from '@angular/core';

/**
 * Hand a job to the user's own Claude instead of queueing a run nobody collects.
 *
 * Without a model key the worker cannot process anything, but the user's Claude already
 * talks to Victus over MCP. So the app builds the instruction and either opens a chat with
 * it or puts it on the clipboard. The deep link may land in a browser rather than the app
 * depending on the device, which is why copying is always offered as well (R67).
 */
@Injectable({ providedIn: 'root' })
export class ClaudeHandoff {
  /** Process whatever captures are open. Deliberately says nothing about days. */
  readonly processCaptures = [
    'Process my open Victus captures.',
    'Use the Victus MCP: agent_run_start, then captures_open, day_thread_get and',
    'product_search per item, then draft_create and agent_run_finish with a short summary.',
    'Do not approve anything, I do that in the app.',
  ].join(' ');

  /** Assess one frozen report moment. */
  assessSnapshot(id: string, title: string): string {
    return [
      `Assess the frozen Victus report "${title}".`,
      'Use the Victus MCP: report_snapshot_get with id',
      `${id},`,
      'read the numbers it carries, then report_assess with your judgement of where I stand:',
      'what the values say, what changed, and what to do next. Keep it short.',
    ].join(' ');
  }

  /** Open a Claude chat with the instruction already in the box. */
  open(prompt: string): void {
    const url = `https://claude.ai/new?q=${encodeURIComponent(prompt)}`;
    window.open(url, '_blank', 'noopener');
  }

  /** Put the instruction on the clipboard. Resolves false when the browser refused. */
  async copy(prompt: string): Promise<boolean> {
    try {
      await navigator.clipboard.writeText(prompt);
      return true;
    } catch {
      return false;
    }
  }
}
