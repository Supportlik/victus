import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AgentRun, ApiClient, Capture, DraftListEntry } from '../../api';
import { BadgesService } from '../../core/badges.service';
import { describeError } from '../../core/problem';
import { CaptureCard } from '../../shared/capture-card';
import { CaptureInput } from '../../shared/capture-input';
import { MarkdownPipe } from '../../shared/markdown.pipe';
import { DraftDayCard } from './draft-day-card';

type Filter = 'open' | 'assigned' | 'processed' | 'discarded' | 'failed' | 'all';

/**
 * One screen for the whole loop: drop a capture, let the agent draft it, accept the
 * result item by item or all at once. Each drafted item shows the capture it came from,
 * and that capture stays here until the item is accepted.
 */
@Component({
  selector: 'v-inbox-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, MarkdownPipe, CaptureInput, CaptureCard, DraftDayCard],
  template: `
    <div class="v-page">
      <header class="v-page-head">
        <div><h2>Inbox</h2><p class="sub">Voice, photo or text goes in; drafts come back. Nothing counts until you accept it.</p></div>
        <div class="v-actions">
          <a class="v-btn" routerLink="/agent">Agent runs</a>
          <button type="button" class="v-btn primary" (click)="processNow()" [disabled]="running()">
            {{ running() ? 'Processing…' : 'Process now' }}
          </button>
        </div>
      </header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }

      <section class="v-panel add">
        <div class="add-head">
          <h3>Add a capture</h3>
          <label class="v-field day"><span>For day</span><input name="date" type="date" [(ngModel)]="targetDate" /></label>
        </div>
        <v-capture-input
          [targetDate]="targetDate || null"
          placeholder="Write it, speak it, or photograph it: lunch, 400 g quark with berries"
          (uploaded)="onUploaded($event)"
        />
      </section>

      @if (run(); as r) {
        <section class="v-panel run" [class.active]="!finished(r)" aria-live="polite">
          <h3>Run {{ r.id.slice(0, 8) }} · {{ r.status.replace('_', ' ') }}</h3>
          @if (r.days.length) { <p class="v-small v-muted">Days: {{ r.days.join(', ') }}@if (r.cost_usd != null) { · {{ r.cost_usd.toFixed(2) }} USD }</p> }
          @if (r.error) { <div class="v-error">{{ r.error }}</div> }
          @if (r.summary_md) { <div class="v-md" [innerHTML]="r.summary_md | markdown"></div> }
        </section>
      }

      <section class="drafts">
        <h3>Waiting for your decision @if (drafts().length) { <span class="v-tag draft">{{ drafts().length }}</span> }</h3>
        @for (d of drafts(); track d.date) {
          <v-draft-day-card [entry]="d" [captures]="capturesFor(d.date)" (changed)="reload()" />
        } @empty {
          <div class="v-empty">No drafts. Add a capture above and press “Process now”.</div>
        }
      </section>

      <section class="captures">
        <div class="head">
          <h3>Captures</h3>
          <div class="filters">
            @for (f of filters; track f.id) {
              <button type="button" class="chip" [class.active]="filter() === f.id" (click)="filter.set(f.id)">{{ f.label }}@if (count(f.id); as n) { <span class="n">{{ n }}</span> }</button>
            }
          </div>
        </div>
        <p class="v-small v-muted">A capture stays here until its drafted item is accepted. Discarded ones are deleted automatically after one day.</p>
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
    .add { display: grid; gap: 0.75rem; }
    .add-head { display: flex; justify-content: space-between; align-items: end; gap: 1rem; flex-wrap: wrap; }
    .day { min-width: 11rem; }
    .run { margin-top: 1rem; } .run.active { border-color: var(--v-agent); }
    .drafts, .captures { margin-top: 1.5rem; display: grid; gap: 0.75rem; }
    .drafts h3, .captures h3 { font-size: var(--v-fs-l); }
    .captures .head { display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; align-items: baseline; }
    .filters { display: flex; gap: 0.35rem; flex-wrap: wrap; }
    .chip { border: 1px solid var(--v-line-strong); background: var(--v-surface); border-radius: 999px; padding: 0.3rem 0.8rem; cursor: pointer; font-size: var(--v-fs-s); display: inline-flex; gap: 0.4rem; align-items: center; }
    .chip.active { background: var(--v-primary-soft); border-color: var(--v-primary); color: var(--v-primary); }
    .chip .n { font-size: var(--v-fs-xs); color: var(--v-ink-3); }
    .cards { display: grid; gap: 0.6rem; }
  `,
})
export class InboxPage {
  readonly api = inject(ApiClient);
  private readonly badges = inject(BadgesService);
  readonly captures = signal<Capture[]>([]);
  readonly drafts = signal<DraftListEntry[]>([]);
  readonly filter = signal<Filter>('open');
  readonly run = signal<AgentRun | null>(null);
  readonly error = signal<string | null>(null);
  readonly filters: { id: Filter; label: string }[] = [
    { id: 'open', label: 'Open' },
    { id: 'assigned', label: 'In draft' },
    { id: 'processed', label: 'Done' },
    { id: 'discarded', label: 'Discarded' },
    { id: 'failed', label: 'Failed' },
    { id: 'all', label: 'All' },
  ];
  targetDate = new Date().toISOString().slice(0, 10);
  private timer: ReturnType<typeof setTimeout> | null = null;

  readonly visible = computed(() => this.captures().filter((c) => this.matches(c, this.filter())));
  readonly running = computed(() => {
    const r = this.run();
    return !!r && !this.finished(r);
  });

  constructor() {
    this.reload();
  }

  reload(): void {
    this.api.captures().subscribe({
      next: (c) => {
        this.captures.set(c);
        this.badges.refresh();
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
    this.api.drafts().subscribe({
      next: (d) => this.drafts.set(d),
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  capturesFor(date: string): Capture[] {
    return this.captures().filter((c) => c.target_date === date);
  }

  count(f: Filter): number {
    return f === 'all' ? 0 : this.captures().filter((c) => this.matches(c, f)).length;
  }

  private matches(c: Capture, f: Filter): boolean {
    if (f === 'all') return true;
    if (f === 'open') return c.status === 'new' || c.status === 'in_progress';
    return c.status === f;
  }

  onUploaded(c: Capture): void {
    this.captures.update((list) => [c, ...list]);
    this.badges.refresh();
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
          if (this.finished(r)) this.reload();
          else this.poll(id);
        },
        error: (e: unknown) => this.error.set(describeError(e)),
      });
    }, 2000);
  }
}
