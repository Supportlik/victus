import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { ApiClient, Health } from './api';
import { AuthService } from './core/auth/auth.service';

interface NavItem {
  path: string;
  label: string;
  glyph: string;
}

/**
 * Application shell: a narrow navigation rail on desktop, a bottom bar on phones,
 * the routed page next to it and the API health line in the footer of the rail.
 */
@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  private readonly api = inject(ApiClient);
  protected readonly auth = inject(AuthService);

  protected readonly title = signal('Victus');
  protected readonly health = signal<Health | null>(null);
  protected readonly apiError = signal<string | null>(null);

  protected readonly nav: NavItem[] = [
    { path: '/days', label: 'Days', glyph: '▤' },
    { path: '/drafts', label: 'Drafts', glyph: '✎' },
    { path: '/products', label: 'Products', glyph: '◆' },
    { path: '/recipes', label: 'Recipes', glyph: '❖' },
    { path: '/weight', label: 'Weight', glyph: '⚖' },
    { path: '/reports', label: 'Reports', glyph: '▥' },
    { path: '/captures', label: 'Captures', glyph: '⏺' },
    { path: '/settings', label: 'Settings', glyph: '⚙' },
  ];

  protected readonly todayLink = computed(() => `/days/${new Date().toISOString().slice(0, 10)}`);

  constructor() {
    this.api.health().subscribe({
      next: (h) => this.health.set(h),
      error: (e: unknown) => this.apiError.set(e instanceof Error ? e.message : 'API unreachable'),
    });
  }

  protected logout(): void {
    void this.auth.logout();
  }
}
