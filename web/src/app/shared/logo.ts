import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * The Victus mark: a bowl whose rim forms a "V", with a single leaf — food, kept simple.
 * Inline SVG so it follows the palette (`currentColor` = accent, leaf = ok colour).
 */
@Component({
  selector: 'v-logo',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg [attr.width]="size()" [attr.height]="size()" viewBox="0 0 64 64" role="img" aria-label="Victus">
      <defs>
        <linearGradient id="v-bowl" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="currentColor" stop-opacity="0.95" />
          <stop offset="1" stop-color="currentColor" stop-opacity="0.65" />
        </linearGradient>
      </defs>
      <path d="M8 22 L32 54 L56 22 Z" fill="url(#v-bowl)" />
      <path d="M8 22 Q32 34 56 22 L56 28 Q32 40 8 28 Z" fill="currentColor" opacity="0.35" />
      <path d="M36 6 C46 6 50 12 50 18 C42 18 37 14 36 6 Z" fill="var(--v-ok, #1baf7a)" />
      <path d="M36 6 C40 11 43 15 49 18" stroke="var(--v-bg, #fff)" stroke-width="1.5" fill="none" opacity="0.7" />
    </svg>
  `,
  styles: `:host { display: inline-flex; color: var(--v-primary); line-height: 0; }`,
})
export class Logo {
  readonly size = input(28);
}
