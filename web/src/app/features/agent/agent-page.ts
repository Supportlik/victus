import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AgentLock, AgentRun, ApiClient } from '../../api';
import { FormatService } from '../../core/format.service';
import { I18nService } from '../../core/i18n.service';
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
        <div><h2>{{ i18n.t('Agent') }}</h2><p class="sub">{{ i18n.t('Runs turn captures into drafts — one model session per day. Nothing here is approved until you say so.') }}</p></div>
        <div class="v-actions">
          <a class="v-btn" routerLink="/captures">{{ i18n.t('Captures') }}</a>
          <button type="button" class="v-btn" (click)="load()">{{ i18n.t('Refresh') }}</button>
        </div>
      </header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }

      <section class="grid">
        <div class="v-scroll">
          <div class="v-scroll-x">
            <table class="v-table runs">
              <thead><tr><th>{{ i18n.t('Started') }}</th><th>{{ i18n.t('Status') }}</th><th>{{ i18n.t('Mode') }}</th><th>{{ i18n.t('Runner') }}</th><th>{{ i18n.t('Days') }}</th><th>{{ i18n.t('Tokens') }}</th><th>{{ i18n.t('Cost') }}</th><th></th></tr></thead>
              <tbody>
                @for (r of runs(); track r.id) {
                  <tr [class.selected]="selected()?.id === r.id" [attr.data-run]="r.id">
                    <td>{{ started(r) }}</td>
                    <td><span class="v-tag" [class]="'v-tag ' + tagClass(r.status)">{{ i18n.t(r.status.replace('_', ' ')) }}</span></td>
                    <td>{{ i18n.t(r.mode.replace('_', ' ')) }}</td>
                    <td>{{ r.runner ? i18n.t(r.runner) : '–' }}</td>
                    <td class="days">{{ r.days.join(', ') || '–' }}</td>
                    <td class="num">{{ tokens(r) }}</td>
                    <td class="num">{{ r.cost_usd != null ? format.number(r.cost_usd, 2) + ' USD' : '–' }}</td>
                    <td class="actions">
                      <button type="button" class="v-btn small" (click)="select(r)">{{ i18n.t('Details') }}</button>
                      @if (active(r)) { <button type="button" class="v-btn small quiet" (click)="cancel(r)">{{ i18n.t('Cancel') }}</button> }
                    </td>
                  </tr>
                } @empty { <tr><td colspan="8" class="v-muted">{{ i18n.t('No runs yet. Add captures and press “Process now”.') }}</td></tr> }
              </tbody>
            </table>
          </div>
        </div>

        @if (selected(); as r) {
          <section class="v-panel detail" aria-live="polite">
            <h3>{{ i18n.t('Run') }} {{ r.id.slice(0, 8) }} · {{ i18n.t(r.status.replace('_', ' ')) }}</h3>
            <p class="v-small v-muted">
              {{ i18n.t(r.mode.replace('_', ' ')) }} · {{ i18n.t(r.runner ?? 'worker') }} · {{ i18n.t('model') }} {{ r.model ?? '–' }} · {{ i18n.t('prompt') }} {{ r.prompt_version ?? '–' }}
              @if (r.finished_at) { · {{ i18n.t('finished') }} {{ format.moment(r.finished_at) }} }
            </p>
            @if (r.error) { <div class="v-error">{{ r.error }}</div> }
            @if (r.sessions?.length) {
              <h4>{{ i18n.t('Sessions (one per day)') }}</h4>
              <div class="v-scroll-x">
                <table class="v-table sessions">
                  <thead><tr><th>{{ i18n.t('Day') }}</th><th>{{ i18n.t('Outcome') }}</th><th>{{ i18n.t('Input') }}</th><th>{{ i18n.t('Output') }}</th><th>{{ i18n.t('Cost') }}</th></tr></thead>
                  <tbody>
                    @for (s of r.sessions; track s.date) {
                      <tr>
                        <td><a [routerLink]="['/days', s.date]">{{ s.date }}</a></td>
                        <td>{{ s.outcome ?? '–' }}</td>
                        <td class="num">{{ s.input_tokens }}</td><td class="num">{{ s.output_tokens }}</td>
                        <td class="num">{{ format.number(s.cost_usd, 3) }}</td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
            }
            @if (r.summary_md) {
              <div class="v-md summary" [innerHTML]="r.summary_md | markdown"></div>
              <a class="v-btn" routerLink="/drafts">{{ i18n.t('Review drafts') }}</a>
            } @else if (active(r)) {
              <p class="v-muted v-small">{{ i18n.t('Still working — the summary appears when the run finishes.') }}</p>
            }
          </section>
        }
      </section>

      <section class="v-panel locks">
        <h3>{{ i18n.t('Locked days') }}</h3>
        <p class="v-small v-muted">{{ i18n.t('A day is locked while a run drafts it (at most a few minutes). Release a lock only if the run that held it is gone.') }}</p>
        @if (locks().length) {
          <div class="v-scroll-x">
            <table class="v-table">
              <thead><tr><th>{{ i18n.t('Day') }}</th><th>{{ i18n.t('Runner') }}</th><th>{{ i18n.t('Run') }}</th><th>{{ i18n.t('Until') }}</th><th></th></tr></thead>
              <tbody>
                @for (l of locks(); track l.date) {
                  <tr [attr.data-lock]="l.date">
                    <td><a [routerLink]="['/days', l.date]">{{ l.date }}</a></td><td>{{ i18n.t(l.runner) }}</td>
                    <td>{{ l.run_id.slice(0, 8) }}</td><td>{{ format.moment(l.locked_until) }}</td>
                    <td class="actions">
                      @if (confirmUnlock() === l.date) {
                        <span class="confirm">{{ i18n.t('Release?') }} <button type="button" class="v-btn small danger" (click)="unlock(l)">{{ i18n.t('Yes, release') }}</button>
                        <button type="button" class="v-btn small quiet" (click)="confirmUnlock.set(null)">{{ i18n.t('No') }}</button></span>
                      } @else {
                        <button type="button" class="v-btn small quiet" (click)="confirmUnlock.set(l.date)">{{ i18n.t('Force unlock') }}</button>
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        } @else { <p class="v-muted v-small">{{ i18n.t('No day is locked right now.') }}</p> }
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
    .detail { align-self: start; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.6rem; }
    .summary { max-height: 60vh; overflow: auto; }
    .confirm { display: inline-flex; gap: 0.3rem; align-items: center; font-size: var(--v-fs-s); }
  `,
})
export class AgentPage {
  private readonly api = inject(ApiClient);
  readonly i18n = inject(I18nService);
  readonly format = inject(FormatService);
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

  /** When the run started, or — before it started — when it was queued. */
  started(r: AgentRun): string {
    const iso = r.started_at ?? r.created_at;
    return iso ? this.format.moment(iso) : '–';
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
