import { ChangeDetectionStrategy, Component, effect, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

type Json = Record<string, unknown>;

interface Stage {
  name: string;
  date: string;
  note: string;
}

/** Editable fields of the tenant settings document, flattened for the form. */
export interface SettingsFormModel {
  goalWeight: string;
  goalDate: string;
  goalReference: string;
  stages: Stage[];
  kcalPerKg: string;
  movingAverageDays: string;
  trendWindows: string;
  tdeeWindows: string;
  tdeeReferenceWindow: string;
  corridorMin: string;
  corridorMax: string;
  corridorAsymmetric: boolean;
  birthDate: string;
  heightCm: string;
  sex: string;
  language: string;
  vocabulary: string;
  reportPeriod: string;
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

function intList(v: string): number[] {
  return v
    .split(/[,\s]+/)
    .map((s) => Number(s))
    .filter((n) => Number.isInteger(n) && n >= 2);
}

function obj(v: unknown): Json {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Json) : {};
}

/**
 * Structured editor for the tenant settings. Fields not shown here (target bands,
 * report palette, anything new) are carried over unchanged from the current version.
 */
@Component({
  selector: 'v-tenant-settings-form',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <form class="grid" (ngSubmit)="submit()">
      <fieldset>
        <legend>Goal</legend>
        <div class="v-form-row">
          <label class="v-field"><span>Target weight (kg)</span><input name="gw" type="number" step="0.1" min="1" [(ngModel)]="m.goalWeight" /></label>
          <label class="v-field"><span>Target date</span><input name="gd" type="date" [(ngModel)]="m.goalDate" /></label>
          <label class="v-field"><span>Reference stage <span class="v-muted">(name)</span></span><input name="gr" [(ngModel)]="m.goalReference" /></label>
        </div>
        <div class="stages">
          <span class="v-small v-muted">Stages</span>
          @for (s of m.stages; track $index; let i = $index) {
            <div class="v-form-row stage">
              <input name="sn{{ i }}" [(ngModel)]="s.name" placeholder="Name" aria-label="Stage name" />
              <input name="sd{{ i }}" type="date" [(ngModel)]="s.date" aria-label="Stage date" />
              <input name="so{{ i }}" [(ngModel)]="s.note" placeholder="Note" aria-label="Stage note" />
              <button type="button" class="v-btn quiet small danger" (click)="m.stages.splice(i, 1)">remove</button>
            </div>
          }
          <button type="button" class="v-btn small" (click)="m.stages.push({ name: '', date: '', note: '' })">Add stage</button>
        </div>
      </fieldset>

      <fieldset>
        <legend>Calculation</legend>
        <div class="v-form-row">
          <label class="v-field"><span>kcal per kg body mass</span><input name="kk" type="number" step="0.01" [(ngModel)]="m.kcalPerKg" /></label>
          <label class="v-field"><span>Moving average (days)</span><input name="ma" type="number" min="1" [(ngModel)]="m.movingAverageDays" /></label>
          <label class="v-field"><span>TDEE reference window (days)</span><input name="rw" type="number" min="2" [(ngModel)]="m.tdeeReferenceWindow" /></label>
        </div>
        <div class="v-form-row">
          <label class="v-field"><span>Trend windows <span class="v-muted">(days, comma-separated)</span></span><input name="tw" [(ngModel)]="m.trendWindows" /></label>
          <label class="v-field"><span>TDEE windows</span><input name="dw" [(ngModel)]="m.tdeeWindows" /></label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Calorie corridor</legend>
        <div class="v-form-row">
          <label class="v-field"><span>Minimum kcal/day</span><input name="cmin" type="number" min="0" [(ngModel)]="m.corridorMin" /></label>
          <label class="v-field"><span>Maximum kcal/day</span><input name="cmax" type="number" min="0" [(ngModel)]="m.corridorMax" /></label>
          <label class="check"><input name="casym" type="checkbox" [(ngModel)]="m.corridorAsymmetric" /> Only exceeding the maximum counts as red</label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Body</legend>
        <div class="v-form-row">
          <label class="v-field"><span>Birth date</span><input name="bd" type="date" [(ngModel)]="m.birthDate" /></label>
          <label class="v-field"><span>Height (cm)</span><input name="hc" type="number" min="1" [(ngModel)]="m.heightCm" /></label>
          <label class="v-field"><span>Sex</span>
            <select name="sx" [(ngModel)]="m.sex"><option value="">–</option><option value="m">m</option><option value="f">f</option><option value="x">x</option></select>
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Transcription &amp; reports</legend>
        <div class="v-form-row">
          <label class="v-field"><span>Language</span><input name="lang" [(ngModel)]="m.language" placeholder="de" maxlength="5" /></label>
          <label class="v-field"><span>Default report period</span><input name="rp" [(ngModel)]="m.reportPeriod" placeholder="14d" pattern="^[0-9]+d$" /></label>
        </div>
        <label class="v-field"><span>Vocabulary for the transcription model <span class="v-muted">(product names, brands, exercises)</span></span>
          <textarea name="voc" rows="4" [(ngModel)]="m.vocabulary"></textarea></label>
      </fieldset>

      <div class="v-actions">
        <button type="submit" class="v-btn primary">Save as new version</button>
        <span class="v-small v-muted">Target bands and other advanced keys are kept as they are.</span>
      </div>
    </form>
  `,
  styles: `
    .grid { display: grid; gap: 1rem; }
    fieldset { border: 1px solid var(--v-line); border-radius: var(--v-radius-l); padding: 0.75rem 1rem 1rem; display: grid; gap: 0.75rem; min-width: 0; }
    legend { padding: 0 0.4rem; color: var(--v-ink-2); font-size: var(--v-fs-s); }
    .stages { display: grid; gap: 0.5rem; }
    .stage { grid-template-columns: 2fr 1fr 2fr auto; align-items: center; }
    .stage input { padding: 0.35rem 0.5rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); }
    .check { display: flex; gap: 0.5rem; align-items: center; font-size: var(--v-fs-s); color: var(--v-ink-2); align-self: end; padding-bottom: 0.5rem; }
    @media (max-width: 40rem) { .stage { grid-template-columns: 1fr 1fr; } }
  `,
})
export class TenantSettingsForm {
  /** Current settings document; the form is rebuilt whenever it changes. */
  readonly data = input.required<Json>();
  readonly save = output<Json>();
  readonly touched = signal(false);
  m: SettingsFormModel = TenantSettingsForm.empty();

  constructor() {
    effect(() => {
      this.m = TenantSettingsForm.fromData(this.data());
    });
  }

  static empty(): SettingsFormModel {
    return {
      goalWeight: '', goalDate: '', goalReference: '', stages: [], kcalPerKg: '', movingAverageDays: '',
      trendWindows: '', tdeeWindows: '', tdeeReferenceWindow: '', corridorMin: '', corridorMax: '',
      corridorAsymmetric: true, birthDate: '', heightCm: '', sex: '', language: '', vocabulary: '', reportPeriod: '',
    };
  }

  static fromData(d: Json): SettingsFormModel {
    const goal = obj(d['goal']);
    const corridor = obj(d['calorie_corridor']);
    const body = obj(d['body']);
    const tr = obj(d['transcription']);
    const rd = obj(d['report_defaults']);
    const stages = Array.isArray(goal['stages']) ? (goal['stages'] as Json[]) : [];
    return {
      goalWeight: str(goal['weight_kg']),
      goalDate: str(goal['date']),
      goalReference: str(goal['reference']),
      stages: stages.map((s) => ({ name: str(s['name']), date: str(s['date']), note: str(s['note']) })),
      kcalPerKg: str(d['kcal_per_kg']),
      movingAverageDays: str(d['moving_average_days']),
      trendWindows: Array.isArray(d['trend_windows']) ? (d['trend_windows'] as number[]).join(', ') : '',
      tdeeWindows: Array.isArray(d['tdee_windows']) ? (d['tdee_windows'] as number[]).join(', ') : '',
      tdeeReferenceWindow: str(d['tdee_reference_window']),
      corridorMin: str(corridor['min']),
      corridorMax: str(corridor['max']),
      corridorAsymmetric: corridor['asymmetric'] !== false,
      birthDate: str(body['birth_date']),
      heightCm: str(body['height_cm']),
      sex: str(body['sex']),
      language: str(tr['language']),
      vocabulary: str(tr['vocabulary_prompt']),
      reportPeriod: str(rd['period']),
    };
  }

  /** Merge the form back into a copy of the current document. */
  toData(): Json {
    return TenantSettingsForm.mergeInto(this.data(), this.m);
  }

  static mergeInto(current: Json, m: SettingsFormModel): Json {
    const d: Json = JSON.parse(JSON.stringify(current));
    const goal: Json = { ...obj(d['goal']) };
    setOrDelete(goal, 'weight_kg', num(m.goalWeight));
    setOrDelete(goal, 'date', m.goalDate || undefined);
    setOrDelete(goal, 'reference', m.goalReference.trim() || undefined);
    const stages = m.stages.filter((s) => s.name.trim() && s.date).map((s) => {
      const o: Json = { name: s.name.trim(), date: s.date };
      if (s.note.trim()) o['note'] = s.note.trim();
      return o;
    });
    setOrDelete(goal, 'stages', stages.length ? stages : undefined);
    setOrDelete(d, 'goal', Object.keys(goal).length ? goal : undefined);
    setOrDelete(d, 'kcal_per_kg', num(m.kcalPerKg));
    setOrDelete(d, 'moving_average_days', num(m.movingAverageDays));
    setOrDelete(d, 'trend_windows', intList(m.trendWindows).length ? intList(m.trendWindows) : undefined);
    setOrDelete(d, 'tdee_windows', intList(m.tdeeWindows).length ? intList(m.tdeeWindows) : undefined);
    setOrDelete(d, 'tdee_reference_window', num(m.tdeeReferenceWindow));
    const corridor: Json = { ...obj(d['calorie_corridor']) };
    setOrDelete(corridor, 'min', num(m.corridorMin));
    setOrDelete(corridor, 'max', num(m.corridorMax));
    corridor['asymmetric'] = m.corridorAsymmetric;
    d['calorie_corridor'] = corridor;
    const body: Json = { ...obj(d['body']) };
    setOrDelete(body, 'birth_date', m.birthDate || undefined);
    setOrDelete(body, 'height_cm', num(m.heightCm));
    setOrDelete(body, 'sex', m.sex || undefined);
    setOrDelete(d, 'body', Object.keys(body).length ? body : undefined);
    const tr: Json = { ...obj(d['transcription']) };
    setOrDelete(tr, 'language', m.language.trim() || undefined);
    setOrDelete(tr, 'vocabulary_prompt', m.vocabulary.trim() || undefined);
    setOrDelete(d, 'transcription', Object.keys(tr).length ? tr : undefined);
    const rd: Json = { ...obj(d['report_defaults']) };
    setOrDelete(rd, 'period', m.reportPeriod.trim() || undefined);
    setOrDelete(d, 'report_defaults', Object.keys(rd).length ? rd : undefined);
    return d;
  }

  submit(): void {
    this.save.emit(this.toData());
  }
}

function setOrDelete(target: Json, key: string, value: unknown): void {
  if (value === undefined) delete target[key];
  else target[key] = value;
}
