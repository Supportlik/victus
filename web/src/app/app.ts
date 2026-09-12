import { Component, OnDestroy, computed, effect, inject, signal, untracked } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { ApiClient, Health } from './api';
import { AuthService } from './core/auth/auth.service';
import { BadgesService } from './core/badges.service';
import { FormatService, todayLocal } from './core/format.service';
import { I18nService } from './core/i18n.service';
import { LiveService } from './core/live.service';
import { PrefsService } from './core/prefs.service';
import { describeError } from './core/problem';
import { ThemeService } from './core/theme.service';
import { Icon } from './shared/icon';
import { Logo } from './shared/logo';
import { Notices } from './shared/notices';

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

/** How long to wait before asking again while the API does not answer. */
const HEALTH_RETRY_MS = 60_000;

/** What the footer line says about the API, in the order the states matter. */
export type ApiState = 'checking' | 'down' | 'reconnecting' | 'ok';

/**
 * Application shell: a narrow navigation rail on desktop, a bottom bar on phones,
 * the routed page next to it and the API health line in the footer of the rail.
 */
@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Icon, Logo, Notices],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App implements OnDestroy {
  private readonly api = inject(ApiClient);
  protected readonly auth = inject(AuthService);
  protected readonly badges = inject(BadgesService);
  protected readonly live = inject(LiveService);
  protected readonly theme = inject(ThemeService);
  protected readonly prefs = inject(PrefsService);
  private readonly format = inject(FormatService);
  protected readonly i18n = inject(I18nService);

  protected readonly title = signal('Victus');
  protected readonly health = signal<Health | null>(null);
  protected readonly apiError = signal<string | null>(null);
  protected readonly nudgeDismissed = signal(App.readDismissed());
  private healthRetry: ReturnType<typeof setTimeout> | null = null;

  /**
   * The three states the footer has to keep apart: the API does not answer, the stream is
   * away and trying, or everything stands and the version is worth showing.
   *
   * A stream that has never been live is a page still starting, not one that lost its
   * connection — saying "reconnecting" there would be wrong on every first load.
   */
  protected readonly apiState = computed<ApiState>(() => {
    if (this.apiError()) return 'down';
    if (!this.health()) return 'checking';
    return this.live.wasLive() && this.live.state() === 'connecting' ? 'reconnecting' : 'ok';
  });

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

  protected readonly todayLink = computed(() => `/days/${todayLocal(this.format.timezone())}`);
  protected readonly homeLink = computed(() => this.prefs.landingUrl());
  protected readonly showNudge = computed(
    () => this.auth.needsSecondPasskey() && !this.auth.isRecoverySession() && !this.nudgeDismissed(),
  );

  constructor() {
    this.checkHealth();
    effect(() => {
      if (this.auth.isAuthenticated() && !this.auth.isRecoverySession()) {
        this.badges.start();
        this.live.start();
      } else {
        this.badges.stop();
        this.live.stop();
      }
    });
    // The version line was fetched exactly once, so an outage stayed on screen long after
    // the API came back. The stream is the first thing that knows it answers again: every
    // time it stands, the line is asked again and heals itself. Only when there is
    // something to heal, or after a break — a stream that connects on a page which never
    // saw a problem has nothing to ask about.
    effect(() => {
      const standing = this.live.connected();
      untracked(() => {
        if (standing && (this.apiError() !== null || this.live.reconnects() > 0)) this.checkHealth();
      });
    });
    // the regional settings decide how numbers and days read; mirror them for the next load
    effect(() => {
      if (!this.auth.isAuthenticated() || this.auth.isRecoverySession()) return;
      this.api.settings().subscribe({
        next: (v) => {
          const regional = (v.data['regional'] ?? {}) as {
            locale?: string;
            timezone?: string;
            language?: string;
          };
          this.format.adopt(regional.locale, regional.timezone);
          this.i18n.adopt(regional.language);
        },
        error: () => undefined,
      });
    });
  }

  ngOnDestroy(): void {
    if (this.healthRetry) clearTimeout(this.healthRetry);
    this.healthRetry = null;
  }

  /**
   * Ask which version is running, and keep asking while it does not answer.
   *
   * Nothing on the page is thrown away when this fails: the routed view keeps whatever it
   * already fetched, and only this one line changes. A browser without `EventSource` never
   * reconnects, so the retry timer is what heals the line there.
   */
  private checkHealth(): void {
    if (this.healthRetry) clearTimeout(this.healthRetry);
    this.healthRetry = null;
    this.api.health().subscribe({
      next: (h) => {
        this.health.set(h);
        this.apiError.set(null);
      },
      error: (e: unknown) => {
        this.apiError.set(describeError(e));
        this.healthRetry = setTimeout(() => {
          this.healthRetry = null;
          this.checkHealth();
        }, HEALTH_RETRY_MS);
      },
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
    return this.i18n.t(s === 'system' ? 'Auto' : s === 'light' ? 'Light' : 'Dark');
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
