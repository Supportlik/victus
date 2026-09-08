import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AgentLock, AgentRun, ApiClient } from '../../api';
import { describeError } from '../../core/problem';
import { MarkdownPipe } from '../../shared/markdown.pipe';

/**
 * Agent runs and locks: what the worker (or an external Claude over MCP) did, what it cost,
 * and which days are currently locked. Queued or running runs can be cancelled; a stuck lock
 * can be released here (the CLI equivalent is `victus agent unlock`).
 */
@Component({
  selector: 'v-agent-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, MarkdownPipe],
  template: `
    <div class="v-page">
      <header class="v-page-head">
        <div><h2>Agent</h2><p class="sub">Runs turn captures into drafts — one model session per day. Nothing here is approved until you say so.</p></div>
        <div class="v-actions">
          <a class="v-btn" routerLink="/captures">Captures</a>
          <button type="button" class="v-btn" (click)="load()">Refresh</button>
        </div>
      </header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }

      <section class="grid">
        <div class="v-scroll">
          <table class="v-table runs">
            <thead><tr><th>Started</th><th>Status</th><th>Mode</th><th>Runner</th><th>Days</th><th>Tokens</th><th>Cost</th><th></th></tr></thead>
            <tbody>
              @for (r of runs(); track r.id) {
                <tr [class.selected]="selected()?.id === r.id" [attr.data-run]="r.id">
                  <td>{{ (r.started_at ?? r.created_at ?? '').replace('T', ' ').slice(0, 16) || '–' }}</td>
                  <td><span class="v-tag" [class]="'v-tag ' + tagClass(r.status)">{{ r.status.replace('_', ' ') }}</span></td>
                  <td>{{ r.mode.replace('_', ' ') }}</td>
                  <td>{{ r.runner ?? '–' }}</td>
                  <td class="days">{{ r.days.join(', ') || '–' }}</td>
                  <td class="num">{{ tokens(r) }}</td>
                  <td class="num">{{ r.cost_usd != null ? r.cost_usd.toFixed(2) + ' USD' : '–' }}</td>
                  <td class="actions">
                    <button type="button" class="v-btn small" (click)="select(r)">Details</button>
                    @if (active(r)) { <button type="button" class="v-btn small quiet" (click)="cancel(r)">Cancel</button> }
                  </td>
                </tr>
              } @empty { <tr><td colspan="8" class="v-muted">No runs yet. Add captures and press “Process now”.</td></tr> }
            </tbody>
          </table>
        </div>

        @if (selected(); as r) {
          <section class="v-panel detail" aria-live="polite">
            <h3>Run {{ r.id.slice(0, 8) }} · {{ r.status.replace('_', ' ') }}</h3>
            <p class="v-small v-muted">
              {{ r.mode.replace('_', ' ') }} · {{ r.runner ?? 'worker' }} · model {{ r.model ?? '–' }} · prompt {{ r.prompt_version ?? '–' }}
              @if (r.finished_at) { · finished {{ r.finished_at.replace('T', ' ').slice(0, 16) }} }
            </p>
            @if (r.error) { <div class="v-error">{{ r.error }}</div> }
            @if (r.sessions?.length) {
              <h4>Sessions (one per day)</h4>
              <table class="v-table sessions">
                <thead><tr><th>Day</th><th>Outcome</th><th>In</th><th>Out</th><th>Cost</th></tr></thead>
                <tbody>
                  @for (s of r.sessions; track s.date) {
                    <tr>
                      <td><a [routerLink]="['/days', s.date]">{{ s.date }}</a></td>
                      <td>{{ s.outcome ?? '–' }}</td>
                      <td class="num">{{ s.input_tokens }}</td><td class="num">{{ s.output_tokens }}</td>
                      <td class="num">{{ s.cost_usd.toFixed(3) }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            }
            @if (r.summary_md) {
              <div class="v-md summary" [innerHTML]="r.summary_md | markdown"></div>
              <a class="v-btn" routerLink="/drafts">Review drafts</a>
            } @else if (active(r)) {
              <p class="v-muted v-small">Still working — the summary appears when the run finishes.</p>
            }
          </section>
        }
      </section>

      <section class="v-panel locks">
        <h3>Locked days</h3>
        <p class="v-small v-muted">A day is locked while a run drafts it (at most a few minutes). Release a lock only if the run that held it is gone.</p>
        @if (locks().length) {
          <table class="v-table">
            <thead><tr><th>Day</th><th>Runner</th><th>Run</th><th>Until</th><th></th></tr></thead>
            <tbody>
              @for (l of locks(); track l.date) {
                <tr [attr.data-lock]="l.date">
                  <td><a [routerLink]="['/days', l.date]">{{ l.date }}</a></td><td>{{ l.runner }}</td>
                  <td>{{ l.run_id.slice(0, 8) }}</td><td>{{ l.locked_until.replace('T', ' ').slice(0, 16) }}</td>
                  <td class="actions">
                    @if (confirmUnlock() === l.date) {
                      <span class="confirm">Release? <button type="button" class="v-btn small danger" (click)="unlock(l)">Yes, release</button>
                      <button type="button" class="v-btn small quiet" (click)="confirmUnlock.set(null)">No</button></span>
                    } @else {
                      <button type="button" class="v-btn small quiet" (click)="confirmUnlock.set(l.date)">Force unlock</button>
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>
        } @else { <p class="v-muted v-small">No day is locked right now.</p> }
      </section>
    </div>
  `,
  styles: `
    .grid { display: grid; gap: 1rem; grid-template-columns: minmax(0, 1fr); margin-bottom: 1rem; }
    .detail { margin-top: 0.75rem; }
    .v-scroll { overflow-x: auto; }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .days { max-width: 14rem; white-space: normal; }
    .actions { white-space: nowrap; display: flex; gap: 0.3rem; }
    tr.selected td { background: var(--v-agent-soft); }
    .detail { align-self: start; display: grid; gap: 0.6rem; }
    .summary { max-height: 60vh; overflow: auto; }
    .confirm { display: inline-flex; gap: 0.3rem; align-items: center; font-size: var(--v-fs-s); }
  `,
})
export class AgentPage {
  private readonly api = inject(ApiClient);
  readonly runs = signal<AgentRun[]>([]);
  readonly locks = signal<AgentLock[]>([]);
  readonly selected = signal<AgentRun | null>(null);
  readonly confirmUnlock = signal<string | null>(null);
  readonly error = signal<string | null>(null);

  constructor() {
    this.load();
  }

  load(): void {
    this.error.set(null);
    this.api.agentRuns({ limit: 50 }).subscribe({ next: (r) => this.runs.set(r), error: (e: unknown) => this.error.set(describeError(e)) });
    this.api.agentLocks().subscribe({ next: (l) => this.locks.set(l), error: (e: unknown) => this.error.set(describeError(e)) });
  }

  select(r: AgentRun): void {
    this.api.agentRun(r.id).subscribe({ next: (full) => this.selected.set(full), error: (e: unknown) => this.error.set(describeError(e)) });
  }

  cancel(r: AgentRun): void {
    this.api.cancelAgentRun(r.id).subscribe({
      next: (u) => {
        this.runs.update((list) => list.map((x) => (x.id === u.id ? u : x)));
        if (this.selected()?.id === u.id) this.selected.set(u);
        this.api.agentLocks().subscribe({ next: (l) => this.locks.set(l) });
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  unlock(l: AgentLock): void {
    this.api.forceUnlock(l.date).subscribe({
      next: () => {
        this.locks.update((list) => list.filter((x) => x.date !== l.date));
        this.confirmUnlock.set(null);
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  active(r: AgentRun): boolean {
    return r.status === 'queued' || r.status === 'running';
  }

  tokens(r: AgentRun): string {
    const total = (r.input_tokens ?? 0) + (r.output_tokens ?? 0);
    return total ? total.toLocaleString('en-US') : '–';
  }

  tagClass(s: AgentRun['status']): string {
    return s === 'finished' ? 'closed' : s === 'failed' || s === 'budget_exceeded' ? 'bad' : s === 'running' ? 'draft' : s === 'queued' ? 'warn' : '';
  }
}
