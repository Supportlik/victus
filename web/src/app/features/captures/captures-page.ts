import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AgentRun, ApiClient, Capture } from '../../api';
import { BadgesService } from '../../core/badges.service';
import { describeError } from '../../core/problem';
import { CaptureCard } from '../../shared/capture-card';
import { CaptureInput } from '../../shared/capture-input';
import { MarkdownPipe } from '../../shared/markdown.pipe';

type Filter = 'open' | 'all' | 'assigned' | 'processed' | 'discarded' | 'failed';

/**
 * Inbox: everything you noted about food that the agent has not turned into a draft yet.
 * Record, photograph, pick files or type; then "Process now" (or let the hourly run take it).
 */
@Component({
  selector: 'v-captures-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, MarkdownPipe, CaptureInput, CaptureCard],
  template: `
    <div class="v-page">
      <header class="v-page-head">
        <div><h2>Captures</h2><p class="sub">Voice, photo or text about what you ate. The agent turns it into drafts you approve.</p></div>
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
          @if (!finished(r)) { <p class="v-small v-muted">Waiting for the worker; this page polls until the run is done.</p> }
          @if (r.error) { <div class="v-error">{{ r.error }}</div> }
          @if (r.summary_md) { <div class="v-md" [innerHTML]="r.summary_md | markdown"></div> <a class="v-btn" routerLink="/drafts">Review drafts</a> }
        </section>
      }

      <section class="v-panel add">
        <div class="add-head">
          <h3>Add a capture</h3>
          <label class="v-field day"><span>For day</span><input name="date" type="date" [(ngModel)]="targetDate" /></label>
        </div>
        <v-capture-input [targetDate]="targetDate || null" (uploaded)="onUploaded($event)" />
        <form class="typed" (ngSubmit)="upload()">
          <textarea name="text" [(ngModel)]="text" rows="2" placeholder="…or type it: lunch 400 g quark with berries, two slices of rye bread" [disabled]="busy()"></textarea>
          <button type="submit" class="v-btn" [disabled]="busy() || !text.trim()">Save text</button>
        </form>
      </section>

      <section class="list">
        <div class="filters" role="tablist">
          @for (f of filters; track f.id) {
            <button type="button" class="chip" [class.active]="filter() === f.id" (click)="filter.set(f.id)">{{ f.label }}@if (count(f.id); as n) { <span class="n">{{ n }}</span> }</button>
          }
        </div>
        <p class="v-small v-muted">New captures wait for the next agent run. Discarded ones are deleted automatically after one day.</p>
        <div class="cards">
          @for (c of visible(); track c.id) {
            <v-capture-card [capture]="c" (changed)="replace($event)" (deleted)="removed($event)" />
          } @empty {
            <div class="v-empty">Nothing here.</div>
          }
        </div>
      </section>
    </div>
  `,
  styles: `
    .run { margin-bottom: 1rem; } .run.active { border-color: var(--v-agent); }
    .add { display: grid; gap: 0.75rem; margin-bottom: 1.25rem; }
    .add-head { display: flex; justify-content: space-between; align-items: end; gap: 1rem; flex-wrap: wrap; }
    .day { min-width: 11rem; }
    .typed { display: grid; grid-template-columns: 1fr auto; gap: 0.5rem; align-items: start; }
    .typed textarea { padding: 0.5rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); resize: vertical; }
    .filters { display: flex; gap: 0.35rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
    .chip { border: 1px solid var(--v-line-strong); background: var(--v-surface); border-radius: 999px; padding: 0.3rem 0.8rem; cursor: pointer; font-size: var(--v-fs-s); display: inline-flex; gap: 0.4rem; align-items: center; }
    .chip.active { background: var(--v-primary-soft); border-color: var(--v-primary); color: var(--v-primary); }
    .chip .n { font-size: var(--v-fs-xs); color: var(--v-ink-3); }
    .cards { display: grid; gap: 0.6rem; }
    @media (max-width: 40rem) { .typed { grid-template-columns: 1fr; } }
  `,
})
export class CapturesPage {
  readonly api = inject(ApiClient);
  private readonly badges = inject(BadgesService);
  readonly captures = signal<Capture[]>([]);
  readonly filter = signal<Filter>('open');
  readonly run = signal<AgentRun | null>(null);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly notice = signal<string | null>(null);
  readonly filters: { id: Filter; label: string }[] = [
    { id: 'open', label: 'Open' },
    { id: 'assigned', label: 'In draft' },
    { id: 'processed', label: 'Done' },
    { id: 'discarded', label: 'Discarded' },
    { id: 'failed', label: 'Failed' },
    { id: 'all', label: 'All' },
  ];
  text = '';
  targetDate = new Date().toISOString().slice(0, 10);
  private timer: ReturnType<typeof setTimeout> | null = null;

  readonly visible = computed(() => this.captures().filter((c) => this.matches(c, this.filter())));

  constructor() {
    this.load();
  }

  count(f: Filter): number {
    return f === 'all' ? 0 : this.captures().filter((c) => this.matches(c, f)).length;
  }

  private matches(c: Capture, f: Filter): boolean {
    if (f === 'all') return true;
    if (f === 'open') return c.status === 'new' || c.status === 'in_progress';
    return c.status === f;
  }

  load(): void {
    this.api.captures().subscribe({
      next: (c) => {
        this.captures.set(c);
        this.badges.refresh();
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  onUploaded(c: Capture): void {
    this.captures.update((list) => [c, ...list]);
    this.badges.refresh();
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
        else this.onUploaded(c);
        this.text = '';
        this.busy.set(false);
      },
      error: (e: unknown) => {
        this.error.set(describeError(e));
        this.busy.set(false);
      },
    });
  }

  replace(u: Capture): void {
    this.captures.update((list) => list.map((x) => (x.id === u.id ? u : x)));
    this.badges.refresh();
  }

  removed(id: string): void {
    this.captures.update((list) => list.filter((x) => x.id !== id));
    this.badges.refresh();
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
}
