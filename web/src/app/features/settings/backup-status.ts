import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, input, OnInit, signal } from '@angular/core';
import { ApiClient, BackupJob, Health } from '../../api';
import { FormatService } from '../../core/format.service';
import { I18nService } from '../../core/i18n.service';

/** How many recorded backups the settings page lists. */
export const RECENT_BACKUPS = 5;

/**
 * The last backup as `/health` reports it, and the few before it.
 *
 * "Never" is said out loud: an instance without the stack's backup service and without a
 * host backup that reports in has no backup Victus knows about, and a missing line would
 * read as "fine". The list needs `admin`; without it the list is simply left out.
 */
@Component({
  selector: 'v-backup-status',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="backup" [class.warn]="degraded()">
      <p class="last">
        <span class="label">{{ i18n.t('Last backup') }}</span>
        @if (health().backup_age_hours != null) {
          <span class="age">{{ i18n.t('{n} h ago', { n: health().backup_age_hours! }) }}</span>
          @if (health().backup_last_at; as at) { <span class="v-muted at">({{ format.moment(at) }})</span> }
        } @else {
          <span class="age">{{ i18n.t('never') }}</span>
        }
      </p>
      @if (degraded()) {
        <p class="hint" role="status">
          @if (health().backup_age_hours == null) {
            {{ i18n.t('Victus knows of no backup of this instance. Without the backup service of the stack, or a host backup that reports in with victus backup record, nothing here is backed up.') }}
          } @else {
            {{ i18n.t('The newest backup is older than {n} h.', { n: health().backup_max_age_hours ?? 30 }) }}
          }
          {{ i18n.t('How to set it up:') }} <code>docs/BACKUP.md</code>
        </p>
      }
      @if (jobs().length) {
        <table class="v-table jobs">
          <caption class="v-small v-muted">{{ i18n.t('Recent backups') }}</caption>
          <thead><tr><th>{{ i18n.t('Finished') }}</th><th>{{ i18n.t('Status') }}</th><th>{{ i18n.t('Where') }}</th><th class="num">{{ i18n.t('Size') }}</th></tr></thead>
          <tbody>
            @for (j of jobs(); track j.id) {
              <tr [class.bad]="j.status === 'failed' || j.status === 'verify_failed'">
                <td>{{ j.finished_at ? format.moment(j.finished_at) : '–' }}</td>
                <td>
                  @switch (j.status) {
                    @case ('finished') { {{ i18n.t('finished') }} }
                    @case ('failed') { {{ i18n.t('failed') }} }
                    @case ('verify_failed') { {{ i18n.t('verification failed') }} }
                    @default { {{ i18n.t('running') }} }
                  }
                  @if (j.error) { <span class="v-small v-muted err">{{ j.error }}</span> }
                </td>
                <td><code>{{ j.path ?? '–' }}</code></td>
                <td class="num">{{ size(j.size) }}</td>
              </tr>
            }
          </tbody>
        </table>
      } @else if (jobsError()) {
        <p class="v-small v-muted">{{ i18n.t('Backup history unavailable.') }}</p>
      }
    </div>
  `,
  styles: `
    .backup { margin-top: 0.75rem; display: grid; gap: 0.5rem; min-width: 0; }
    .last { margin: 0; display: flex; flex-wrap: wrap; gap: 0.25rem 0.5rem; align-items: baseline; }
    .label { font-size: var(--v-fs-xs); color: var(--v-ink-3); }
    .hint { margin: 0; padding: 0.5rem 0.75rem; border-radius: var(--v-radius); border: 1px solid var(--v-line-strong); background: var(--v-surface-2); }
    .warn .hint { border-color: var(--v-warn); background: var(--v-warn-soft); color: var(--v-warn-ink); }
    .jobs { width: 100%; }
    .jobs caption { text-align: left; }
    .jobs code { word-break: break-all; }
    .err { display: block; }
    tr.bad td { color: var(--v-bad-ink); }
    code { background: var(--v-surface-2); padding: 0.1rem 0.3rem; border-radius: 3px; }
  `,
})
export class BackupStatus implements OnInit {
  private readonly api = inject(ApiClient);
  readonly i18n = inject(I18nService);
  readonly format = inject(FormatService);

  readonly health = input.required<Health>();
  readonly jobs = signal<BackupJob[]>([]);
  /** Set when the list could not be read for a reason other than a missing `admin` scope. */
  readonly jobsError = signal(false);
  readonly degraded = computed(() => this.health().checks?.['backup'] !== 'ok');

  /** A size a person can read: kilobytes below one megabyte, so a small archive is not "0.0 MB". */
  size(bytes: number | null | undefined): string {
    if (bytes == null) return '–';
    if (bytes < 1e6) return this.i18n.t('{n} KB', { n: this.format.number(Math.max(bytes / 1e3, 0.1), bytes < 1e4 ? 1 : 0) });
    return this.i18n.t('{n} MB', { n: this.format.number(bytes / 1e6, 1) });
  }

  ngOnInit(): void {
    this.api.backupJobs(RECENT_BACKUPS).subscribe({
      next: (jobs) => {
        this.jobs.set(jobs);
        this.jobsError.set(false);
      },
      error: (e: unknown) => {
        this.jobs.set([]);
        // no admin scope: the list is not this reader's business, and not an error either
        this.jobsError.set(!(e instanceof HttpErrorResponse && e.status === 403));
      },
    });
  }
}
