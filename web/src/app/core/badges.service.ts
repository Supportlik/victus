import { Injectable, effect, inject, signal } from '@angular/core';
import { ApiClient } from '../api';
import { isoDayIn } from './format.service';
import { LiveService } from './live.service';

function iso(d: Date): string {
  return isoDayIn(d);
}

/**
 * Counts shown as badges in the navigation: captures the agent has not seen,
 * days with drafts waiting for approval, and days still open before today.
 *
 * The change stream sends exactly these four numbers with every message, so while it is
 * live they are taken from it and the four requests are not made at all. The minute poll
 * stays for when the stream is not there — a browser without `EventSource`, a proxy that
 * refuses it — and `refresh()` is still called after a write, which is a read-back rather
 * than a poll.
 */
@Injectable({ providedIn: 'root' })
export class BadgesService {
  private readonly api = inject(ApiClient);
  private readonly live = inject(LiveService);
  readonly newCaptures = signal(0);
  readonly draftDays = signal(0);
  readonly openDays = signal(0);
  readonly pendingProposals = signal(0);
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor() {
    effect(() => {
      const counts = this.live.counts();
      if (!counts || !this.live.connected()) return;
      this.newCaptures.set(counts.new_captures);
      this.draftDays.set(counts.draft_days);
      this.openDays.set(counts.open_days);
      this.pendingProposals.set(counts.pending_proposals);
    });
  }

  start(): void {
    if (this.timer) return;
    this.refresh();
    this.timer = setInterval(() => {
      if (this.live.connected()) return;
      this.refresh();
    }, 60_000);
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  refresh(): void {
    const quiet = { error: () => undefined };
    this.api.captures('new').subscribe({ next: (c) => this.newCaptures.set(c.length), ...quiet });
    this.api.drafts().subscribe({ next: (d) => this.draftDays.set(d.length), ...quiet });
    this.api.proposals().subscribe({ next: (p) => this.pendingProposals.set(p.length), ...quiet });
    const today = iso(new Date());
    const from = iso(new Date(Date.now() - 60 * 86_400_000));
    this.api.days(from, today, 'open').subscribe({
      next: (days) => this.openDays.set(days.filter((d) => d.date < today).length),
      ...quiet,
    });
  }
}
