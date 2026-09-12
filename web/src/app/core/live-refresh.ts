import { effect, inject, signal, untracked } from '@angular/core';
import { ChangeTarget, LiveService } from './live.service';

export interface LiveRefreshOptions {
  /**
   * Whether this batch of targets is about what the page shows.
   *
   * A batch is one transaction, so it is judged as a whole: a day view takes a batch that
   * names its own date and ignores one that names another.
   */
  accepts: (targets: ChangeTarget[]) => boolean;
  /** Fetch again. Called directly when nothing is at stake, on request when something is. */
  refresh: () => void;
  /**
   * Whether replacing what is on screen would take something away from the person.
   *
   * Be generous here: an open form, a typed line, a panel someone is in the middle of.
   * The cost of saying yes is one small notice; the cost of saying no is lost work.
   */
  busy: () => boolean;
}

/**
 * A page that keeps up with the stream without interrupting anyone (R80).
 *
 * The rule the owner chose: refresh silently wherever nothing is being edited, and where a
 * form is open or carries typed text, change nothing at all — say that newer data exists
 * and let the person ask for it. A page that replaces a half-filled form with fresh data is
 * worse than a stale page, because the staleness is visible and the lost typing is not.
 */
export class LiveRefresh {
  /** True when a change was held back because something was being edited. */
  readonly pending = signal(false);

  constructor(private readonly options: LiveRefreshOptions) {}

  /** A change that concerns this page arrived. */
  arrived(): void {
    if (this.options.busy()) this.pending.set(true);
    else this.options.refresh();
  }

  /** "Show it": the person asked for the newer data. */
  apply(): void {
    this.pending.set(false);
    this.options.refresh();
  }

  /** "Not now": the hint goes; the next change brings it back. */
  dismiss(): void {
    this.pending.set(false);
  }
}

/**
 * Wire a page to the change stream. Call it from an injection context (a field initializer
 * or the constructor of a component).
 *
 * Every callback runs untracked. They read the page's own signals — which item is open,
 * which date is shown — and a dependency on those would turn each of them into a reason to
 * refetch, which is exactly what this is meant to avoid.
 */
export function liveRefresh(options: LiveRefreshOptions): LiveRefresh {
  const live = inject(LiveService);
  const state = new LiveRefresh(options);

  effect(() => {
    const change = live.lastChange();
    untracked(() => {
      if (!change || !change.targets.length) return;
      if (!options.accepts(change.targets)) return;
      state.arrived();
    });
  });

  // A reconnect may have skipped changes: the stream does not replay what was missed after
  // a manual reopen. Taking a fresh copy closes that hole, but only while nothing is being
  // edited — there is nothing to tell the person here, since nothing says anything changed.
  effect(() => {
    const seen = live.reconnects();
    untracked(() => {
      if (!seen || options.busy()) return;
      options.refresh();
    });
  });

  return state;
}
