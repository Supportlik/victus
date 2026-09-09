import { Component, computed, effect, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { ApiClient, Health } from './api';
import { AuthService } from './core/auth/auth.service';
import { BadgesService } from './core/badges.service';
import { PrefsService } from './core/prefs.service';
import { ThemeService } from './core/theme.service';
import { Icon } from './shared/icon';
import { Logo } from './shared/logo';

interface NavItem {
  path: string;
  label: string;
  /** Icon name from shared/icon.ts. */
  icon: string;
  /** Which badge counter to show next to the label. */
  badge?: 'inbox' | 'days' | 'products';
  /** On a phone the bottom bar shows only the primary entries; the rest sit behind "More". */
  primary?: boolean;
}

const NUDGE_KEY = 'victus.passkeyNudgeDismissed';

/**
 * Application shell: a narrow navigation rail on desktop, a bottom bar on phones,
 * the routed page next to it and the API health line in the footer of the rail.
 */
@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Icon, Logo],
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
    { path: '/days', label: 'Days', icon: 'days', badge: 'days', primary: true },
    { path: '/inbox', label: 'Inbox', icon: 'inbox', badge: 'inbox', primary: true },
    { path: '/products', label: 'Products', icon: 'products', badge: 'products', primary: true },
    { path: '/recipes', label: 'Recipes', icon: 'recipes' },
    { path: '/weight', label: 'Weight', icon: 'weight' },
    { path: '/reports', label: 'Reports', icon: 'reports', primary: true },
    { path: '/agent', label: 'Agent', icon: 'agent' },
    { path: '/settings', label: 'Settings', icon: 'settings' },
  ];

  /** Bottom bar on a phone: four entries plus "More", so nothing has to scroll sideways. */
  protected readonly primaryNav = this.nav.filter((i) => i.primary);
  protected readonly secondaryNav = this.nav.filter((i) => !i.primary);
  protected readonly moreOpen = signal(false);

  /** Anything waiting behind "More" is worth a dot on the button. */
  protected readonly moreBadge = computed(() =>
    this.secondaryNav.reduce((n, item) => n + this.badge(item), 0),
  );

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

  protected closeMore(): void {
    this.moreOpen.set(false);
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
