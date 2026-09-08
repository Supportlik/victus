import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiClient, DraftListEntry } from '../../api';
import { describeError } from '../../core/problem';
import { DayNamePipe, MacroPipe } from '../../shared/format';
import { StatusTag } from '../../shared/status-tag';

@Component({
  selector: 'v-drafts-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, StatusTag, MacroPipe, DayNamePipe],
  template: `
    <div class="v-page">
      <header class="v-page-head">
        <div><h2>Drafts</h2><p class="sub">Days the agent prepared. Nothing counts until you approve it.</p></div>
      </header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
      @if (drafts().length === 0) {
        <div class="v-empty">No drafts waiting. Add a capture and press “Process now” to create one.</div>
      } @else {
        <table class="v-table">
          <thead><tr><th>Day</th><th>Status</th><th class="num">Draft items</th><th class="num">Estimates</th><th class="num">kcal</th><th></th></tr></thead>
          <tbody>
            @for (d of drafts(); track d.date) {
              <tr>
                <td>{{ d.date | dayName }}</td>
                <td><v-status-tag [status]="d.status" /></td>
                <td class="num">{{ d.draft_items }}</td>
                <td class="num">{{ d.estimated_items }}</td>
                <td class="num">{{ d.kcal | macro: 'kcal' }}</td>
                <td><a class="v-btn small primary" [routerLink]="['/drafts', d.date]">Review</a></td>
              </tr>
            }
          </tbody>
        </table>
      }
    </div>
  `,
})
export class DraftsPage {
  private readonly api = inject(ApiClient);
  readonly drafts = signal<DraftListEntry[]>([]);
  readonly error = signal<string | null>(null);
  constructor() {
    this.api.drafts().subscribe({ next: (d) => this.drafts.set(d), error: (e: unknown) => this.error.set(describeError(e)) });
  }
}
