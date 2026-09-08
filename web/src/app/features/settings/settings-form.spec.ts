import { describe, expect, it } from 'vitest';
import { TenantSettingsForm } from './settings-form';

const DOC = {
  goal: { weight_kg: 80, date: '2027-01-31', stages: [{ name: 'first', date: '2026-12-01' }] },
  kcal_per_kg: 7716.17,
  moving_average_days: 7,
  trend_windows: [7, 14, 30],
  tdee_windows: [7, 14],
  tdee_reference_window: 14,
  calorie_corridor: { min: 1800, max: 2400, asymmetric: true },
  transcription: { language: 'en', vocabulary_prompt: 'skyr, quark' },
  target_bands: [{ name: 'rest', training_type: 'rest' }],
  report_defaults: { period: '14d', palette: { ok: '#00ff00' } },
};

describe('TenantSettingsForm', () => {
  it('round-trips the document and keeps keys it does not edit', () => {
    const m = TenantSettingsForm.fromData(DOC);
    expect(m.goalWeight).toBe('80');
    expect(m.trendWindows).toBe('7, 14, 30');
    expect(m.language).toBe('en');
    const out = TenantSettingsForm.mergeInto(DOC, { ...m, goalWeight: '78.5', trendWindows: '7,14,21', vocabulary: 'skyr, quark, rye bread' });
    expect(out['goal']).toMatchObject({ weight_kg: 78.5, date: '2027-01-31' });
    expect(out['trend_windows']).toEqual([7, 14, 21]);
    expect(out['target_bands']).toEqual(DOC.target_bands);
    expect((out['report_defaults'] as { palette: unknown }).palette).toEqual({ ok: '#00ff00' });
    expect((out['transcription'] as { vocabulary_prompt: string }).vocabulary_prompt).toBe('skyr, quark, rye bread');
  });

  it('drops empty optional groups instead of writing empty objects', () => {
    const m = TenantSettingsForm.empty();
    m.kcalPerKg = '7716.17';
    const out = TenantSettingsForm.mergeInto({ kcal_per_kg: 7716.17 }, m);
    expect(out['goal']).toBeUndefined();
    expect(out['body']).toBeUndefined();
    expect(out['calorie_corridor']).toEqual({ asymmetric: true });
  });
});
