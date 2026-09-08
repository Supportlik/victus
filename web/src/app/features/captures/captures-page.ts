import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiClient, AgentRun, Capture } from '../../api';
import { describeError } from '../../core/problem';
import { MarkdownPipe } from '../../shared/markdown.pipe';

/**
 * Inbox: drop text, a voice note or a photo, optionally for a specific day, then press
 * "Process now". The run is queued and picked up by the worker immediately.
 */
@Component({
  selector: 'v-captures-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, MarkdownPipe],
  template: `
    <div class="v-page">
      <header class="v-page-head">
        <div><h2>Captures</h2><p class="sub">Whatever you noted about food — text, voice, photo. The agent turns it into drafts you approve.</p></div>
        <div class="v-actions">
          <button type="button" class="v-btn primary" (click)="processNow()" [disabled]="run() && !finished(run()!)">
            {{ run() && !finished(run()!) ? 'Processing…' : 'Process now' }}
          </button>
        </div>
      </header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }

      @if (run(); as r) {
        <section class="v-panel run" [class.active]="!finished(r)" aria-live="polite">
          <h3>Run {{ r.id.slice(0, 8) }} · {{ r.status.replace('_', ' ') }}</h3>
          @if (r.days.length) { <p class="v-small v-muted">Days: {{ r.days.join(', ') }}@if (r.cost_usd != null) { · {{ r.cost_usd.toFixed(2) }} USD }</p> }
          @if (r.error) { <div class="v-error">{{ r.error }}</div> }
          @if (r.summary_md) { <div class="v-md" [innerHTML]="r.summary_md | markdown"></div> <a class="v-btn" routerLink="/drafts">Review drafts</a> }
        </section>
      }

      <form class="v-panel upload" (ngSubmit)="upload()">
        <h3>Add a capture</h3>
        <label class="v-field"><span>Text</span><textarea name="text" [(ngModel)]="text" placeholder="e.g. lunch: 400 g quark with berries, two slices of rye bread"></textarea></label>
        <div class="v-form-row">
          <label class="v-field"><span>Voice note or photo</span><input name="file" type="file" accept="audio/*,image/*" (change)="onFile($event)" /></label>
          <label class="v-field"><span>For which day? <span class="v-muted">(optional)</span></span><input name="date" type="date" [(ngModel)]="targetDate" /></label>
        </div>
        <button type="submit" class="v-btn" [disabled]="busy() || (!text.trim() && !file)">Save capture</button>
      </form>

      <section class="list">
        <div class="v-actions"><label class="v-field"><span>Show</span>
          <select [ngModel]="status()" (ngModelChange)="status.set($event); load()"><option value="">all</option><option value="new">new</option><option value="assigned">assigned</option><option value="processed">processed</option><option value="failed">failed</option></select>
        </label></div>
        <table class="v-table">
          <thead><tr><th>Captured</th><th>Kind</th><th>For day</th><th>Content</th><th>Status</th></tr></thead>
          <tbody>
            @for (c of captures(); track c.id) {
              <tr>
                <td>{{ c.captured_at.replace('T', ' ').slice(0, 16) }}</td><td>{{ c.kind }}</td>
                <td>@if (c.target_date) { <a [routerLink]="['/days', c.target_date]">{{ c.target_date }}</a> } @else { <span class="v-muted">–</span> }</td>
                <td class="content">{{ c.text ?? c.transcript ?? '' }}</td>
                <td><span class="v-tag" [class]="'v-tag ' + tagClass(c.status)">{{ c.status.replace('_', ' ') }}</span></td>
              </tr>
            } @empty { <tr><td colspan="5" class="v-muted">No captures yet.</td></tr> }
          </tbody>
        </table>
      </section>
    </div>
  `,
  styles: `
    .run { margin-bottom: 1rem; } .run.active { border-color: var(--v-agent); }
    .upload { display: grid; gap: 0.75rem; margin-bottom: 1.5rem; }
    .content { max-width: 32rem; white-space: pre-wrap; }
  `,
})
export class CapturesPage {
  private readonly api = inject(ApiClient);
  readonly captures = signal<Capture[]>([]);
  readonly status = signal('');
  readonly run = signal<AgentRun | null>(null);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  text = '';
  targetDate = '';
  file: File | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    this.load();
  }

  load(): void {
    this.api.captures(this.status() || undefined).subscribe({ next: (c) => this.captures.set(c), error: (e: unknown) => this.error.set(describeError(e)) });
  }

  onFile(ev: Event): void {
    this.file = (ev.target as HTMLInputElement).files?.[0] ?? null;
  }

  upload(): void {
    const form = new FormData();
    if (this.text.trim()) form.append('text', this.text.trim());
    if (this.file) form.append('file', this.file);
    if (this.targetDate) form.append('target_date', this.targetDate);
    this.busy.set(true);
    this.api.uploadCapture(form).subscribe({
      next: () => {
        this.text = '';
        this.file = null;
        this.busy.set(false);
        this.load();
      },
      error: (e: unknown) => {
        this.error.set(describeError(e));
        this.busy.set(false);
      },
    });
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
