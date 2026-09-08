import { describe, expect, it } from 'vitest';
import { TenantSettingsForm } from './settings-form';

const DOC = {
  goal: { weight_kg: 80, date: '2027-01-31', stages: [{ name: 'plan', date: '2026-12-01' }] },
  kcal_per_kg: 7716.17,
  moving_average_days: 7,
  trend_windows: [7, 14, 30],
  tdee_windows: [7, 14],
  tdee_reference_window: 14,
  calorie_corridor: { min: 1800, max: 2400, asymmetric: true },
  transcription: { language: 'en', vocabulary_prompt: 'skyr, quark' },
  target_bands: [
    {
      name: 'rest',
      training_type: 'rest',
      valid_from: '2026-08-18',
      kcal: { min: 1400, opt_min: 1400, opt_max: 2000, target: 1900, max: 2000 },
      protein: { min: 105, opt_min: 150, opt_max: 185, target: 165, max: 200, stretch: 185 },
      carbs: { min: 120, opt_min: 155, opt_max: 200, target: 180, max: 230 },
      fat: { min: 45, opt_min: 55, opt_max: 70, target: 58, max: 75 },
      fiber: { min: 25, opt_min: 32, opt_max: 38, target: 35, max: 50, stretch: 38 },
      salt: { min: 4, opt_min: 6, opt_max: 8, target: 8, max: 15 },
    },
  ],
  report_defaults: { period: '14d', palette: { ok: '#00ff00' } },
};

const MULTI = {
  ...DOC,
  goals: [
    { name: 'plan', weight_kg: 80, date: '2027-01-31', stages: [{ name: 'plan', date: '2026-12-01' }] },
    { name: 'stretch', weight_kg: 76, date: '2027-06-30', active: true },
  ],
};

describe('TenantSettingsForm', () => {
  it('reads a single legacy goal as one active goal', () => {
    const m = TenantSettingsForm.fromData(DOC);
    expect(m.goals).toHaveLength(1);
    expect(m.goals[0]).toMatchObject({ weight: '80', date: '2027-01-31', active: true });
    expect(m.goals[0].stages[0].name).toBe('plan');
    expect(m.trendWindows).toBe('7, 14, 30');
    expect(m.language).toBe('en');
  });

  it('keeps several goals and marks exactly one active', () => {
    const m = TenantSettingsForm.fromData(MULTI);
    expect(m.goals.map((g) => g.name)).toEqual(['plan', 'stretch']);
    expect(m.goals.filter((g) => g.active).map((g) => g.name)).toEqual(['stretch']);
  });

  it('writes goals, mirrors the active one into goal, and keeps untouched keys', () => {
    const m = TenantSettingsForm.fromData(MULTI);
    const out = TenantSettingsForm.mergeInto(MULTI, {
      ...m,
      trendWindows: '7,14,21',
      vocabulary: 'skyr, quark, rye bread',
    });
    expect((out['goals'] as { name: string }[]).map((g) => g.name)).toEqual(['plan', 'stretch']);
    expect(out['goal']).toMatchObject({ weight_kg: 76, date: '2027-06-30' });
    expect(out['trend_windows']).toEqual([7, 14, 21]);
    // the form owns the bands now: they round-trip through the editor unchanged
    expect(out['target_bands']).toEqual(DOC.target_bands);
    expect((out['report_defaults'] as { palette: unknown }).palette).toEqual({ ok: '#00ff00' });
    expect((out['transcription'] as { vocabulary_prompt: string }).vocabulary_prompt).toBe('skyr, quark, rye bread');
  });

  it('drops empty optional groups instead of writing empty objects', () => {
    const m = TenantSettingsForm.empty();
    m.kcalPerKg = '7716.17';
    const out = TenantSettingsForm.mergeInto({ kcal_per_kg: 7716.17 }, m);
    expect(out['goal']).toBeUndefined();
    expect(out['goals']).toBeUndefined();
    expect(out['body']).toBeUndefined();
    expect(out['calorie_corridor']).toEqual({ asymmetric: true });
  });
});
