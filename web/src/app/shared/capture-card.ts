import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiClient, Capture } from '../api';
import { describeError } from '../core/problem';

/**
 * One capture, the same everywhere (inbox, day thread, product page): preview of the
 * text, transcript, audio or image; status; and the actions that make sense for its state.
 *
 * - new / failed: set day, discard, delete, re-transcribe (audio)
 * - assigned: nothing destructive (the agent used it; approve or discard the draft instead)
 * - discarded: restore or delete now; otherwise it is deleted automatically after one day
 * - processed: read-only
 */
@Component({
  selector: 'v-capture-card',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink],
  template: `
    <article class="card" [class.compact]="compact()" [class]="'card ' + c().status" [attr.data-capture]="c().id">
      <div class="media">
        @if (images().length) {
          @for (a of images(); track a.id) {
            <a [href]="api.attachmentUrl(a.id)" target="_blank" rel="noopener" title="Open full size">
              <img [src]="api.attachmentUrl(a.id)" alt="capture photo" loading="lazy" />
            </a>
          }
        } @else if (c().kind === 'audio') {
          <span class="glyph" aria-hidden="true">🎙</span>
        } @else {
          <span class="glyph" aria-hidden="true">✎</span>
        }
      </div>
      <div class="body">
        <div class="meta">
          <time [attr.datetime]="c().captured_at">{{ c().captured_at.replace('T', ' ').slice(0, 16) }}</time>
          <span class="v-tag" [class]="'v-tag ' + tagClass()">{{ statusLabel() }}</span>
          @if (showTarget()) {
            @if (c().product_id) { <a class="target" [routerLink]="['/products', c().product_id]">product</a> }
            @else if (c().target_date) { <a class="target" [routerLink]="['/days', c().target_date]">{{ c().target_date }}</a> }
            @else { <span class="v-muted">no day yet</span> }
          }
        </div>
        @if (c().text) { <p class="text">{{ c().text }}</p> }
        @if (c().kind === 'audio') {
          @for (a of audios(); track a.id) { <audio controls preload="none" [src]="api.attachmentUrl(a.id)"></audio> }
          @if (c().transcript) { <p class="transcript">“{{ c().transcript }}”</p> }
          @else if (c().transcript === '') { <p class="v-small v-muted">No speech detected in this recording.</p> }
          @else { <p class="v-small v-muted">No transcript yet.</p> }
        }
        @if (error(); as e) { <div class="v-small err">{{ e }}</div> }
        @if (canAct()) {
          <div class="actions">
            @if (editing()) {
              <input type="date" [(ngModel)]="pendingDate" name="d{{ c().id }}" aria-label="Day" />
              <button type="button" class="v-btn small primary" (click)="saveDay()">Save</button>
              <button type="button" class="v-btn small quiet" (click)="editing.set(false)">Cancel</button>
            } @else {
              @if (isOpen() && !c().product_id) {
                <button type="button" class="v-btn small" (click)="editing.set(true); pendingDate = c().target_date ?? ''">{{ c().target_date ? 'Change day' : 'Set day' }}</button>
              }
              @if (isOpen()) {
                <button type="button" class="v-btn small quiet" (click)="setStatus('discarded')" [disabled]="busy()">Discard</button>
              }
              @if (c().status === 'discarded') {
                <button type="button" class="v-btn small" (click)="setStatus('new')" [disabled]="busy()">Restore</button>
              }
              @if (c().kind === 'audio' && isOpen()) {
                <button type="button" class="v-btn small quiet" (click)="retranscribe()" [disabled]="busy()">Re-transcribe</button>
              }
              @if (confirmDelete()) {
                <span class="v-small">Delete for good?</span>
                <button type="button" class="v-btn small danger" (click)="remove()" [disabled]="busy()">Yes, delete</button>
                <button type="button" class="v-btn small quiet" (click)="confirmDelete.set(false)">No</button>
              } @else {
                <button type="button" class="v-btn small quiet danger" (click)="confirmDelete.set(true)" [disabled]="busy()">Delete</button>
              }
            }
          </div>
          @if (c().status === 'discarded') { <p class="v-small v-muted">Discarded captures are deleted automatically after one day.</p> }
        }
      </div>
    </article>
  `,
  styles: `
    .card { display: grid; grid-template-columns: 4.5rem 1fr; gap: 0.75rem; padding: 0.75rem; border: 1px solid var(--v-line); border-radius: var(--v-radius-l); background: var(--v-surface); }
    .card.compact { grid-template-columns: 3rem 1fr; padding: 0.5rem; }
    .card.discarded { opacity: 0.7; }
    .card.processed { border-style: dashed; }
    .media { display: grid; gap: 0.25rem; place-items: center; align-content: start; }
    .media img { width: 4.5rem; height: 4.5rem; object-fit: cover; border-radius: var(--v-radius); display: block; }
    .compact .media img { width: 3rem; height: 3rem; }
    .glyph { font-size: 1.4rem; color: var(--v-ink-3); }
    .body { min-width: 0; display: grid; gap: 0.35rem; }
    .meta { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; font-size: var(--v-fs-xs); color: var(--v-ink-3); }
    .target { font-weight: 500; }
    .text { margin: 0; white-space: pre-wrap; font-size: var(--v-fs-s); }
    .transcript { margin: 0; color: var(--v-ink-2); font-style: italic; font-size: var(--v-fs-s); }
    audio { width: 100%; max-width: 20rem; display: block; }
    .actions { display: flex; gap: 0.3rem; flex-wrap: wrap; align-items: center; }
    .actions input { padding: 0.25rem 0.4rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); }
    .err { color: var(--v-bad); }
  `,
})
export class CaptureCard {
  readonly api = inject(ApiClient);
  readonly capture = input.required<Capture>();
  readonly compact = input(false);
  /** Show the day / product link in the header (off inside a day thread or product page). */
  readonly showTarget = input(true);
  /** Hide all actions (read-only listing). */
  readonly readonly = input(false);
  readonly changed = output<Capture>();
  readonly deleted = output<string>();

  readonly local = signal<Capture | null>(null);
  readonly c = computed(() => this.local() ?? this.capture());
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly editing = signal(false);
  readonly confirmDelete = signal(false);
  pendingDate = '';

  readonly isOpen = computed(() => ['new', 'failed'].includes(this.c().status));
  readonly canAct = computed(() => !this.readonly() && this.c().status !== 'processed' && this.c().status !== 'assigned');

  /** Files of this capture, split by what they are. */
  private files(): { id: string; mime: string }[] {
    const c = this.c();
    if (c.attachments?.length) return c.attachments;
    return c.attachment_id ? [{ id: c.attachment_id, mime: c.attachment_mime ?? '' }] : [];
  }
  images(): { id: string; mime: string }[] {
    return this.files().filter((a) => a.mime.startsWith('image/'));
  }
  audios(): { id: string; mime: string }[] {
    const audio = this.files().filter((a) => a.mime.startsWith('audio/') || a.mime.startsWith('video/'));
    return audio.length ? audio : this.c().attachment_id && this.c().kind === 'audio' ? [{ id: this.c().attachment_id!, mime: '' }] : [];
  }

  statusLabel(): string {
    const s = this.c().status;
    return s === 'new' ? 'waiting for the agent' : s === 'assigned' ? 'in draft' : s === 'in_progress' ? 'processing' : s;
  }

  tagClass(): string {
    const s = this.c().status;
    return s === 'processed' ? 'closed' : s === 'failed' ? 'bad' : s === 'new' ? 'warn' : s === 'assigned' ? 'draft' : '';
  }

  saveDay(): void {
    this.patch({ target_date: this.pendingDate || null });
    this.editing.set(false);
  }

  setStatus(status: Capture['status']): void {
    this.patch({ status });
  }

  retranscribe(): void {
    this.busy.set(true);
    this.api.transcribeCapture(this.c().id, true).subscribe({ next: (u) => this.apply(u), error: (e: unknown) => this.fail(e) });
  }

  remove(): void {
    this.busy.set(true);
    const id = this.c().id;
    this.api.deleteCapture(id).subscribe({
      next: () => {
        this.busy.set(false);
        this.deleted.emit(id);
      },
      error: (e: unknown) => this.fail(e),
    });
  }

  private patch(body: Partial<Pick<Capture, 'status' | 'target_date'>>): void {
    this.busy.set(true);
    this.error.set(null);
    this.api.updateCapture(this.c().id, body).subscribe({ next: (u) => this.apply(u), error: (e: unknown) => this.fail(e) });
  }

  private apply(u: Capture): void {
    this.local.set(u);
    this.busy.set(false);
    this.changed.emit(u);
  }

  private fail(e: unknown): void {
    this.error.set(describeError(e));
    this.busy.set(false);
  }
}
