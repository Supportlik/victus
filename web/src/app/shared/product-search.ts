import { ChangeDetectionStrategy, Component, inject, input, output, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { catchError, debounceTime, distinctUntilChanged, filter, of, switchMap } from 'rxjs';
import { ApiClient, Product } from '../api';
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
      <span>{{ label }}</span>
      <input type="search" [formControl]="query" [placeholder]="placeholder" autocomplete="off" />
    </label>
    @if (results(); as list) {
      @if (list.length === 0 && query.value.length >= minLength) {
        <p class="v-muted v-small">Nothing found for “{{ query.value }}”.</p>
      } @else if (list.length) {
        <ul class="results" role="listbox">
          @for (p of list; track p.id) {
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
    .results { list-style: none; margin: 0.4rem 0 0; padding: 0; display: grid; gap: 0.25rem; max-height: 18rem; overflow: auto; }
    .hit { width: 100%; text-align: left; display: grid; gap: 0.15rem; padding: 0.5rem 0.6rem; border: 1px solid var(--v-line); border-radius: var(--v-radius); background: var(--v-surface); cursor: pointer; }
    .hit:hover { border-color: var(--v-primary); }
    .name { font-weight: 500; }
    .brand { color: var(--v-ink-2); font-weight: 400; }
  `,
})
export class ProductSearch {
  private readonly api = inject(ApiClient);
  readonly label = 'Search products';
  readonly placeholder = 'Name or brand';
  readonly minLength = 2;
  /** Day the food was eaten; decides which version of a product is offered. */
  readonly on = input<string | null>(null);
  readonly picked = output<Product>();
  readonly query = new FormControl('', { nonNullable: true });
  readonly busy = signal(false);

  readonly results = toSignal(
    this.query.valueChanges.pipe(
      debounceTime(300),
      distinctUntilChanged(),
      filter((q) => q.trim().length >= this.minLength || q.trim().length === 0),
      switchMap((q) => {
        if (!q.trim()) return of([] as Product[]);
        this.busy.set(true);
        return this.api
          .products(q.trim(), { limit: 15, on: this.on() })
          .pipe(catchError(() => of([] as Product[])));
      }),
    ),
    { initialValue: [] as Product[] },
  );

  pick(p: Product): void {
    this.picked.emit(p);
    this.query.setValue('');
  }
}
