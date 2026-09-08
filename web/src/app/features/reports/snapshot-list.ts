import { ChangeDetectionStrategy, Component, effect, inject, input, output, signal } from '@angular/core';
import { ApiClient, ReportBlock, ReportSnapshot } from '../../api';
import { describeError } from '../../core/problem';
import { MarkdownPipe } from '../../shared/markdown.pipe';
import { ReportBlockView } from './report-blocks/report-block';

/**
 * Frozen moments of a report. A snapshot keeps the numbers of its period for good;
 * the assessment written for it therefore always refers to what it actually saw.
 * Clicking one opens it below the list.
 */
@Component({
  selector: 'v-snapshot-list',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MarkdownPipe, ReportBlockView],
  template: `
    <section class="v-panel snaps">
      <header>
        <div>
          <h3>Moments</h3>
          <p class="v-small v-muted">A snapshot freezes this period's numbers. The agent writes its assessment for exactly those numbers.</p>
        </div>
        <div class="v-actions">
          <button type="button" class="v-btn primary" (click)="freeze()" [disabled]="busy()">{{ busy() ? 'Freezing…' : 'Freeze this period' }}</button>
        </div>
      </header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
      @if (notice(); as n) { <div class="v-notice">{{ n }}</div> }

      <ul class="list">
        @for (s of snapshots(); track s.id) {
          <li [class.open]="open() === s.id" [attr.data-snapshot]="s.id">
            <button type="button" class="row" (click)="toggle(s)">
              <span class="when">{{ s.today }}</span>
              <span class="what">{{ s.label || s.title }} <span class="v-small v-muted">{{ s.period_start }} → {{ s.period_end }}</span></span>
              <span class="v-tag" [class]="'v-tag ' + (s.status === 'assessed' ? 'closed' : s.status === 'failed' ? 'bad' : 'warn')">{{ s.status === 'frozen' ? 'no assessment yet' : s.status }}</span>
              <span class="chev" aria-hidden="true">{{ open() === s.id ? '▾' : '▸' }}</span>
            </button>
            @if (open() === s.id) {
              <div class="detail">
                @if (detail(); as d) {
                  @if (d.assessment_md) {
                    <div class="assessment">
                      <h4>Assessment @if (d.model) { <span class="v-small v-muted">{{ d.model }}@if (d.cost_usd) { · {{ d.cost_usd.toFixed(2) }} USD }</span> }</h4>
                      <div class="v-md" [innerHTML]="d.assessment_md | markdown"></div>
                    </div>
                  } @else {
                    <p class="v-small v-muted">No assessment yet. Ask the agent in the chat (tool <code>report_assess</code>), or write one yourself.</p>
                    <form class="own" (submit)="submitOwn($event, d)">
                      <textarea name="own" rows="3" placeholder="Your own note on this moment" [value]="ownText" (input)="ownText = $any($event.target).value"></textarea>
                      <button type="submit" class="v-btn" [disabled]="busy() || !ownText.trim()">Save note</button>
                    </form>
                  }
                  <details class="numbers">
                    <summary>Frozen numbers</summary>
                    @if (d.result) {
                      <div class="blocks">@for (b of blocksOf(d); track $index) { <v-report-block [block]="b" /> }</div>
                    }
                  </details>
                  <div class="v-actions">
                    @if (confirmDelete() === d.id) {
                      <span class="v-small">Delete this moment?</span>
                      <button type="button" class="v-btn small danger" (click)="remove(d)">Yes</button>
                      <button type="button" class="v-btn small quiet" (click)="confirmDelete.set(null)">No</button>
                    } @else {
                      <button type="button" class="v-btn small quiet danger" (click)="confirmDelete.set(d.id)">Delete</button>
                    }
                  </div>
                } @else {
                  <p class="v-muted v-small">Loading…</p>
                }
              </div>
            }
          </li>
        } @empty {
          <li class="v-muted v-small empty">No moments yet. Freeze this period to keep its numbers and have them assessed.</li>
        }
      </ul>
    </section>
  `,
  styles: `
    .snaps { display: grid; gap: 0.6rem; }
    .snaps > header { display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; align-items: start; }
    .list { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.35rem; }
    .list li { border: 1px solid var(--v-line); border-radius: var(--v-radius); overflow: hidden; }
    .list li.empty { border: 0; padding: 0.25rem 0; }
    .row { width: 100%; display: grid; grid-template-columns: 6.5rem minmax(0, 1fr) auto 1.5rem; gap: 0.6rem; align-items: center; padding: 0.5rem 0.6rem; background: var(--v-surface); border: 0; cursor: pointer; text-align: left; color: inherit; font: inherit; }
    .row:hover { background: var(--v-surface-2); }
    li.open .row { background: var(--v-surface-2); font-weight: 500; }
    .when { font-variant-numeric: tabular-nums; color: var(--v-ink-2); }
    .what { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
    .chev { color: var(--v-ink-3); text-align: center; }
    .detail { padding: 0.75rem 0.6rem; border-top: 1px solid var(--v-line); display: grid; gap: 0.75rem; }
    .assessment h4 { font-size: var(--v-fs-m); margin-bottom: 0.25rem; }
    .own { display: grid; grid-template-columns: 1fr auto; gap: 0.5rem; align-items: start; }
    .own textarea { padding: 0.5rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); }
    .numbers summary { cursor: pointer; color: var(--v-ink-2); font-size: var(--v-fs-s); }
    .blocks { display: grid; gap: 0.75rem; margin-top: 0.6rem; }
    @media (max-width: 48rem) { .row { grid-template-columns: 1fr auto; } .when { grid-column: 1 / -1; } .own { grid-template-columns: 1fr; } }
  `,
})
export class SnapshotList {
  private readonly api = inject(ApiClient);
  /** Which report the list belongs to, and which period a new snapshot freezes. */
  readonly report = input.required<string>();
  readonly from = input<string | null>(null);
  readonly to = input<string | null>(null);
  readonly asOf = input<string | null>(null);
  readonly created = output<ReportSnapshot>();

  readonly snapshots = signal<ReportSnapshot[]>([]);
  readonly open = signal<string | null>(null);
  readonly detail = signal<ReportSnapshot | null>(null);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly notice = signal<string | null>(null);
  readonly confirmDelete = signal<string | null>(null);
  ownText = '';
  private loadedFor = '';

  constructor() {
    // `report` is a required input: reading it in the constructor would throw.
    effect(() => {
      const report = this.report();
      if (report !== this.loadedFor) this.load();
    });
  }

  load(): void {
    this.loadedFor = this.report();
    this.api.snapshots(this.report()).subscribe({
      next: (s) => this.snapshots.set(s),
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  toggle(s: ReportSnapshot): void {
    if (this.open() === s.id) {
      this.open.set(null);
      return;
    }
    this.open.set(s.id);
    this.detail.set(null);
    this.ownText = '';
    this.api.snapshot(s.id).subscribe({
      next: (d) => this.detail.set(d),
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  blocksOf(s: ReportSnapshot): ReportBlock[] {
    const result = s.result as { blocks?: ReportBlock[] } | null | undefined;
    return result?.blocks ?? [];
  }

  freeze(): void {
    this.busy.set(true);
    this.error.set(null);
    this.notice.set(null);
    this.api.createSnapshot(this.report(), { from: this.from(), to: this.to(), asOf: this.asOf() }).subscribe({
      next: (s) => {
        this.snapshots.update((list) => [s, ...list]);
        this.busy.set(false);
        this.notice.set('Frozen. Ask the agent for its assessment, or write your own note.');
        this.created.emit(s);
      },
      error: (e: unknown) => {
        this.error.set(describeError(e));
        this.busy.set(false);
      },
    });
  }

  submitOwn(event: Event, s: ReportSnapshot): void {
    event.preventDefault();
    const text = this.ownText.trim();
    if (!text) return;
    this.busy.set(true);
    this.api.assessSnapshot(s.id, text).subscribe({
      next: (updated) => {
        this.detail.set({ ...updated, result: s.result });
        this.snapshots.update((list) => list.map((x) => (x.id === updated.id ? { ...x, ...updated } : x)));
        this.busy.set(false);
        this.ownText = '';
      },
      error: (e: unknown) => {
        this.error.set(describeError(e));
        this.busy.set(false);
      },
    });
  }

  remove(s: ReportSnapshot): void {
    this.confirmDelete.set(null);
    this.api.deleteSnapshot(s.id).subscribe({
      next: () => {
        this.snapshots.update((list) => list.filter((x) => x.id !== s.id));
        this.open.set(null);
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }
}
