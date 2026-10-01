// T-WEB-417: the rendered settings form — typing into its number fields and saving emits the
// document with numbers (an <input type="number"> hands ngModel a number, not a string, and
// saving used to throw on it), goals are added, made active and removed, and a profile is
// added.
import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { TenantSettingsForm } from './settings-form';

type Json = Record<string, unknown>;

const DOC: Json = {
  goals: [
    { name: 'plan', weight_kg: 80, date: '2027-01-31', active: true },
    { name: 'stretch', weight_kg: 76, date: '2027-06-30' },
  ],
  kcal_per_kg: 7716.17,
  calorie_corridor: { min: 1800, max: 2400, asymmetric: true },
  captures: { processed_retention_days: 10 },
};

@Component({
  imports: [TenantSettingsForm],
  template: `<v-tenant-settings-form [data]="data()" (save)="saved = $event" />`,
})
class Host {
  data = signal<Json>(DOC);
  saved: Json | null = null;
}

async function render() {
  const fixture = TestBed.createComponent(Host);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  await fixture.whenStable();
  const el = fixture.nativeElement as HTMLElement;
  const form = fixture.debugElement.children[0].componentInstance as TenantSettingsForm;
  return { fixture, el, form };
}

function type(el: HTMLElement, selector: string, value: string): void {
  const input = el.querySelector(selector) as HTMLInputElement;
  expect(input, selector).toBeTruthy();
  input.value = value;
  input.dispatchEvent(new Event('input'));
}

describe('TenantSettingsForm (rendered)', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [Host] }).compileComponents();
  });

  it('T-WEB-417: numbers typed into number fields are saved as numbers', async () => {
    const { fixture, el } = await render();
    const numbers = [...el.querySelectorAll('input[type="number"]')] as HTMLInputElement[];
    expect(numbers.length).toBeGreaterThan(4);
    for (const input of numbers) {
      input.value = '12';
      input.dispatchEvent(new Event('input'));
    }
    fixture.detectChanges();
    (el.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit'));
    fixture.detectChanges();
    const saved = fixture.componentInstance.saved;
    expect(saved).not.toBeNull();
    expect(saved!['kcal_per_kg']).toBe(12);
    expect((saved!['calorie_corridor'] as Json)['min']).toBe(12);
    expect((saved!['captures'] as Json)['processed_retention_days']).toBe(12);

    // a number field emptied again means "no value", not 0
    for (const input of numbers) {
      input.value = '';
      input.dispatchEvent(new Event('input'));
    }
    (el.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit'));
    expect(fixture.componentInstance.saved!['kcal_per_kg']).toBeUndefined();
    expect(fixture.componentInstance.saved!['captures']).toBeUndefined();
  });

  it('T-WEB-417: goals are added, switched and removed; a profile is added', async () => {
    const { fixture, el, form } = await render();
    expect(form.m.goals.map((g) => g.active)).toEqual([true, false]);
    const radios = [...el.querySelectorAll('input[type="radio"][name="activeGoal"]')] as HTMLInputElement[];
    radios[1].dispatchEvent(new Event('change'));
    expect(form.m.goals.map((g) => g.active)).toEqual([false, true]);

    const buttons = [...el.querySelectorAll('button')] as HTMLButtonElement[];
    buttons.find((b) => b.textContent?.includes('Add goal'))!.click();
    expect(form.m.goals.length).toBe(3);
    expect(form.m.goals[2].active).toBe(false);

    form.removeGoal(1); // the active one: the first goal takes over
    expect(form.m.goals.map((g) => g.active)).toEqual([true, false]);
    form.removeGoal(1);
    form.removeGoal(0);
    expect(form.m.goals).toEqual([]);
    form.addGoal();
    expect(form.m.goals[0].active).toBe(true), 'the first goal of an empty list is active';

    buttons.find((b) => b.textContent?.includes('Add profile'))!.click();
    expect(form.m.bands.length).toBe(1);
    fixture.detectChanges();
    expect(form.localeLabel('de-DE')).toContain('1.234,5');
    expect(form.localeLabel('en-GB')).toContain('British');
    expect(form.localeLabel('en-US')).toContain('American');
  });
});
