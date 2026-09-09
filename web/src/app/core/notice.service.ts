import { Injectable, signal } from '@angular/core';

export type NoticeKind = 'ok' | 'error';

export interface Notice {
  id: number;
  kind: NoticeKind;
  text: string;
}

/** How long a success stays before it gets out of the way. */
const OK_MS = 4000;

/**
 * Short messages that float above the page (R79).
 *
 * A message rendered inside the page is only seen if the reader happens to be looking at
 * that part of it. Saving the settings scrolls nothing, and the button sits at the bottom
 * of a long form, so a confirmation at the top was invisible: the save looked like it did
 * nothing. These float, regardless of the scroll position.
 *
 * A success disappears on its own; an error stays until it is dismissed, because it says
 * something the reader has to act on.
 */
@Injectable({ providedIn: 'root' })
export class NoticeService {
  readonly notices = signal<Notice[]>([]);
  private next = 1;

  ok(text: string): void {
    this.push('ok', text);
  }

  error(text: string): void {
    this.push('error', text);
  }

  dismiss(id: number): void {
    this.notices.update((list) => list.filter((n) => n.id !== id));
  }

  private push(kind: NoticeKind, text: string): void {
    const id = this.next++;
    // at most three at once; the oldest goes, so a burst cannot bury the page
    this.notices.update((list) => [...list.slice(-2), { id, kind, text }]);
    if (kind === 'ok') setTimeout(() => this.dismiss(id), OK_MS);
  }
}
