import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { BandSpec, BandZone, MacroKey } from '../api';
import { formatMacro, toneOf, ZONE_LABEL } from './format';

/**
 * The one memorable element of the day view: a slim strip that shows where today's value sits
 * against the target band (minimum · optimal range · maximum). No traffic-light dots.
 */
@Component({
  selector: 'v-band-gauge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'v-band-gauge' },
  template: `
    <div class="head">
      <span class="label">{{ label() }}</span>
      <span class="value" [class]="tone()">{{ formatted() }} <span class="unit">{{ unit() }}</span></span>
    </div>
    @if (band(); as b) {
      <div class="strip" role="img" [attr.aria-label]="aria()">
        <span class="seg min" [style.flex]="scale(b.min, b.opt_min)"></span>
        <span class="seg opt" [style.flex]="scale(b.opt_min, b.opt_max)"></span>
        <span class="seg max" [style.flex]="scale(b.opt_max, b.max)"></span>
        @if (markerPct() !== null) {
          <span class="marker" [class]="tone()" [style.left.%]="markerPct()"></span>
        }
      </div>
      <div class="ticks"><span>{{ b.min }}</span><span>{{ b.opt_min }}–{{ b.opt_max }}</span><span>{{ b.max }}</span></div>
    } @else {
      <div class="strip none"></div>
    }
  `,
  styles: `
    :host { display: block; min-width: 9rem; }
    .head { display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem; font-size: var(--v-fs-s); }
    .label { color: var(--v-ink-2); }
    .value { font-weight: 560; font-size: var(--v-fs-m); }
    .value.warn { color: var(--v-warn); }
    .value.bad { color: var(--v-bad); }
    .value.ok { color: var(--v-ok); }
    .unit { font-weight: 400; color: var(--v-ink-3); font-size: var(--v-fs-xs); }
    .strip { position: relative; display: flex; height: 6px; margin: 0.35rem 0 0.2rem; border-radius: 3px; overflow: visible; background: var(--v-surface-2); }
    .seg { height: 100%; }
    .seg.min, .seg.max { background: var(--v-line-strong); }
    .seg.opt { background: var(--v-ok); opacity: 0.55; }
    .seg:first-child { border-radius: 3px 0 0 3px; }
    .seg:nth-child(3) { border-radius: 0 3px 3px 0; }
    .marker { position: absolute; top: -3px; width: 3px; height: 12px; margin-left: -1.5px; border-radius: 2px; background: var(--v-ink); }
    .marker.warn { background: var(--v-warn); }
    .marker.bad { background: var(--v-bad); }
    .marker.ok { background: var(--v-ok); }
    .ticks { display: flex; justify-content: space-between; font-size: var(--v-fs-xs); color: var(--v-ink-3); }
    .strip.none { opacity: 0.4; }
  `,
})
export class BandGauge {
  readonly macro = input.required<MacroKey>();
  readonly label = input.required<string>();
  readonly unit = input('g');
  readonly value = input<number | null | undefined>(null);
  readonly band = input<BandSpec | null | undefined>(null);
  readonly zone = input<BandZone | null | undefined>(null);

  readonly formatted = computed(() => formatMacro(this.value(), this.macro()));
  readonly computedZone = computed<BandZone | null>(() => {
    const z = this.zone();
    if (z) return z;
    const b = this.band();
    const v = this.value();
    if (!b || v === null || v === undefined) return null;
    if (v < b.min) return 'below_min';
    if (v < b.opt_min) return 'below_optimum';
    if (v <= b.opt_max) return 'optimal';
    if (v <= b.max) return 'above_optimum';
    return 'above_max';
  });
  readonly tone = computed(() => toneOf(this.computedZone()));
  readonly aria = computed(() => {
    const z = this.computedZone();
    return `${this.label()} ${this.formatted()} ${this.unit()}${z ? ', ' + ZONE_LABEL[z] : ''}`;
  });

  /** Strip runs from 0.8·min to 1.15·max so the marker can leave the band visibly. */
  private range(b: BandSpec): [number, number] {
    return [Math.min(b.min * 0.8, b.min - 1), Math.max(b.max * 1.15, b.max + 1)];
  }

  scale(from: number, to: number): string {
    return String(Math.max(to - from, 0.0001));
  }

  readonly markerPct = computed<number | null>(() => {
    const b = this.band();
    const v = this.value();
    if (!b || v === null || v === undefined) return null;
    const total = b.max - b.min;
    if (total <= 0) return null;
    const pct = ((v - b.min) / total) * 100;
    return Math.min(Math.max(pct, -2), 102);
  });
}
