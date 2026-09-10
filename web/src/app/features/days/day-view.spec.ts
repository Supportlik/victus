// T-WEB-001: day view renders meals, totals, ⚠️ on estimates, draft tint and band gauges from a fixture.
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { DayLog, Product } from '../../api';
import { FormatService } from '../../core/format.service';
import { LineItemForm } from '../../shared/line-item-form';
import { DayView } from './day-view';

const band = { min: 105, opt_min: 150, opt_max: 185, target: 165, max: 200, stretch: 185 };
const UNITS = [
  { code: 'g', singular: 'g', plural: 'g', unit_type: 'mass' as const },
  { code: 'ml', singular: 'ml', plural: 'ml', unit_type: 'volume' as const },
  { code: 'bag', singular: 'bag', plural: 'bags', unit_type: 'count' as const },
  { code: 'slice', singular: 'slice', plural: 'slices', unit_type: 'count' as const },
];
const day: DayLog = {
  date: '2026-01-02',
  status: 'open',
  reliable: true,
  training_type: 'rest',
  macros: { kcal: 1383, protein: 154.9, carbs: 116.6, fat: 28.4, fiber: 12.3, salt: 7.25 },
  target_band: {
    id: 1, name: 'Rest day', training_type: 'rest', valid_from: '2026-01-01', valid_until: null,
    protein: band, carbs: { min: 120, opt_min: 155, opt_max: 200, target: 180, max: 230 },
    fat: { min: 45, opt_min: 55, opt_max: 70, target: 58, max: 75 }, fiber: { min: 25, opt_min: 32, opt_max: 38, target: 35, max: 50 },
    salt: { min: 4, opt_min: 6, opt_max: 8, target: 7, max: 15 },
  },
  zones: { protein: 'optimal', fiber: 'below_min', kcal: 'optimal' },
  findings: [],
  meals: [
    {
      id: 1, position: 1, name: 'Breakfast', time: '07:40', totals: { kcal: 252, protein: 44 },
      line_items: [
        { id: 11, meal_id: 1, position: 1, consumable_id: 5, consumable_name: 'Skyr natural', consumable_kind: 'product', amount: 400, unit_code: 'g', base_amount: 400, base_unit: 'g', estimated: false, amount_estimated: false, is_draft: false, kcal: 252, protein: 44 },
        { id: 12, meal_id: 1, position: 2, consumable_id: 9, consumable_name: 'Paprika chicken', consumable_kind: 'product', amount: 396, unit_code: 'g', base_amount: 396, base_unit: 'g', estimated: true, amount_estimated: true, is_draft: true, kcal: 420, protein: 67 },
      ],
    },
  ],
};

const skyrProduct: Product = {
  id: 5, name: 'Skyr natural', reference_amount: 100, reference_unit: 'g', verified: true, kcal: 63, protein: 11,
  portions: [{ id: 9, product_id: 5, unit_code: 'tub', label: 'tub', amount: 400, amount_unit: 'g', is_default: true }],
};
const chicken: Product = {
  id: 9, name: 'Paprika chicken', reference_amount: 100, reference_unit: 'g', verified: false, kcal: 106, protein: 17,
  portions: [],
};

describe('DayView', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DayView],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
  });

  async function render() {
    const fixture = TestBed.createComponent(DayView);
    fixture.componentRef.setInput('date', '2026-01-02');
    await fixture.whenStable();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/api/v1/units').flush(UNITS);
    http.expectOne('/api/v1/days/2026-01-02').flush(day);
    await fixture.whenStable();
    // The thread panel mounts once the day is loaded and then asks for its messages.
    http.expectOne('/api/v1/days/2026-01-02/messages').flush([]);
    await fixture.whenStable();
    return fixture;
  }

  it('renders meals, items and totals', async () => {
    const fixture = await render();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.meal h3')?.textContent).toContain('Breakfast');
    expect(el.querySelectorAll('.meal tbody tr:not(.total)').length).toBe(2);
    expect(el.querySelector('tr.total')?.textContent).toContain('252');
  });

  // T-WEB-049: one unit can have several portions - a piece of egg is S, M, L or XL - so
  // the unit alone would read "1 Stück" for anything between 43 and 65 g.
  it('names the portion beside the unit, unless the label only repeats the unit', async () => {
    const fixture = await render();
    const base = day.meals[0].line_items[0];
    fixture.componentInstance.day.update((d) =>
      d
        ? {
            ...d,
            meals: [
              {
                ...d.meals[0],
                line_items: [
                  ...d.meals[0].line_items,
                  { ...base, id: 13, position: 3, consumable_name: 'Egg', amount: 2, unit_code: 'piece', portion_id: 9, portion_label: 'L', base_amount: 112 },
                  { ...base, id: 14, position: 4, consumable_name: 'Roll', amount: 1, unit_code: 'piece', portion_id: 10, portion_label: 'piece', base_amount: 70 },
                ],
              },
            ],
          }
        : d,
    );
    fixture.detectChanges();
    const rows = [...(fixture.nativeElement as HTMLElement).querySelectorAll('tbody tr')];
    const cell = (name: string) =>
      rows.find((r) => r.textContent?.includes(name))?.querySelectorAll('td.num')[0]?.textContent?.trim();

    expect(cell('Egg')).toBe('2 piece (L)');
    // a label that is only the unit's own word would read "1 piece (piece)"
    expect(cell('Roll')).toBe('1 piece');
    // and an item logged in grams has no portion at all
    expect(cell('Skyr natural')).toBe('400 g');
  });

  it('marks estimated items with ⚠️ and drafts with a tag', async () => {
    const el = (await render()).nativeElement as HTMLElement;
    const rows = el.querySelectorAll('.meal tbody tr');
    expect(rows[0].textContent).not.toContain('⚠️');
    expect(rows[1].textContent).toContain('⚠️');
    expect(rows[1].classList.contains('draft')).toBe(true);
    expect(rows[1].querySelector('.v-tag.draft')?.textContent).toContain('draft');
  });

  it('shows one gauge per macro with the server zone colour', async () => {
    const el = (await render()).nativeElement as HTMLElement;
    const gauges = el.querySelectorAll('v-band-gauge');
    expect(gauges.length).toBe(6);
    const protein = gauges[1];
    expect(protein.querySelector('.value')?.classList.contains('ok')).toBe(true);
    const fiber = gauges[4];
    expect(fiber.querySelector('.value')?.classList.contains('bad')).toBe(true);
    expect(protein.querySelector('.strip')?.getAttribute('aria-label')).toContain('in the optimal range');
  });

  // T-WEB-048: there are three kinds of day. A fourth option labelled "none / rest" wrote
  // no type at all, and from the day the generic band was replaced by the three typed ones
  // such a day had no band: no gauges, and every macro of it unrated in the report.
  it('offers the three kinds of day and no empty option', async () => {
    const fixture = await render();
    const el = fixture.nativeElement as HTMLElement;
    const select = el.querySelector('select') as HTMLSelectElement;
    const values = [...select.options].map((o) => o.value);
    expect(values).toEqual(['rest', 'strength', 'martial_arts']);
    expect(values).not.toContain(''), 'an unclassified day is a rest day, not a fourth state';
    // a day the server returns without a type reads as the rest day it is judged as
    fixture.componentInstance.day.update((d) => (d ? { ...d, training_type: null } : d));
    fixture.detectChanges();
    expect((el.querySelector('select') as HTMLSelectElement).value).toBe('rest');
  });

  it('shows "Create this day" on 404 and posts reliable + training_type', async () => {
    const fixture = TestBed.createComponent(DayView);
    fixture.componentRef.setInput('date', '2026-01-03');
    await fixture.whenStable();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/api/v1/units').flush([]);
    http.expectOne('/api/v1/days/2026-01-03').flush({ title: 'Not found' }, { status: 404, statusText: 'Not Found' });
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.create-day')).not.toBeNull();
    expect(el.querySelector('.v-error')).toBeNull();

    fixture.componentInstance.newReliable = 'false';
    fixture.componentInstance.newTraining = 'strength';
    fixture.componentInstance.createDay();
    const req = http.expectOne('/api/v1/days/2026-01-03');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ reliable: false, training_type: 'strength' });
    req.flush({ ...day, date: '2026-01-03', reliable: false, training_type: 'strength', meals: [] });
    await fixture.whenStable();
    http.expectOne('/api/v1/days/2026-01-03/messages').flush([]);
    await fixture.whenStable();
    expect(el.querySelector('.create-day')).toBeNull();
    expect(el.querySelector('.gauges')).not.toBeNull();
  });

  it('offers "Close day" for an open day and posts to /close', async () => {
    const fixture = await render();
    const el = fixture.nativeElement as HTMLElement;
    const btn = [...el.querySelectorAll('button')].find((b) => b.textContent?.includes('Close day'));
    expect(btn).toBeDefined();
    btn!.click();
    const req = TestBed.inject(HttpTestingController).expectOne('/api/v1/days/2026-01-02/close');
    expect(req.request.method).toBe('POST');
    req.flush({ ...day, status: 'closed' });
    await fixture.whenStable();
    expect(el.querySelector('v-status-tag')?.textContent).toContain('Closed');
  });

  // T-WEB-041: a count unit without a portion used to be offered and then rejected on save
  // with "no portion for unit". It now asks for the size once and keeps it (R73).
  // T-WEB-046: a timestamp is stored in UTC and read on the tenant's clock. Cutting the
  // hour out of the ISO string told a Berlin reader 23:12 at ten past one in the morning.
  it('writes thread times on the clock of the tenant, not of the server', async () => {
    TestBed.inject(FormatService).adopt('de-DE', 'Europe/Berlin');
    const fixture = TestBed.createComponent(DayView);
    fixture.componentRef.setInput('date', '2026-01-02');
    await fixture.whenStable();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/api/v1/units').flush(UNITS);
    http.expectOne('/api/v1/days/2026-01-02').flush(day);
    await fixture.whenStable();
    http.expectOne('/api/v1/days/2026-01-02/messages').flush([
      {
        id: 3,
        role: 'agent',
        kind: 'note',
        content: 'Fibre is the weak one.',
        created_at: '2026-01-02T22:12:00Z',
      },
    ]);
    await fixture.whenStable();

    const time = (fixture.nativeElement as HTMLElement).querySelector('.thread time');
    expect(time?.textContent?.trim()).toBe('23:12'), 'CET is an hour ahead of UTC';
    expect(time?.getAttribute('datetime')).toBe('2026-01-02T22:12:00Z'), 'the stored value is UTC';
    http.match(() => true).forEach((r) => r.flush([]));
  });

  it('asks what an undeclared unit holds and saves it with the product', async () => {
    const fixture = await render();
    const http = TestBed.inject(HttpTestingController);
    const el = fixture.nativeElement as HTMLElement;

    // open the add form for the first meal and pick a product with no portions
    const add = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Add item') as HTMLButtonElement;
    add.click();
    fixture.detectChanges();
    fixture.componentInstance.pending.set({
      id: 42, name: 'Frosta High Protein', reference_amount: 100, reference_unit: 'g',
      verified: true, kcal: 96, protein: 8, portions: [],
    });
    fixture.componentInstance.amount = 1;
    fixture.componentInstance.unitCode.set('bag');
    fixture.detectChanges();

    // the unit is in the group that needs a size, and the form says so
    expect(fixture.componentInstance.needsSize()).toBe(true);
    const groups = Array.from(el.querySelectorAll('optgroup')).map((g) => g.getAttribute('label'));
    expect(groups).toContain('Weight and volume');
    expect(groups).toContain('Needs a size once');
    expect(el.textContent).toContain('One bag is');

    fixture.componentInstance.portionAmount = 500;
    fixture.detectChanges();
    // submitting through the DOM does not fire in jsdom; the handler is what matters here
    fixture.componentInstance.addItem(day.meals[0]);

    // the portion is declared first...
    const portion = http.expectOne('/api/v1/products/42/portions');
    expect(portion.request.body).toMatchObject({ unit_code: 'bag', amount: 500, amount_unit: 'g', is_default: true });
    // T-WEB-045: the label is the unit's own word, whatever language declared it. Storing
    // the translated one wrote "Tüte" into the database, and the English app then showed
    // "Tüte (500 g)" while one declared over MCP showed "tub" in the German app.
    expect(portion.request.body).toMatchObject({ label: 'bag' });
    portion.flush({ id: 7, product_id: 42, unit_code: 'bag', label: 'bag', amount: 500, amount_unit: 'g', is_default: true });

    // ...then the item is added against it, so nothing is rejected
    const item = http.expectOne(`/api/v1/meals/${day.meals[0].id}/line-items`);
    expect(item.request.body).toMatchObject({ consumable_id: 42, amount: 1, unit_code: 'bag', portion_id: 7 });
    item.flush({});
    http.match(() => true).forEach((r) => r.flush(r.request.method === 'GET' ? [] : {}));
  });

  /** Press "edit" in the row of one item; jsdom needs the change detection by hand. */
  function open(fixture: ComponentFixture<DayView>, item: string): void {
    const rows = [...(fixture.nativeElement as HTMLElement).querySelectorAll('tbody tr')];
    const row = rows.find((r) => r.textContent?.includes(item))!;
    const button = [...row.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'edit');
    (button as HTMLButtonElement).click();
    fixture.detectChanges();
  }

  function save(panel: Element): void {
    const button = [...panel.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Save');
    (button as HTMLButtonElement).click();
  }

  // T-WEB-055: the numbers say whether the day stayed in its bands. They do not say what
  // the day was, which is the question a person opens a day with.
  it('shows the verdict above the meals, and nothing when there is none', async () => {
    const fixture = await render();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.verdict')).toBeNull();

    fixture.componentInstance.day.update((d) => (d ? { ...d, verdict: 'A rest day that came in light. Two ready meals and a pudding.' } : d));
    fixture.detectChanges();
    const verdict = el.querySelector('.verdict');
    expect(verdict?.textContent).toContain('came in light');
    // above the meals, not inside the thread
    expect(verdict!.compareDocumentPosition(el.querySelector('.ledger')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(el.querySelector('.thread .verdict')).toBeNull();
  });

  // T-WEB-056: editing an item was `window.prompt` for one number, so its unit, its portion
  // and the two estimate marks could only be set while adding it. Withdrawing an estimate
  // was implemented on the server and unreachable from the page.
  it('takes both estimate marks back through the edit panel', async () => {
    const fixture = await render();
    const http = TestBed.inject(HttpTestingController);
    const el = fixture.nativeElement as HTMLElement;
    open(fixture, 'Paprika chicken');
    http.expectOne('/api/v1/products/9').flush(chicken);
    await fixture.whenStable();

    const panel = el.querySelector('v-line-item-form')!;
    const boxes = [...panel.querySelectorAll('input[type=checkbox]')] as HTMLInputElement[];
    // the panel opens on what the item says: this one is ⚠️ on both counts
    expect(boxes.map((b) => b.checked)).toEqual([true, true]);
    boxes.forEach((b) => b.click());
    fixture.detectChanges();
    save(panel);

    const req = http.expectOne('/api/v1/line-items/12');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ amount: 396, unit_code: 'g', portion_id: null, estimated: false, amount_estimated: false });
    req.flush({});
    http.match(() => true).forEach((r) => r.flush(r.request.method === 'GET' ? [] : {}));
  });

  it('offers the product’s own portions and logs the item against the chosen one', async () => {
    const fixture = await render();
    const http = TestBed.inject(HttpTestingController);
    const el = fixture.nativeElement as HTMLElement;
    open(fixture, 'Skyr natural');
    http.expectOne('/api/v1/products/5').flush(skyrProduct);
    await fixture.whenStable();

    const panel = el.querySelector('v-line-item-form')!;
    const groups = [...panel.querySelectorAll('optgroup')].map((g) => g.getAttribute('label'));
    expect(groups).toEqual(['Weight and volume', 'Portions of this product', 'Needs a size once']);
    const options = [...panel.querySelectorAll('option')].map((o) => o.textContent?.trim());
    expect(options).toContain('tub (400 g)');
    // a select in jsdom does not write back through ngModel; the model is what matters here
    const form = fixture.debugElement.query(By.directive(LineItemForm)).componentInstance as LineItemForm;
    form.unitCode.set('portion:9');
    ([...panel.querySelectorAll('input[type=checkbox]')] as HTMLInputElement[])[1].click();
    fixture.detectChanges();
    save(panel);

    const req = http.expectOne('/api/v1/line-items/11');
    expect(req.request.body).toEqual({ amount: 400, unit_code: 'tub', portion_id: 9, estimated: false, amount_estimated: true });
    req.flush({});
    http.match(() => true).forEach((r) => r.flush(r.request.method === 'GET' ? [] : {}));
  });
});
