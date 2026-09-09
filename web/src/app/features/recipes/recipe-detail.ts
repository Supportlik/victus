import { ChangeDetectionStrategy, Component, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiClient, Recipe } from '../../api';
import { I18nService } from '../../core/i18n.service';
import { describeError } from '../../core/problem';
import { isoDate, MacroPipe } from '../../shared/format';

@Component({
  selector: 'v-recipe-detail',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, FormsModule, MacroPipe],
  template: `
    <div class="v-page">
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
      @if (recipe(); as r) {
        <header class="v-page-head"><div><a routerLink="/recipes" class="v-small">← {{ i18n.t('Recipes') }}</a><h2>{{ r.name }}</h2>@if (r.default_servings) { <p class="sub">{{ i18n.t('{n} servings by default', { n: r.default_servings }) }}</p> }</div></header>
        <div class="grid">
          <section>
            <h3>{{ i18n.t('Ingredients') }}</h3>
            <table class="v-table"><tbody>
              @for (i of r.ingredients ?? []; track i.id) {
                <tr><td>{{ i.product_name ?? i.free_text }}</td><td class="num">{{ i.amount }} {{ i.unit_code }}</td></tr>
              } @empty { <tr><td class="v-muted">{{ i18n.t('No ingredients recorded.') }}</td></tr> }
            </tbody></table>
          </section>
          <section>
            <h3>{{ i18n.t('Batches') }}</h3>
            <table class="v-table">
              <thead><tr><th>{{ i18n.t('Cooked') }}</th><th class="num">{{ i18n.t('Weight') }}</th><th class="num">{{ i18n.t('kcal total') }}</th><th class="num">{{ i18n.t('Protein') }}</th><th>{{ i18n.t('Used up') }}</th></tr></thead>
              <tbody>
                @for (b of r.batches ?? []; track b.id) {
                  <tr><td>{{ b.cooked_at ?? i18n.t('unknown') }}</td><td class="num">{{ b.total_weight_g }} g</td><td class="num">{{ b.kcal | macro: 'kcal' }}</td><td class="num">{{ b.protein | macro: 'protein' }}</td><td>{{ b.finished_at ?? '' }}</td></tr>
                } @empty { <tr><td colspan="5" class="v-muted">{{ i18n.t('Not cooked yet.') }}</td></tr> }
              </tbody>
            </table>
            <form class="v-form-row cook" (ngSubmit)="cook()">
              <label class="v-field"><span>{{ i18n.t('Cooked on') }}</span><input name="d" type="date" [(ngModel)]="cookedAt" required /></label>
              <label class="v-field"><span>{{ i18n.t('Total weight g') }}</span><input name="w" type="number" min="1" [(ngModel)]="weight" required /></label>
              <label class="v-field"><span>{{ i18n.t('Servings') }}</span><input name="s" type="number" min="1" [(ngModel)]="servings" /></label>
              <button type="submit" class="v-btn primary" [disabled]="!weight">{{ i18n.t('Cook a batch') }}</button>
            </form>
          </section>
        </div>
      }
    </div>
  `,
  styles: `.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; } .cook { margin-top: 0.75rem; align-items: end; } @media (max-width: 52rem) { .grid { grid-template-columns: 1fr; } }`,
})
export class RecipeDetail {
  private readonly api = inject(ApiClient);
  readonly i18n = inject(I18nService);
  readonly id = input.required<string>();
  readonly recipe = signal<Recipe | null>(null);
  readonly error = signal<string | null>(null);
  cookedAt = isoDate(new Date());
  weight: number | null = null;
  servings: number | null = null;
  constructor() {
    effect(() => this.load());
  }
  load(): void {
    this.api.recipe(Number(this.id())).subscribe({ next: (r) => this.recipe.set(r), error: (e: unknown) => this.error.set(describeError(e)) });
  }
  cook(): void {
    if (!this.weight) return;
    this.api.cookBatch(Number(this.id()), { cooked_at: this.cookedAt, total_weight_g: this.weight, servings: this.servings ?? undefined }).subscribe({
      next: () => this.load(),
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }
}
