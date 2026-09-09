import { ChangeDetectionStrategy, Component, input, model } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { todayLocal } from '../../core/format.service';

type Json = Record<string, unknown>;

/** The macros a band can carry; protein and fiber also know a stretch value. */
const MACROS = [
  { key: 'kcal', label: 'kcal', stretch: false },
  { key: 'protein', label: 'Protein g', stretch: true },
  { key: 'carbs', label: 'Carbs g', stretch: false },
  { key: 'fat', label: 'Fat g', stretch: false },
  { key: 'fiber', label: 'Fiber g', stretch: true },
  { key: 'salt', label: 'Salt g', stretch: false },
] as const;

const LEVELS = ['min', 'opt_min', 'opt_max', 'target', 'max'] as const;

export interface BandModel {
  name: string;
  training_type: string;
  valid_from: string;
  valid_until: string;
  note: string;
  /** macro → level → value as typed. */
  values: Record<string, Record<string, string>>;
}

function str(v: unknown): string {
  return v === undefined || v === null ? '' : String(v);
}

function num(v: string): number | undefined {
  const t = v.trim();
  if (!t) return undefined;
  const n = Number(t.replace(',', '.'));
  return Number.isFinite(n) ? n : undefined;
}

/** Turn one `target_bands` entry from the settings document into the form model. */
export function bandFromJson(raw: Json): BandModel {
  const values: Record<string, Record<string, string>> = {};
  for (const m of MACROS) {
    const spec = (raw[m.key] ?? {}) as Json;
    const row: Record<string, string> = {};
    for (const level of LEVELS) row[level] = str(spec[level]);
    if (m.stretch) row['stretch'] = str(spec['stretch']);
    values[m.key] = row;
  }
  return {
    name: str(raw['name']),
    training_type: str(raw['training_type']),
    valid_from: str(raw['valid_from']),
    valid_until: str(raw['valid_until']),
    note: str(raw['note']),
    values,
  };
}

/** …and back, dropping empty fields so the document stays clean. */
export function bandToJson(b: BandModel): Json {
  const out: Json = { name: b.name.trim(), valid_from: b.valid_from };
  if (b.training_type) out['training_type'] = b.training_type;
  if (b.valid_until) out['valid_until'] = b.valid_until;
  if (b.note.trim()) out['note'] = b.note.trim();
  for (const m of MACROS) {
    const spec: Json = {};
    for (const level of LEVELS) {
      const v = num(b.values[m.key]?.[level] ?? '');
      if (v !== undefined) spec[level] = v;
    }
    if (m.stretch) {
      const v = num(b.values[m.key]?.['stretch'] ?? '');
      if (v !== undefined) spec['stretch'] = v;
    }
    if (Object.keys(spec).length) out[m.key] = spec;
  }
  return out;
}

export function emptyBand(): BandModel {
  const values: Record<string, Record<string, string>> = {};
  for (const m of MACROS) {
    const row: Record<string, string> = {};
    for (const level of LEVELS) row[level] = '';
    if (m.stretch) row['stretch'] = '';
    values[m.key] = row;
  }
  return { name: '', training_type: '', valid_from: todayLocal(), valid_until: '', note: '', values };
}

/**
 * One target band: which days it applies to, and per nutrient the five levels
 * (min, optimum from/to, target, max) plus a stretch value where it makes sense.
 */
@Component({
  selector: 'v-band-editor',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <div class="band">
      <div class="v-form-row head">
        <label class="v-field"><span>Profile</span><input name="bn{{ idx() }}" [(ngModel)]="band().name" placeholder="Rest day" required /></label>
        <label class="v-field"><span>Applies to</span>
          <select name="bt{{ idx() }}" [(ngModel)]="band().training_type">
            <option value="">every day</option><option value="rest">rest</option><option value="strength">strength</option><option value="martial_arts">martial arts</option>
          </select>
        </label>
        <label class="v-field"><span>Valid from</span><input name="bf{{ idx() }}" type="date" [(ngModel)]="band().valid_from" required /></label>
        <label class="v-field"><span>Valid until</span><input name="bu{{ idx() }}" type="date" [(ngModel)]="band().valid_until" /></label>
      </div>
      <div class="v-scroll-x">
        <table class="v-table levels">
          <thead>
            <tr><th>Nutrient</th><th class="num">min</th><th class="num">optimum from</th><th class="num">optimum to</th><th class="num">target</th><th class="num">max</th><th class="num">stretch</th></tr>
          </thead>
          <tbody>
            @for (m of MACROS; track m.key) {
              <tr>
                <td>{{ m.label }}</td>
                @for (level of LEVELS; track level) {
                  <td class="num"><input type="number" step="any" min="0" [name]="'b' + idx() + m.key + level" [(ngModel)]="band().values[m.key][level]" [attr.aria-label]="m.label + ' ' + level" /></td>
                }
                <td class="num">
                  @if (m.stretch) {
                    <input type="number" step="any" min="0" [name]="'b' + idx() + m.key + 'stretch'" [(ngModel)]="band().values[m.key]['stretch']" [attr.aria-label]="m.label + ' stretch'" />
                  } @else { <span class="v-muted">–</span> }
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>
      <label class="v-field"><span>Note</span><input name="bnote{{ idx() }}" [(ngModel)]="band().note" /></label>
    </div>
  `,
  styles: `
    .band { display: grid; gap: 0.6rem; padding: 0.6rem; border: 1px solid var(--v-line); border-radius: var(--v-radius); }
    .head { grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); }
    .levels input { width: 5rem; padding: 0.2rem 0.35rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); text-align: right; }
    .levels td, .levels th { padding: 0.3rem 0.4rem; }
  `,
})
export class BandEditor {
  readonly band = model.required<BandModel>();
  readonly idx = input(0);
  protected readonly MACROS = MACROS;
  protected readonly LEVELS = LEVELS;
}
