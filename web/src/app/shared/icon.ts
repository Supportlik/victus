import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import {
  CalendarCheck,
  CalendarDays,
  Camera,
  ChartSpline,
  ChefHat,
  ChevronsLeft,
  ChevronsRight,
  Ellipsis,
  Images,
  Inbox,
  LogOut,
  Mic,
  Moon,
  Scale,
  Settings,
  ShoppingBasket,
  Sparkles,
  Sun,
  SunMoon,
  X,
} from 'lucide';

/** One node of a Lucide icon: a tag plus its attributes. */
type Node = [string, Record<string, string>];

/**
 * The icons the interface uses, by name. Importing them one by one keeps the rest of
 * Lucide out of the bundle; adding an icon means adding it here.
 */
const ICONS: Record<string, Node[]> = {
  today: CalendarCheck as Node[],
  days: CalendarDays as Node[],
  inbox: Inbox as Node[],
  products: ShoppingBasket as Node[],
  recipes: ChefHat as Node[],
  weight: Scale as Node[],
  reports: ChartSpline as Node[],
  agent: Sparkles as Node[],
  settings: Settings as Node[],
  more: Ellipsis as Node[],
  collapse: ChevronsLeft as Node[],
  expand: ChevronsRight as Node[],
  scheme: SunMoon as Node[],
  light: Sun as Node[],
  dark: Moon as Node[],
  signout: LogOut as Node[],
  close: X as Node[],
  camera: Camera as Node[],
  images: Images as Node[],
  mic: Mic as Node[],
};

export type IconName = keyof typeof ICONS;

function svg(nodes: Node[], size: number, stroke: number): string {
  const body = nodes
    .map(([tag, attrs]) => {
      const a = Object.entries(attrs)
        .map(([k, v]) => `${k}="${v}"`)
        .join(' ');
      return `<${tag} ${a} />`;
    })
    .join('');
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" ` +
    `fill="none" stroke="currentColor" stroke-width="${stroke}" stroke-linecap="round" ` +
    `stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`
  );
}

/** Built once per icon, size and weight; the same icon is asked for on every render. */
const CACHE = new Map<string, SafeHtml>();

/**
 * A Lucide icon, drawn in the current text colour.
 *
 * The markup is built from the icon package's own path data, which is static and part of the
 * bundle, never anything a user typed. That is why trusting it is safe here; nothing else in
 * the app may take this shortcut.
 */
@Component({
  selector: 'v-icon',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="i" [innerHTML]="html()"></span>`,
  styles: `
    .i { display: inline-flex; align-items: center; justify-content: center; line-height: 0; }
    svg { display: block; }
  `,
})
export class Icon {
  private readonly sanitizer = inject(DomSanitizer);
  readonly name = input.required<IconName | string>();
  readonly size = input(20);
  /** Thinner lines read better at small sizes; heavier ones mark the active entry. */
  readonly stroke = input(1.75);

  readonly html = computed<SafeHtml>(() => {
    const nodes = ICONS[this.name()];
    if (!nodes) return '';
    const key = `${this.name()}|${this.size()}|${this.stroke()}`;
    let found = CACHE.get(key);
    if (!found) {
      found = this.sanitizer.bypassSecurityTrustHtml(svg(nodes, this.size(), this.stroke()));
      CACHE.set(key, found);
    }
    return found;
  });
}
