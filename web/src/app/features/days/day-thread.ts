import { ChangeDetectionStrategy, Component, effect, inject, input, signal } from '@angular/core';
import { ApiClient, Capture, DayMessage } from '../../api';
import { BadgesService } from '../../core/badges.service';
import { FormatService } from '../../core/format.service';
import { I18nService } from '../../core/i18n.service';
import { describeError } from '../../core/problem';
import { CaptureCard } from '../../shared/capture-card';
import { CaptureInput } from '../../shared/capture-input';
import { MarkdownPipe } from '../../shared/markdown.pipe';

/**
 * The day's conversation. Everything you write, say or photograph here is a capture for this
 * date; the agent answers with questions and notes in the same thread. Its verdict on the day
 * is not a chat entry — that stands above the meals.
 */
@Component({
  selector: 'v-day-thread',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MarkdownPipe, CaptureInput, CaptureCard],
  template: `
    <aside class="thread">
      <h3>{{ i18n.t('Talk to this day') }}</h3>
      <p class="v-small v-muted">{{ i18n.t('Text, voice or photo — each becomes a capture for this day. The agent reads it on its next run and answers here.') }}</p>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
      <ol class="messages" aria-live="polite">
        @for (m of messages(); track m.id) {
          <li class="msg" [class]="'msg ' + m.role + ' ' + m.kind" [class.card]="!!m.capture_id">
            @if (m.role === 'agent' || m.role === 'system') {
              <div class="meta">
                <span class="who">{{ i18n.t(m.role === 'agent' ? 'Agent' : 'System') }}</span>
                @if (m.kind !== 'text') { <span class="v-tag" [class]="'v-tag ' + kindClass(m.kind)">{{ i18n.t(m.kind) }}</span> }
                <time [attr.datetime]="m.created_at">{{ format.clock(m.created_at) }}</time>
              </div>
              <div class="body v-md" [innerHTML]="m.content | markdown"></div>
            } @else if (m.capture_id) {
              <v-capture-card [capture]="asCapture(m)" [compact]="true" [showTarget]="false" (changed)="reload()" (deleted)="reload()" />
            } @else {
              <div class="meta"><span class="who">{{ i18n.t('You') }}</span><time [attr.datetime]="m.created_at">{{ format.clock(m.created_at) }}</time></div>
              <div class="body">{{ m.content }}</div>
            }
          </li>
        } @empty {
          <li class="v-muted v-small">{{ i18n.t('No messages yet.') }}</li>
        }
      </ol>
      <v-capture-input
        [targetDate]="date()"
        [compact]="true"
        [placeholder]="i18n.t('Add to this day, or correct it: the chicken was 300 g, not 400')"
        (uploaded)="reload()"
      />
    </aside>
  `,
  styles: `
    .thread { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.6rem; align-content: start; }
    .messages { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.5rem; max-height: 60vh; overflow: auto; }
    .msg:not(.card) { padding: 0.5rem 0.7rem; border-radius: var(--v-radius-l); background: var(--v-surface-2); }
    .msg.agent, .msg.system { background: var(--v-agent-soft); border-left: 3px solid var(--v-agent); }
    .msg.question { border-left-color: var(--v-warn); }
    .msg.note { border-left-style: dashed; }
    .meta { display: flex; gap: 0.5rem; align-items: center; font-size: var(--v-fs-xs); color: var(--v-ink-3); margin-bottom: 0.2rem; }
    .who { color: var(--v-ink-2); font-weight: 500; }
    .body { white-space: pre-wrap; font-size: var(--v-fs-s); }
  `,
})
export class DayThread {
  private readonly api = inject(ApiClient);
  private readonly badges = inject(BadgesService);
  readonly i18n = inject(I18nService);
  readonly format = inject(FormatService);
  readonly date = input.required<string>();
  /** Bumped by the day when something outside the thread changed a capture. */
  readonly revision = input(0);
  readonly messages = signal<DayMessage[]>([]);
  readonly error = signal<string | null>(null);

  constructor() {
    effect(() => {
      this.date();
      this.revision();
      this.reload();
    });
  }

  reload(): void {
    this.api.dayMessages(this.date()).subscribe({
      next: (m) => {
        // The day's verdict has its own quiet block above the meals; as a chat entry it
        // would say the same two sentences twice on one page. What belongs in a
        // conversation are the notes and the questions.
        this.messages.set(m.filter((x) => !(x.role === 'agent' && x.kind === 'summary')));
        this.badges.refresh();
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  kindClass(kind: DayMessage['kind']): string {
    return kind === 'question' ? 'warn' : kind === 'summary' ? 'closed' : kind === 'correction' ? 'draft' : '';
  }

  /** A thread entry that is a capture, shaped for the shared card. */
  asCapture(m: DayMessage): Capture {
    return {
      id: m.capture_id!,
      kind: m.capture_kind ?? 'text',
      captured_at: m.created_at,
      target_date: this.date(),
      text: m.capture_kind === 'text' ? m.content : null,
      status: m.processing_state ?? 'new',
      transcript: m.transcript ?? null,
      attachment_id: m.attachment_id ?? null,
      attachment_mime: m.attachment_mime ?? null,
      attachments: m.attachments ?? [],
    };
  }

}
