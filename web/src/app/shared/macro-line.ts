import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { MACRO_KEYS, MACRO_UNIT, MacroKey, Macros } from '../api';
import { formatMacro } from './format';

/** Compact one-line macro summary: "1,383 kcal · P 154.9 · C 116.6 · F 28.4 · Fi 12.3 · S 7.25". */
@Component({
  selector: 'v-macro-line',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="kcal">{{ fmt(m().kcal, 'kcal') }} kcal</span>
    @for (k of rest; track k) {
      <span class="part"><abbr [title]="title[k]">{{ short[k] }}</abbr> {{ fmt(m()[k], k) }}</span>
    }
  `,
  styles: `
    :host { display: inline-flex; gap: 0.75rem; flex-wrap: wrap; font-size: var(--v-fs-s); color: var(--v-ink-2); }
    .kcal { color: var(--v-ink); font-weight: 560; }
    abbr { text-decoration: none; color: var(--v-ink-3); }
  `,
})
export class MacroLine {
  readonly m = input.required<Macros>();
  readonly rest = MACRO_KEYS.filter((k) => k !== 'kcal');
  readonly short: Record<MacroKey, string> = { kcal: 'kcal', protein: 'P', carbs: 'C', fat: 'F', fiber: 'Fi', salt: 'S' };
  readonly title: Record<MacroKey, string> = {
    kcal: 'Calories',
    protein: `Protein (${MACRO_UNIT.protein})`,
    carbs: 'Carbohydrates (g)',
    fat: 'Fat (g)',
    fiber: 'Fiber (g)',
    salt: 'Salt (g)',
  };
  fmt(v: number | null | undefined, k: MacroKey): string {
    return formatMacro(v, k);
  }
}
