import { DOCUMENT } from '@angular/common';
import { Injectable, effect, inject, signal } from '@angular/core';

/** Light/dark follows the device by default; a person can pin one. */
export type Scheme = 'system' | 'light' | 'dark';

export interface Palette {
  id: string;
  label: string;
  /** Accent swatch for the picker. */
  swatch: string;
}

/** Colour palettes; the CSS for each lives in styles.scss under `html[data-palette]`. */
export const PALETTES: readonly Palette[] = [
  { id: 'graphite', label: 'Graphite', swatch: '#2a78d6' },
  { id: 'forest', label: 'Forest', swatch: '#2f8f5b' },
  { id: 'ocean', label: 'Ocean', swatch: '#0f7f9f' },
  { id: 'clay', label: 'Clay', swatch: '#c2572b' },
  { id: 'plum', label: 'Plum', swatch: '#7b4bb7' },
  { id: 'contrast', label: 'High contrast', swatch: '#000000' },
];

const SCHEME_KEY = 'victus.scheme';
const PALETTE_KEY = 'victus.palette';

function read(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode or blocked storage: the choice simply does not persist */
  }
}

/**
 * Appearance settings, stored per browser. Applied as `data-scheme` / `data-palette`
 * on <html>, which the global stylesheet turns into colour tokens.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly doc = inject(DOCUMENT);
  readonly palettes = PALETTES;
  readonly scheme = signal<Scheme>(read(SCHEME_KEY, 'system') as Scheme);
  readonly palette = signal<string>(read(PALETTE_KEY, 'graphite'));

  constructor() {
    let first = true;
    effect(() => {
      const scheme = this.scheme();
      const palette = PALETTES.some((p) => p.id === this.palette()) ? this.palette() : 'graphite';
      const root = this.doc.documentElement;
      const changing = !first && (root.dataset['scheme'] !== scheme || root.dataset['palette'] !== palette);
      first = false;
      // Every colour changes at once, so no element should animate its way there: a
      // page-wide fade reads as a fault, and Chrome otherwise keeps the pre-switch value
      // of any transitioned property that takes its colour from a custom property — the
      // rail stayed dark on a light page until the next reload.
      if (changing) {
        root.classList.add('v-switching');
      }
      root.dataset['scheme'] = scheme;
      root.dataset['palette'] = palette;
      write(SCHEME_KEY, scheme);
      write(PALETTE_KEY, palette);
      if (changing) {
        void root.offsetHeight;
        requestAnimationFrame(() => root.classList.remove('v-switching'));
      }
    });
  }

  cycleScheme(): void {
    const order: Scheme[] = ['system', 'light', 'dark'];
    this.scheme.set(order[(order.indexOf(this.scheme()) + 1) % order.length]);
  }
}
