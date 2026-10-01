// T-WEB-412 / T-WEB-413: a target band travels from the settings document into the form
// and back without inventing or losing values, and the editor binds every level.
import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { FormsModule } from '@angular/forms';
import { I18nService } from '../../core/i18n.service';
import { todayLocal } from '../../core/format.service';
import { BandEditor, BandModel, bandFromJson, bandToJson, emptyBand } from './band-editor';

describe('band-editor model', () => {
  it('T-WEB-412: reads a settings entry into strings, with empty strings for what is missing', () => {
    const band = bandFromJson({
      name: 'Rest day', training_type: 'rest', valid_from: '2026-01-01', note: 'illustrative',
      kcal: { min: 1800, opt_min: 1900, opt_max: 2100, target: 2000, max: 2300 },
      protein: { min: 120, stretch: 160 },
      fat: null,
    });
    expect(band).toMatchObject({ name: 'Rest day', training_type: 'rest', valid_from: '2026-01-01', valid_until: '', note: 'illustrative' });
    expect(band.values['kcal']).toEqual({ min: '1800', opt_min: '1900', opt_max: '2100', target: '2000', max: '2300' });
    expect(band.values['protein']).toEqual({ min: '120', opt_min: '', opt_max: '', target: '', max: '', stretch: '160' });
    expect(band.values['fiber']['stretch']).toBe(''), 'fiber also knows a stretch value';
    expect('stretch' in band.values['salt']).toBe(false), 'salt has no stretch';
    expect(band.values['fat']).toEqual({ min: '', opt_min: '', opt_max: '', target: '', max: '' });
    expect(bandFromJson({}).name).toBe('');
  });

  it('T-WEB-412: writes back numbers only, accepts a decimal comma and drops empty or invalid fields', () => {
    const band = bandFromJson({ name: '  Training  ', valid_from: '2026-02-01' });
    band.values['kcal']['min'] = ' 2000 ';
    band.values['salt']['max'] = '5,5';
    band.values['carbs']['target'] = 'abc';
    band.values['protein']['stretch'] = '180';
    band.values['fiber']['stretch'] = '';
    band.note = '   ';
    expect(bandToJson(band)).toEqual({
      name: 'Training',
      valid_from: '2026-02-01',
      kcal: { min: 2000 },
      salt: { max: 5.5 },
      protein: { stretch: 180 },
    });

    band.training_type = 'strength';
    band.valid_until = '2026-03-01';
    band.note = ' lifting ';
    expect(bandToJson(band)).toMatchObject({ training_type: 'strength', valid_until: '2026-03-01', note: 'lifting' });

    // a model missing a macro row entirely still serialises
    const partial: BandModel = { ...band, values: {} };
    expect(bandToJson(partial)).toEqual({ name: 'Training', valid_from: '2026-02-01', training_type: 'strength', valid_until: '2026-03-01', note: 'lifting' });
  });

  it('T-WEB-412: an empty band starts today with every level blank', () => {
    const band = emptyBand();
    expect(band.valid_from).toBe(todayLocal());
    expect(band.name).toBe('');
    expect(Object.keys(band.values)).toEqual(['kcal', 'protein', 'carbs', 'fat', 'fiber', 'salt']);
    expect(band.values['protein']['stretch']).toBe('');
    expect(bandToJson(band)).toEqual({ name: '', valid_from: band.valid_from });
  });
});

@Component({
  imports: [BandEditor, FormsModule],
  template: `<v-band-editor [(band)]="band" [idx]="2" />`,
})
class Host {
  band = signal<BandModel>(bandFromJson({ name: 'Rest day', valid_from: '2026-01-01', protein: { min: 120 } }));
}

describe('BandEditor', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [Host] }).compileComponents();
  });

  it('T-WEB-413: shows every macro with five levels, stretch only for protein and fiber, and binds typing to the model', async () => {
    const fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const rows = [...el.querySelectorAll('table.levels tbody tr')];
    expect(rows.map((r) => r.querySelector('td')?.textContent)).toEqual(['kcal', 'Protein g', 'Carbs g', 'Fat g', 'Fiber g', 'Salt g']);
    expect(rows[1].querySelectorAll('input').length).toBe(6);
    expect(rows[0].querySelectorAll('input').length).toBe(5);
    expect(rows[0].querySelector('.v-muted')?.textContent).toBe('–');
    const protein = rows[1].querySelector('input') as HTMLInputElement;
    expect(protein.getAttribute('aria-label')).toBe('Protein g min');
    expect(protein.value).toBe('120');
    expect(rows[1].querySelectorAll('input')[5].getAttribute('aria-label')).toBe('Protein g stretch');
    expect(rows[0].querySelectorAll('input')[1].getAttribute('aria-label')).toBe('kcal optimum from');

    const name = el.querySelector('.head input') as HTMLInputElement;
    expect(name.value).toBe('Rest day');
    name.value = 'Heavy day';
    name.dispatchEvent(new Event('input'));
    const kcalMax = rows[0].querySelectorAll('input')[4] as HTMLInputElement;
    kcalMax.value = '2600';
    kcalMax.dispatchEvent(new Event('input'));
    const select = el.querySelector('select') as HTMLSelectElement;
    select.value = 'martial_arts';
    select.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    const band = fixture.componentInstance.band();
    expect(band.name).toBe('Heavy day');
    expect(band.training_type).toBe('martial_arts');
    expect(bandToJson(band)['kcal']).toEqual({ max: 2600 });
  });

  it('T-WEB-413: level labels follow the interface language', () => {
    const fixture = TestBed.createComponent(BandEditor);
    fixture.componentRef.setInput('band', emptyBand());
    const i18n = TestBed.inject(I18nService);
    i18n.adopt('de');
    expect(fixture.componentInstance.levelLabel('opt_max')).toBe(i18n.t('optimum to'));
    expect(fixture.componentInstance.levelLabel('max')).toBe(i18n.t('max'));
  });
});
