import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiClient, Recipe } from '../../api';
import { I18nService } from '../../core/i18n.service';
import { describeError } from '../../core/problem';

@Component({
  selector: 'v-recipes-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    <div class="v-page">
      <header class="v-page-head"><div><h2>{{ i18n.t('Recipes') }}</h2><p class="sub">{{ i18n.t('A recipe is a definition; a cooked batch freezes its nutrients.') }}</p></div></header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
      @if (recipes().length === 0) { <div class="v-empty">{{ i18n.t('No recipes yet.') }}</div> } @else {
        <ul class="list">
          @for (r of recipes(); track r.id) {
            <li><a [routerLink]="['/recipes', r.id]">{{ r.name }}</a> <span class="v-small v-muted">@if (r.default_servings) { {{ i18n.t('{n} servings', { n: r.default_servings }) }} · } {{ i18n.t('{n} batches', { n: r.batches?.length ?? 0 }) }}</span></li>
          }
        </ul>
      }
    </div>
  `,
  styles: `.list { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.4rem; } .list li { padding: 0.5rem 0; border-bottom: 1px solid var(--v-line); }`,
})
export class RecipesPage {
  private readonly api = inject(ApiClient);
  readonly i18n = inject(I18nService);
  readonly recipes = signal<Recipe[]>([]);
  readonly error = signal<string | null>(null);
  constructor() {
    this.api.recipes().subscribe({ next: (r) => this.recipes.set(r), error: (e: unknown) => this.error.set(describeError(e)) });
  }
}
