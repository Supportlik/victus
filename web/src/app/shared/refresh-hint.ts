import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { LiveRefresh } from '../core/live-refresh';
import { I18nService } from '../core/i18n.service';
import { Icon } from './icon';

/**
 * "There is newer data" — the quiet half of live updating (R80).
 *
 * It appears only where a silent refresh would have taken something away: a form that is
 * open, a line that is half typed. Nothing on the page moves until the button is pressed,
 * and dismissing it only hides it — the next change brings it back.
 */
@Component({
  selector: 'v-refresh-hint',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon],
  template: `
    @if (live().pending()) {
      <div class="v-notice stale" role="status">
        <span>{{ i18n.t('There is newer data.') }}</span>
        <span class="v-actions">
          <button type="button" class="v-btn small primary" (click)="live().apply()">{{ i18n.t('Show it') }}</button>
          <button type="button" class="v-btn quiet small" (click)="live().dismiss()" [attr.aria-label]="i18n.t('Dismiss')">
            <v-icon name="close" [size]="16" />
          </button>
        </span>
      </div>
    }
  `,
  styles: `
    .stale { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
  `,
})
export class RefreshHint {
  readonly i18n = inject(I18nService);
  readonly live = input.required<LiveRefresh>();
}
