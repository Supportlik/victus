import { Component, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { RouterOutlet } from '@angular/router';

/** Shape of GET /api/v1/health (kept stable from Stage 0 on). */
export interface Health {
  status: string;
  version: string;
  checks: Record<string, string>;
}

@Component({
  imports: [RouterOutlet],
  selector: 'app-root',
  styleUrl: './app.scss',
  templateUrl: './app.html',
})
export class App {
  private readonly http = inject(HttpClient);

  protected readonly title = signal('Victus');
  protected readonly health = signal<Health | null>(null);
  protected readonly apiError = signal<string | null>(null);

  constructor() {
    this.http.get<Health>('/api/v1/health').subscribe({
      next: (h) => this.health.set(h),
      error: (e: unknown) => this.apiError.set(e instanceof Error ? e.message : 'API unreachable'),
    });
  }
}
