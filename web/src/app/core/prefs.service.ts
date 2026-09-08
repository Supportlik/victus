import { Injectable, effect, signal } from '@angular/core';

/** Where the app opens after sign-in (and when the brand is clicked). */
export type Landing = 'today' | 'days' | 'inbox' | 'reports';

export const LANDINGS: readonly { id: Landing; label: string }[] = [
  { id: 'today', label: 'Today' },
  { id: 'days', label: 'Days list' },
  { id: 'inbox', label: 'Inbox' },
  { id: 'reports', label: 'Reports' },
];

const LANDING_KEY = 'victus.landing';
const RAIL_KEY = 'victus.railCollapsed';

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage blocked: the preference simply does not persist */
  }
}

/** Per-browser UI preferences that are not worth a server round-trip. */
@Injectable({ providedIn: 'root' })
export class PrefsService {
  readonly landing = signal<Landing>((read(LANDING_KEY) as Landing | null) ?? 'today');
  readonly railCollapsed = signal(read(RAIL_KEY) === '1');

  constructor() {
    effect(() => write(LANDING_KEY, this.landing()));
    effect(() => write(RAIL_KEY, this.railCollapsed() ? '1' : '0'));
  }

  /** Router URL for the configured landing page. */
  landingUrl(): string {
    switch (this.landing()) {
      case 'days':
        return '/days';
      case 'inbox':
        return '/inbox';
      case 'reports':
        return '/reports';
      default:
        return `/days/${new Date().toISOString().slice(0, 10)}`;
    }
  }
}
