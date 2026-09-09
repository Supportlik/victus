import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { I18nService } from '../core/i18n.service';
import { NoticeService } from '../core/notice.service';
import { Icon } from './icon';

/**
 * The visible half of NoticeService: the messages, floating over the page.
 *
 * Mounted once in the shell rather than per page, so a message survives the render of
 * whatever triggered it and is readable at any scroll position. On a phone the stack sits
 * above the tab bar, because a confirmation hidden behind the bar is no confirmation.
 */
@Component({
  selector: 'v-notices',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon],
  template: `
    <div class="stack">
      @for (n of notices.notices(); track n.id) {
        <div
          class="notice"
          [class.bad]="n.kind === 'error'"
          [attr.role]="n.kind === 'error' ? 'alert' : 'status'"
          [attr.aria-live]="n.kind === 'error' ? null : 'polite'"
        >
          <span class="text">{{ n.text }}</span>
          <button
            type="button"
            class="close"
            (click)="notices.dismiss(n.id)"
            [attr.aria-label]="i18n.t('Dismiss')"
          >
            <v-icon name="close" [size]="16" />
          </button>
        </div>
      }
    </div>
  `,
  styles: `
    .stack {
      position: fixed;
      inset: auto 1rem 1rem auto;
      z-index: 60;
      display: grid;
      gap: 0.5rem;
      justify-items: end;
      max-width: min(26rem, calc(100vw - 2rem));
      pointer-events: none;
    }
    .notice {
      display: flex;
      align-items: start;
      gap: 0.75rem;
      width: 100%;
      padding: 0.7rem 0.75rem 0.7rem 1rem;
      border: 1px solid var(--v-ok);
      border-left-width: 3px;
      border-radius: var(--v-radius);
      background: var(--v-ok-soft);
      color: var(--v-ink);
      box-shadow: 0 0.4rem 1.2rem rgb(0 0 0 / 0.18);
      pointer-events: auto;
      animation: notice-in 160ms ease-out;
    }
    .notice.bad {
      border-color: var(--v-bad);
      background: var(--v-bad-soft);
    }
    .text { flex: 1; overflow-wrap: anywhere; }
    .close {
      flex: none;
      display: inline-flex;
      padding: 0.2rem;
      border: 0;
      border-radius: var(--v-radius);
      background: none;
      color: var(--v-ink-2);
      cursor: pointer;
      &:hover { color: var(--v-ink); }
    }
    @keyframes notice-in {
      from { opacity: 0; transform: translateY(0.5rem); }
    }

    @media (max-width: 52rem) {
      .stack {
        inset: auto 0.75rem calc(4.5rem + env(safe-area-inset-bottom)) 0.75rem;
        justify-items: stretch;
        max-width: none;
      }
    }

    @media (prefers-reduced-motion: reduce) {
      .notice { animation: none; }
    }
  `,
})
export class Notices {
  protected readonly notices = inject(NoticeService);
  protected readonly i18n = inject(I18nService);
}
