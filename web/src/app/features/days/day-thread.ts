import { ChangeDetectionStrategy, Component, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiClient, DayMessage } from '../../api';
import { describeError } from '../../core/problem';
import { MarkdownPipe } from '../../shared/markdown.pipe';

/**
 * The day's conversation: your notes and the agent's summaries and questions, in order.
 * A message typed here becomes a capture for this date; while a run is active it waits.
 */
@Component({
  selector: 'v-day-thread',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, MarkdownPipe],
  template: `
    <aside class="thread">
      <h3>Notes for this day</h3>
      <p class="v-small v-muted">Add what you ate or correct the draft. The agent picks it up for this day only.</p>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
      <ol class="messages" aria-live="polite">
        @for (m of messages(); track m.id) {
          <li class="msg" [class]="m.role + ' ' + m.kind">
            <div class="meta">
              <span class="who">{{ m.role === 'agent' ? 'Agent' : m.role === 'system' ? 'System' : 'You' }}</span>
              @if (m.role === 'agent' && m.kind !== 'text') { <span class="v-tag" [class]="'v-tag ' + kindClass(m.kind)">{{ m.kind }}</span> }
              <time [attr.datetime]="m.created_at">{{ m.created_at.slice(11, 16) }}</time>
              @if (m.processing_state === 'new' || m.processing_state === 'in_progress') {
                <span class="v-tag warn" title="The agent has not processed this note yet">{{ m.processing_state === 'new' ? 'waiting for the agent' : 'processing' }}</span>
              } @else if (m.processing_state === 'assigned') {
                <span class="v-tag draft" title="Part of the current draft; approve the day to finish">in draft</span>
              }
            </div>
            @if (m.role === 'agent') {
              <div class="body v-md" [innerHTML]="m.content | markdown"></div>
            } @else {
              <div class="body">{{ m.content }}</div>
            }
          </li>
        } @empty {
          <li class="v-muted v-small">No notes yet.</li>
        }
      </ol>
      <form (ngSubmit)="send()" class="composer">
        <textarea name="text" [(ngModel)]="text" rows="2" placeholder="e.g. the chicken was 300 g, not 400" [disabled]="sending()"></textarea>
        <button type="submit" class="v-btn primary" [disabled]="sending() || !text.trim()">Add note</button>
      </form>
    </aside>
  `,
  styles: `
    .thread { display: grid; gap: 0.6rem; align-content: start; }
    .messages { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.5rem; max-height: 60vh; overflow: auto; }
    .msg { padding: 0.5rem 0.7rem; border-radius: var(--v-radius-l); background: var(--v-surface-2); }
    .msg.agent { background: var(--v-agent-soft); border-left: 3px solid var(--v-agent); }
    .msg.question { border-left-color: var(--v-warn); }
    .msg.summary { border-left-color: var(--v-ok); }
    .msg.note { border-left-style: dashed; }
    .meta { display: flex; gap: 0.5rem; align-items: center; font-size: var(--v-fs-xs); color: var(--v-ink-3); margin-bottom: 0.2rem; }
    .who { color: var(--v-ink-2); font-weight: 500; }
    .body { white-space: pre-wrap; font-size: var(--v-fs-s); }
    .composer { display: grid; gap: 0.4rem; }
    .composer textarea { padding: 0.5rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); }
  `,
})
export class DayThread {
  private readonly api = inject(ApiClient);
  readonly date = input.required<string>();
  readonly messages = signal<DayMessage[]>([]);
  readonly sending = signal(false);
  readonly error = signal<string | null>(null);
  text = '';

  constructor() {
    effect(() => {
      const d = this.date();
      this.api.dayMessages(d).subscribe({
        next: (m) => this.messages.set(m),
        error: (e: unknown) => this.error.set(describeError(e)),
      });
    });
  }

  kindClass(kind: DayMessage['kind']): string {
    return kind === 'question' ? 'warn' : kind === 'summary' ? 'closed' : kind === 'correction' ? 'draft' : '';
  }

  send(): void {
    const t = this.text.trim();
    if (!t) return;
    this.sending.set(true);
    this.api.addDayMessage(this.date(), t).subscribe({
      next: (m) => {
        this.messages.update((list) => [...list, m]);
        this.text = '';
        this.sending.set(false);
      },
      error: (e: unknown) => {
        this.error.set(describeError(e));
        this.sending.set(false);
      },
    });
  }
}
