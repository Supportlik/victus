import { Injectable, inject, signal } from '@angular/core';
import { ApiClient } from '../api';

function iso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/**
 * Counts shown as badges in the navigation: captures the agent has not seen,
 * days with drafts waiting for approval, and days still open before today.
 * Polled every minute while the shell is visible; `refresh()` after writes.
 */
@Injectable({ providedIn: 'root' })
export class BadgesService {
  private readonly api = inject(ApiClient);
  readonly newCaptures = signal(0);
  readonly draftDays = signal(0);
  readonly openDays = signal(0);
  private timer: ReturnType<typeof setInterval> | null = null;

  start(): void {
    if (this.timer) return;
    this.refresh();
    this.timer = setInterval(() => this.refresh(), 60_000);
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  refresh(): void {
    const quiet = { error: () => undefined };
    this.api.captures('new').subscribe({ next: (c) => this.newCaptures.set(c.length), ...quiet });
    this.api.drafts().subscribe({ next: (d) => this.draftDays.set(d.length), ...quiet });
    const today = iso(new Date());
    const from = iso(new Date(Date.now() - 60 * 86_400_000));
    this.api.days(from, today, 'open').subscribe({
      next: (days) => this.openDays.set(days.filter((d) => d.date < today).length),
      ...quiet,
    });
  }
}
