import { ChangeDetectionStrategy, Component, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiClient, Category, Product, ProductInput } from '../../api';
import { describeError } from '../../core/problem';
import { FoodIcon } from '../../shared/food-icon';

/** A short, food-shaped set; anything else can be typed into the field. */
const ICON_CHOICES = ['🍽', '🥩', '🍗', '🐟', '🧀', '🥛', '🥚', '🥦', '🍓', '🥖', '🍚', '🍝', '🍲', '🥫', '🧈', '🥜', '🍫', '🍟', '🍨', '☕', '💧', '🥤', '🍺', '💊'] as const;

/** Create or edit a product. Used stand-alone (/products/new) and inside the detail page. */
@Component({
  selector: 'v-product-form',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, FoodIcon],
  template: `
    <form (ngSubmit)="save()" class="form">
      <h3>{{ product() ? 'Edit product' : 'New product' }}</h3>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
      <div class="v-form-row identity">
        <label class="v-field icon"><span>Icon</span>
          <span class="picker">
            <input name="icon" [(ngModel)]="model.icon" maxlength="4" placeholder="auto" aria-label="Icon" />
            <span class="preview"><v-food-icon [name]="model.name" [category]="categoryName()" kind="product" [icon]="model.icon" /></span>
          </span>
        </label>
        <label class="v-field"><span>Name</span><input name="name" [(ngModel)]="model.name" required /></label>
        <label class="v-field"><span>Brand</span><input name="brand" [(ngModel)]="model.brand" /></label>
        <label class="v-field"><span>Category</span>
          <select name="category" [(ngModel)]="model.category_id">
            <option [ngValue]="null">none</option>
            @for (c of categories(); track c.id) { <option [ngValue]="c.id">{{ c.name }}</option> }
          </select>
        </label>
        <label class="v-field"><span>Reference</span>
          <select name="ref" [(ngModel)]="model.reference_unit"><option value="g">per 100 g</option><option value="ml">per 100 ml</option></select>
        </label>
      </div>
      <div class="v-form-row">
        <label class="v-field"><span>kcal</span><input name="kcal" type="number" step="any" min="0" [(ngModel)]="model.kcal" required /></label>
        <label class="v-field"><span>Protein g</span><input name="protein" type="number" step="any" min="0" [(ngModel)]="model.protein" /></label>
        <label class="v-field"><span>Carbs g</span><input name="carbs" type="number" step="any" min="0" [(ngModel)]="model.carbs" /></label>
        <label class="v-field"><span>Fat g</span><input name="fat" type="number" step="any" min="0" [(ngModel)]="model.fat" /></label>
        <label class="v-field"><span>Fiber g</span><input name="fiber" type="number" step="any" min="0" [(ngModel)]="model.fiber" /></label>
        <label class="v-field"><span>Salt g</span><input name="salt" type="number" step="any" min="0" [(ngModel)]="model.salt" /></label>
      </div>
      <div class="v-form-row">
        <label class="v-field"><span>Source</span><input name="source" [(ngModel)]="model.source" placeholder="label, manufacturer site, database" /></label>
        <label class="v-field"><span>EAN</span><input name="ean" [(ngModel)]="model.ean" inputmode="numeric" /></label>
        <label class="v-field check"><span>Values from the label</span><input name="verified" type="checkbox" [(ngModel)]="model.verified" /></label>
      </div>
      <div class="suggest">
        <span class="v-small v-muted">Pick an icon</span>
        @for (g of ICON_CHOICES; track g) {
          <button type="button" class="glyph" [class.active]="model.icon === g" (click)="model.icon = model.icon === g ? null : g" [attr.aria-label]="'icon ' + g">{{ g }}</button>
        }
        <button type="button" class="glyph auto" [class.active]="!model.icon" (click)="model.icon = null">auto</button>
      </div>
      <label class="v-field"><span>Note</span><textarea name="note" [(ngModel)]="model.note"></textarea></label>
      <div class="v-actions">
        <button type="submit" class="v-btn primary" [disabled]="busy() || !model.name || model.kcal == null">{{ product() ? 'Save changes' : 'Create product' }}</button>
        @if (product()) { <button type="button" class="v-btn quiet" (click)="cancelled.emit()">Cancel</button> }
      </div>
    </form>
  `,
  styles: `
    .form { display: grid; gap: 1rem; }
    .form h3 { font-size: var(--v-fs-l); }
    fieldset { border: 1px solid var(--v-line); border-radius: var(--v-radius-l); padding: 0.75rem 1rem 1rem; display: grid; gap: 0.75rem; min-width: 0; }
    legend { padding: 0 0.4rem; color: var(--v-ink-2); font-size: var(--v-fs-s); }
    .identity { grid-template-columns: 5.5rem minmax(10rem, 2fr) minmax(8rem, 1fr) minmax(8rem, 1fr) minmax(7rem, 1fr); }
    .icon .picker { display: flex; gap: 0.35rem; align-items: center; }
    .icon input { width: 3rem; text-align: center; }
    .preview { font-size: 1.2rem; }
    .check { grid-template-columns: 1fr auto; align-items: center; }
    .suggest { display: flex; gap: 0.3rem; flex-wrap: wrap; align-items: center; }
    .glyph { border: 1px solid var(--v-line-strong); background: var(--v-surface); border-radius: var(--v-radius); width: 2rem; height: 2rem; cursor: pointer; font-size: 1rem; line-height: 1; }
    .glyph.auto { width: auto; padding: 0 0.5rem; font-size: var(--v-fs-xs); }
    .glyph.active { border-color: var(--v-primary); box-shadow: 0 0 0 1px var(--v-primary) inset; }
    @media (max-width: 52rem) { .identity { grid-template-columns: 4.5rem 1fr; } }
  `,
})
export class ProductForm {
  private readonly api = inject(ApiClient);
  private readonly router = inject(Router);
  readonly product = input<Product | null>(null);
  readonly saved = output<Product>();
  readonly cancelled = output<void>();
  readonly categories = signal<Category[]>([]);
  protected readonly ICON_CHOICES = ICON_CHOICES;

  /** Name of the selected category, so the icon preview matches what will be saved. */
  categoryName(): string | null {
    return this.categories().find((c) => c.id === this.model.category_id)?.name ?? null;
  }
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  model: ProductInput = { name: '', icon: null, reference_amount: 100, reference_unit: 'g', verified: false, kcal: null, protein: null, carbs: null, fat: null, fiber: null, salt: null, category_id: null, brand: '', source: '', ean: '', note: '' };

  constructor() {
    this.api.categories().subscribe({ next: (c) => this.categories.set(c), error: () => this.categories.set([]) });
  }

  ngOnInit(): void {
    const p = this.product();
    if (p) {
      const { id: _id, portions: _portions, ...rest } = p;
      this.model = { ...this.model, ...rest };
    }
  }

  save(): void {
    this.busy.set(true);
    this.error.set(null);
    const body = { ...this.model, brand: this.model.brand || null, ean: this.model.ean || null, note: this.model.note || null, source: this.model.source || null };
    const p = this.product();
    const req = p ? this.api.updateProduct(p.id, body) : this.api.createProduct(body);
    req.subscribe({
      next: (res) => {
        this.busy.set(false);
        this.saved.emit(res);
        if (!p) void this.router.navigate(['/products', res.id]);
      },
      error: (e: unknown) => {
        this.error.set(describeError(e));
        this.busy.set(false);
      },
    });
  }
}
