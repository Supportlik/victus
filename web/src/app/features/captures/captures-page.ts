import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiClient, AgentRun, Capture } from '../../api';
import { describeError } from '../../core/problem';
import { CaptureInput } from '../../shared/capture-input';
import { MarkdownPipe } from '../../shared/markdown.pipe';

/**
 * Inbox: drop text, a voice note or a photo, optionally for a specific day, then press
 * "Process now". The run is queued and picked up by the worker within seconds.
 * Each row shows the transcript or image, and lets you re-target, discard or re-transcribe.
 */
@Component({
  selector: 'v-captures-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, MarkdownPipe, CaptureInput],
  template: `
    <div class="v-page">
      <header class="v-page-head">
        <div><h2>Captures</h2><p class="sub">Whatever you noted about food — text, voice, photo. The agent turns it into drafts you approve.</p></div>
        <div class="v-actions">
          <a class="v-btn" routerLink="/agent">Agent runs</a>
          <button type="button" class="v-btn primary" (click)="processNow()" [disabled]="run() && !finished(run()!)">
            {{ run() && !finished(run()!) ? 'Processing…' : 'Process now' }}
          </button>
        </div>
      </header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
      @if (notice(); as n) { <div class="v-notice">{{ n }}</div> }

      @if (run(); as r) {
        <section class="v-panel run" [class.active]="!finished(r)" aria-live="polite">
          <h3>Run {{ r.id.slice(0, 8) }} · {{ r.status.replace('_', ' ') }}</h3>
          @if (r.days.length) { <p class="v-small v-muted">Days: {{ r.days.join(', ') }}@if (r.cost_usd != null) { · {{ r.cost_usd.toFixed(2) }} USD }</p> }
          @if (!finished(r)) { <p class="v-small v-muted">The worker picks the run up within seconds; this page polls until it is done.</p> }
          @if (r.error) { <div class="v-error">{{ r.error }}</div> }
          @if (r.summary_md) { <div class="v-md" [innerHTML]="r.summary_md | markdown"></div> <a class="v-btn" routerLink="/drafts">Review drafts</a> }
        </section>
      }

      <form class="v-panel upload" (ngSubmit)="upload()">
        <h3>Add a capture</h3>
        <div class="v-form-row">
          <label class="v-field"><span>For which day? <span class="v-muted">(optional — the agent can infer it)</span></span><input name="date" type="date" [(ngModel)]="targetDate" /></label>
        </div>
        <v-capture-input [targetDate]="targetDate || null" (uploaded)="load()" />
        <label class="v-field"><span>…or type it</span><textarea name="text" [(ngModel)]="text" placeholder="e.g. lunch: 400 g quark with berries, two slices of rye bread"></textarea></label>
        <div class="v-actions"><button type="submit" class="v-btn" [disabled]="busy() || !text.trim()">Save text</button></div>
      </form>

      <section class="list">
        <div class="v-actions"><label class="v-field"><span>Show</span>
          <select [ngModel]="status()" (ngModelChange)="status.set($event); load()"><option value="">all</option><option value="new">new</option><option value="assigned">assigned</option><option value="processed">processed</option><option value="discarded">discarded</option><option value="failed">failed</option></select>
        </label></div>
        <div class="v-scroll">
        <table class="v-table">
          <thead><tr><th>Captured</th><th>Kind</th><th>For day</th><th>Content</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            @for (c of captures(); track c.id) {
              <tr [attr.data-capture]="c.id">
                <td>{{ c.captured_at.replace('T', ' ').slice(0, 16) }}</td><td>{{ c.kind }}</td>
                <td>
                  @if (editing() === c.id) {
                    <span class="set-day">
                      <input type="date" [ngModel]="c.target_date ?? ''" (ngModelChange)="pendingDate = $event" name="d{{ c.id }}" aria-label="Target day" />
                      <button type="button" class="v-btn small primary" (click)="saveDay(c)">Save</button>
                      <button type="button" class="v-btn small quiet" (click)="editing.set(null)">Cancel</button>
                    </span>
                  } @else if (c.product_id) { <a [routerLink]="['/products', c.product_id]">product #{{ c.product_id }}</a>
                  } @else if (c.target_date) { <a [routerLink]="['/days', c.target_date]">{{ c.target_date }}</a> } @else { <span class="v-muted">–</span> }
                </td>
                <td class="content">
                  @if (c.text) { <div>{{ c.text }}</div> }
                  @if (c.kind === 'audio') {
                    @if (c.attachment_id) { <audio controls preload="none" [src]="api.attachmentUrl(c.attachment_id)"></audio> }
                    @if (c.transcript) { <div class="transcript">“{{ c.transcript }}”</div> } @else { <div class="v-muted v-small">no transcript yet</div> }
                  }
                  @if (c.kind === 'image' && c.attachment_id) {
                    <a [href]="api.attachmentUrl(c.attachment_id)" target="_blank" rel="noopener"><img class="thumb" [src]="api.attachmentUrl(c.attachment_id)" alt="capture photo" loading="lazy" /></a>
                  }
                </td>
                <td><span class="v-tag" [class]="'v-tag ' + tagClass(c.status)">{{ c.status.replace('_', ' ') }}</span></td>
                <td class="actions">
                  @if ((c.status === 'new' || c.status === 'failed') && !c.product_id) {
                    <button type="button" class="v-btn small" (click)="editing.set(c.id); pendingDate = c.target_date ?? ''">Set day</button>
                    <button type="button" class="v-btn small quiet" (click)="discard(c)">Discard</button>
                  }
                  @if (c.kind === 'audio') { <button type="button" class="v-btn small" (click)="retranscribe(c)" [disabled]="busy()">Re-transcribe</button> }
                </td>
              </tr>
            } @empty { <tr><td colspan="6" class="v-muted">No captures yet.</td></tr> }
          </tbody>
        </table>
        </div>
      </section>
    </div>
  `,
  styles: `
    .run { margin-bottom: 1rem; } .run.active { border-color: var(--v-agent); }
    .upload { display: grid; gap: 0.75rem; margin-bottom: 1.5rem; }
    .content { max-width: 32rem; white-space: pre-wrap; }
    .transcript { color: var(--v-ink-2); font-style: italic; margin-top: 0.25rem; }
    .thumb { max-width: 12rem; max-height: 8rem; border-radius: var(--v-radius); display: block; }
    audio { max-width: 16rem; display: block; margin-top: 0.25rem; }
    .actions { white-space: nowrap; display: flex; gap: 0.3rem; flex-wrap: wrap; }
    .set-day { display: inline-flex; gap: 0.3rem; align-items: center; }
    .v-scroll { overflow-x: auto; }
  `,
})
export class CapturesPage {
  readonly api = inject(ApiClient);
  readonly captures = signal<Capture[]>([]);
  readonly status = signal('');
  readonly run = signal<AgentRun | null>(null);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly notice = signal<string | null>(null);
  readonly editing = signal<string | null>(null);
  text = '';
  targetDate = '';
  pendingDate = '';
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    this.load();
  }

  load(): void {
    this.api.captures(this.status() || undefined).subscribe({ next: (c) => this.captures.set(c), error: (e: unknown) => this.error.set(describeError(e)) });
  }

  upload(): void {
    if (!this.text.trim()) return;
    const form = new FormData();
    form.append('text', this.text.trim());
    if (this.targetDate) form.append('target_date', this.targetDate);
    this.busy.set(true);
    this.error.set(null);
    this.notice.set(null);
    this.api.uploadCapture(form).subscribe({
      next: (c) => {
        if (c.created === false) this.notice.set('This capture already exists (same content) — nothing was added.');
        this.text = '';
        this.busy.set(false);
        this.load();
      },
      error: (e: unknown) => {
        this.error.set(describeError(e));
        this.busy.set(false);
      },
    });
  }

  saveDay(c: Capture): void {
    const target_date = this.pendingDate || null;
    this.api.updateCapture(c.id, { target_date }).subscribe({
      next: (u) => {
        this.replace(u);
        this.editing.set(null);
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  discard(c: Capture): void {
    this.api.updateCapture(c.id, { status: 'discarded' }).subscribe({
      next: (u) => this.replace(u),
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  retranscribe(c: Capture): void {
    this.busy.set(true);
    this.api.transcribeCapture(c.id, true).subscribe({
      next: (u) => {
        this.replace(u);
        this.busy.set(false);
      },
      error: (e: unknown) => {
        this.error.set(describeError(e));
        this.busy.set(false);
      },
    });
  }

  private replace(u: Capture): void {
    this.captures.update((list) => list.map((x) => (x.id === u.id ? u : x)));
  }

  finished(r: AgentRun): boolean {
    return !['queued', 'running'].includes(r.status);
  }

  processNow(): void {
    this.error.set(null);
    this.api.startAgentRun({ mode: 'historical' }).subscribe({
      next: (r) => {
        this.run.set(r);
        this.poll(r.id);
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  private poll(id: string): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.api.agentRun(id).subscribe({
        next: (r) => {
          this.run.set(r);
          if (this.finished(r)) this.load();
          else this.poll(id);
        },
        error: (e: unknown) => this.error.set(describeError(e)),
      });
    }, 2000);
  }

  tagClass(s: Capture['status']): string {
    return s === 'processed' ? 'closed' : s === 'failed' ? 'bad' : s === 'new' ? 'warn' : s === 'assigned' ? 'draft' : '';
  }
}
