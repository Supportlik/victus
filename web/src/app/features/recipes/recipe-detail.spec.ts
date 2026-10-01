// T-WEB-401 / T-WEB-402: a recipe's ingredients and batches, and cooking a new batch.
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { Recipe } from '../../api';
import { formatMacro } from '../../shared/format';
import { RecipeDetail } from './recipe-detail';

const RECIPE: Recipe = {
  id: 7,
  name: 'Lentil soup',
  default_servings: 4,
  ingredients: [
    { id: 1, product_name: 'Red lentils', amount: 250, unit_code: 'g' } as never,
    { id: 2, product_name: null, free_text: 'a pinch of cumin', amount: 1, unit_code: 'pinch' } as never,
  ],
  batches: [
    { id: 20, cooked_at: '2026-01-02', total_weight_g: 1800, kcal: 1420, protein: 88.5, finished_at: '2026-01-05' } as never,
    { id: 21, cooked_at: null, total_weight_g: 900, kcal: 700, protein: 40 } as never,
  ],
};

describe('RecipeDetail', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RecipeDetail],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  async function render(recipe: Recipe | null, id = '7') {
    const fixture = TestBed.createComponent(RecipeDetail);
    fixture.componentRef.setInput('id', id);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    // while loading nothing but the empty page frame is shown
    expect(el.querySelector('h2')).toBeNull();
    const req = http.expectOne(`/api/v1/recipes/${id}`);
    if (recipe) req.flush(recipe);
    else req.flush({ title: 'Not Found', detail: 'No recipe 99.' }, { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();
    await fixture.whenStable();
    return { fixture, el };
  }

  it('T-WEB-401: shows name, default servings, ingredients and batches', async () => {
    const { el } = await render(RECIPE);
    expect(el.querySelector('h2')?.textContent).toBe('Lentil soup');
    expect(el.querySelector('.sub')?.textContent).toContain('4 servings by default');
    expect(el.querySelector('a[href="/recipes"]')).toBeTruthy();
    const ingredients = [...el.querySelectorAll('section:first-child tbody tr')].map((r) =>
      [...r.querySelectorAll('td')].map((c) => c.textContent!.trim()).join(' | '),
    );
    expect(ingredients).toEqual(['Red lentils | 250 g', 'a pinch of cumin | 1 pinch']);
    const batches = [...el.querySelectorAll('section:nth-child(2) tbody tr')];
    expect(batches.length).toBe(2);
    expect(batches[0].textContent).toContain('2026-01-02');
    expect(batches[0].textContent).toContain('1800 g');
    expect(batches[0].textContent).toContain(formatMacro(1420, 'kcal'));
    expect(batches[0].textContent).toContain(formatMacro(88.5, 'protein'));
    expect(batches[0].textContent).toContain('2026-01-05');
    expect(batches[1].textContent).toContain('unknown'), 'a batch without a cooking day says so';
  });

  it('T-WEB-401: a recipe with one serving and nothing recorded shows the empty rows', async () => {
    const { el } = await render({ id: 8, name: 'Porridge', default_servings: 1 }, '8');
    expect(el.querySelector('.sub')?.textContent).toContain('1 serving by default');
    expect(el.textContent).toContain('No ingredients recorded.');
    expect(el.textContent).toContain('Not cooked yet.');
    const { el: plain } = await render({ id: 9, name: 'Stock', ingredients: [], batches: [] }, '9');
    expect(plain.querySelector('.sub')).toBeNull(), 'no servings line without default servings';
  });

  it('T-WEB-401: shows the refusal when the recipe cannot be read', async () => {
    const { el } = await render(null, '99');
    expect(el.querySelector('.v-error')?.textContent).toContain('No recipe 99.');
    expect(el.querySelector('h2')).toBeNull();
  });

  it('T-WEB-402: cooking a batch posts it and reloads the recipe; the button waits for a weight', async () => {
    const { fixture, el } = await render(RECIPE);
    const button = el.querySelector('form.cook button[type=submit]') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    // submitting without a weight sends nothing
    fixture.componentInstance.cook();
    http.expectNone('/api/v1/recipes/7/batches');

    fixture.componentInstance.cookedAt = '2026-01-10';
    fixture.componentInstance.weight = 1500;
    fixture.componentInstance.servings = 5;
    fixture.componentInstance.cook();
    const post = http.expectOne('/api/v1/recipes/7/batches');
    expect(post.request.method).toBe('POST');
    expect(post.request.body).toEqual({ cooked_at: '2026-01-10', total_weight_g: 1500, servings: 5 });
    post.flush({ id: 22, cooked_at: '2026-01-10', total_weight_g: 1500 });
    const reload = http.expectOne('/api/v1/recipes/7');
    reload.flush({ ...RECIPE, batches: [...RECIPE.batches!, { id: 22, cooked_at: '2026-01-10', total_weight_g: 1500, kcal: 1200, protein: 70 } as never] });
    fixture.detectChanges();
    await fixture.whenStable();
    expect(el.querySelectorAll('section:nth-child(2) tbody tr').length).toBe(3);
  });

  it('T-WEB-402: servings left empty are not sent, and a refused batch shows the problem', async () => {
    const { fixture, el } = await render(RECIPE);
    fixture.componentInstance.weight = 800;
    fixture.componentInstance.cook();
    const post = http.expectOne('/api/v1/recipes/7/batches');
    expect(post.request.body.servings).toBeUndefined();
    post.flush(
      { title: 'Unprocessable', detail: 'The batch was refused', errors: [{ field: 'total_weight_g', message: 'too small' }] },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    fixture.detectChanges();
    await fixture.whenStable();
    expect(el.querySelector('.v-error')?.textContent).toContain('The batch was refused — total_weight_g: too small');
  });
});
