// T-WEB-400: the recipe list shows each recipe with servings and batch count, an empty
// state when there are none, and the API's refusal when the list cannot be read.
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { Recipe } from '../../api';
import { RecipesPage } from './recipes-page';

const RECIPES: Recipe[] = [
  { id: 1, name: 'Lentil soup', default_servings: 4, batches: [{ id: 10, cooked_at: '2026-01-02' } as never] },
  { id: 2, name: 'Overnight oats', default_servings: 1, batches: [] },
  { id: 3, name: 'Chili', batches: [{ id: 11, cooked_at: null } as never, { id: 12, cooked_at: null } as never] },
  { id: 4, name: 'Dal' },
];

describe('RecipesPage', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RecipesPage],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  async function render(answer: (r: ReturnType<HttpTestingController['expectOne']>) => void) {
    const fixture = TestBed.createComponent(RecipesPage);
    const req = http.expectOne('/api/v1/recipes');
    expect(req.request.method).toBe('GET');
    // before the answer the page already reads as empty, not broken
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('.v-empty')?.textContent).toContain('No recipes yet.');
    answer(req);
    fixture.detectChanges();
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  }

  it('T-WEB-400: lists recipes with singular/plural servings and batches, linked to their detail', async () => {
    const el = await render((r) => r.flush(RECIPES));
    const items = [...el.querySelectorAll('ul.list li')];
    expect(items.length).toBe(4);
    expect(items[0].querySelector('a')?.getAttribute('href')).toBe('/recipes/1');
    expect(items[0].textContent).toContain('4 servings');
    expect(items[0].textContent).toContain('1 batch');
    expect(items[1].textContent).toContain('1 serving ·');
    expect(items[1].textContent).toContain('0 batches');
    expect(items[2].textContent).not.toContain('serving');
    expect(items[2].textContent).toContain('2 batches');
    expect(items[3].textContent).toContain('0 batches'), 'a recipe without a batch list counts none';
    expect(el.querySelector('.v-empty')).toBeNull();
    expect(el.querySelector('.v-error')).toBeNull();
  });

  it('T-WEB-400: shows the empty state for an empty list', async () => {
    const el = await render((r) => r.flush([]));
    expect(el.querySelector('.v-empty')?.textContent).toContain('No recipes yet.');
    expect(el.querySelector('ul.list')).toBeNull();
  });

  it('T-WEB-400: shows the problem detail when the list cannot be read', async () => {
    const el = await render((r) =>
      r.flush({ title: 'Forbidden', detail: 'Missing scope recipes:read' }, { status: 403, statusText: 'Forbidden' }),
    );
    expect(el.querySelector('.v-error')?.textContent).toContain('Missing scope recipes:read');
    expect(el.querySelector('.v-empty')).toBeTruthy();
  });
});
