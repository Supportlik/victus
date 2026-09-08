import { ChangeDetectionStrategy, Component, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiClient, Category, Product, ProductInput } from '../../api';
import { describeError } from '../../core/problem';

/** Create or edit a product. Used stand-alone (/products/new) and inside the detail page. */
@Component({
  selector: 'v-product-form',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <form (ngSubmit)="save()" class="form">
      <h3>{{ product() ? 'Edit product' : 'New product' }}</h3>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
      <div class="v-form-row">
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
      <label class="v-field"><span>Note</span><textarea name="note" [(ngModel)]="model.note"></textarea></label>
      <div class="v-actions">
        <button type="submit" class="v-btn primary" [disabled]="busy() || !model.name || model.kcal == null">{{ product() ? 'Save changes' : 'Create product' }}</button>
        @if (product()) { <button type="button" class="v-btn quiet" (click)="cancelled.emit()">Cancel</button> }
      </div>
    </form>
  `,
  styles: `.form { display: grid; gap: 0.9rem; } .check { grid-template-columns: 1fr auto; align-items: center; }`,
})
export class ProductForm {
  private readonly api = inject(ApiClient);
  private readonly router = inject(Router);
  readonly product = input<Product | null>(null);
  readonly saved = output<Product>();
  readonly cancelled = output<void>();
  readonly categories = signal<Category[]>([]);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  model: ProductInput = { name: '', reference_amount: 100, reference_unit: 'g', verified: false, kcal: null, protein: null, carbs: null, fat: null, fiber: null, salt: null, category_id: null, brand: '', source: '', ean: '', note: '' };

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
