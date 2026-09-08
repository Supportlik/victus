import { Component, computed, effect, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { ApiClient, Health } from './api';
import { AuthService } from './core/auth/auth.service';
import { BadgesService } from './core/badges.service';
import { PrefsService } from './core/prefs.service';
import { ThemeService } from './core/theme.service';
import { Logo } from './shared/logo';

interface NavItem {
  path: string;
  label: string;
  glyph: string;
  /** Which badge counter to show next to the label. */
  badge?: 'inbox' | 'days' | 'products';
}

const NUDGE_KEY = 'victus.passkeyNudgeDismissed';

/**
 * Application shell: a narrow navigation rail on desktop, a bottom bar on phones,
 * the routed page next to it and the API health line in the footer of the rail.
 */
@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Logo],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  private readonly api = inject(ApiClient);
  protected readonly auth = inject(AuthService);
  protected readonly badges = inject(BadgesService);
  protected readonly theme = inject(ThemeService);
  protected readonly prefs = inject(PrefsService);

  protected readonly title = signal('Victus');
  protected readonly health = signal<Health | null>(null);
  protected readonly apiError = signal<string | null>(null);
  protected readonly nudgeDismissed = signal(App.readDismissed());

  /** Nine entries before Inbox merged captures and drafts. */
  protected readonly nav: NavItem[] = [
    { path: '/days', label: 'Days', glyph: '▤', badge: 'days' },
    { path: '/inbox', label: 'Inbox', glyph: '⏺', badge: 'inbox' },
    { path: '/products', label: 'Products', glyph: '◆', badge: 'products' },
    { path: '/recipes', label: 'Recipes', glyph: '❖' },
    { path: '/weight', label: 'Weight', glyph: '⚖' },
    { path: '/reports', label: 'Reports', glyph: '▥' },
    { path: '/agent', label: 'Agent', glyph: '✦' },
    { path: '/settings', label: 'Settings', glyph: '⚙' },
  ];

  protected readonly todayLink = computed(() => `/days/${new Date().toISOString().slice(0, 10)}`);
  protected readonly homeLink = computed(() => this.prefs.landingUrl());
  protected readonly showNudge = computed(
    () => this.auth.needsSecondPasskey() && !this.auth.isRecoverySession() && !this.nudgeDismissed(),
  );

  constructor() {
    this.api.health().subscribe({
      next: (h) => this.health.set(h),
      error: (e: unknown) => this.apiError.set(e instanceof Error ? e.message : 'API unreachable'),
    });
    effect(() => {
      if (this.auth.isAuthenticated() && !this.auth.isRecoverySession()) this.badges.start();
      else this.badges.stop();
    });
  }

  protected badge(item: NavItem): number {
    switch (item.badge) {
      case 'inbox':
        return this.badges.newCaptures() + this.badges.draftDays();
      case 'days':
        return this.badges.openDays();
      case 'products':
        return this.badges.pendingProposals();
      default:
        return 0;
    }
  }

  protected dismissNudge(): void {
    this.nudgeDismissed.set(true);
    try {
      localStorage.setItem(NUDGE_KEY, '1');
    } catch {
      /* storage blocked: the notice returns next session, nothing else breaks */
    }
  }

  protected schemeLabel(): string {
    const s = this.theme.scheme();
    return s === 'system' ? 'Auto' : s === 'light' ? 'Light' : 'Dark';
  }

  protected logout(): void {
    void this.auth.logout();
  }

  private static readDismissed(): boolean {
    try {
      return localStorage.getItem(NUDGE_KEY) === '1';
    } catch {
      return false;
    }
  }
}
