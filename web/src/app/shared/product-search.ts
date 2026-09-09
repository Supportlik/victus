import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  afterNextRender,
  inject,
  input,
  output,
  viewChild,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { catchError, debounceTime, distinctUntilChanged, filter, map, of, switchMap } from 'rxjs';
import { ApiClient, Product } from '../api';
import { I18nService } from '../core/i18n.service';
import { MacroLine } from './macro-line';

/**
 * Debounced product search (300 ms, one request per pause). Emits the chosen product.
 * Used by the day view (add item), the review list (re-assign) and the product page.
 *
 * With `on` set, a product whose values changed over time is offered in the version that
 * applied on that day, so logging an older day does not pick up today's numbers (R70).
 */
@Component({
  selector: 'v-product-search',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, MacroLine],
  template: `
    <label class="v-field">
      <span>{{ i18n.t('Search products') }}</span>
      <input #field type="search" [formControl]="query" [placeholder]="i18n.t('Name or brand')" autocomplete="off" />
    </label>
    @if (results(); as answer) {
      @if (answer.list.length === 0 && term().length >= minLength) {
        @if (answer.term === term()) {
          <p class="v-muted v-small">{{ i18n.t('Nothing found for “{query}”.', { query: term() }) }}</p>
        } @else {
          <p class="v-muted v-small">{{ i18n.t('Searching …') }}</p>
        }
      } @else if (answer.list.length) {
        <ul class="results" role="listbox">
          @for (p of answer.list; track p.id) {
            <li>
              <button type="button" class="hit" (click)="pick(p)" role="option">
                <span class="name">{{ p.name }}@if (p.brand) {<span class="brand"> · {{ p.brand }}</span>}</span>
                <v-macro-line [m]="p" />
              </button>
            </li>
          }
        </ul>
      }
    }
  `,
  styles: `
    :host { display: block; }
    .results { list-style: none; margin: 0.4rem 0 0; padding: 0; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.25rem; max-height: 18rem; overflow: auto; }
    .hit { width: 100%; text-align: left; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.15rem; padding: 0.5rem 0.6rem; border: 1px solid var(--v-line); border-radius: var(--v-radius); background: var(--v-surface); cursor: pointer; }
    .hit:hover { border-color: var(--v-primary); }
    .name { font-weight: 500; }
    .brand { color: var(--v-ink-2); font-weight: 400; }
  `,
})
export class ProductSearch {
  private readonly api = inject(ApiClient);
  readonly i18n = inject(I18nService);
  private readonly field = viewChild<ElementRef<HTMLInputElement>>('field');

  constructor() {
    // The field exists only because someone chose to search, so it takes the caret. It is
    // inserted after the click, which is too late for the `autofocus` attribute.
    afterNextRender(() => this.field()?.nativeElement.focus());
  }

  readonly minLength = 2;
  /** Day the food was eaten; decides which version of a product is offered. */
  readonly on = input<string | null>(null);
  readonly picked = output<Product>();
  readonly query = new FormControl('', { nonNullable: true });
  /** What is typed right now, as a signal, so the view can compare it with the answer. */
  readonly term = toSignal(
    this.query.valueChanges.pipe(map((q) => q.trim())),
    { initialValue: '' },
  );

  /** The answer carries the term it belongs to: anything else is still on its way. */
  readonly results = toSignal(
    this.query.valueChanges.pipe(
      debounceTime(300),
      distinctUntilChanged(),
      filter((q) => q.trim().length >= this.minLength || q.trim().length === 0),
      switchMap((q) => {
        const term = q.trim();
        if (!term) return of({ term, list: [] as Product[] });
        return this.api.products(term, { limit: 15, on: this.on() }).pipe(
          map((list) => ({ term, list })),
          catchError(() => of({ term, list: [] as Product[] })),
        );
      }),
    ),
    { initialValue: { term: '', list: [] as Product[] } },
  );

  pick(p: Product): void {
    this.picked.emit(p);
    this.query.setValue('');
  }
}
