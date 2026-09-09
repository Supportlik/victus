import { ChangeDetectionStrategy, Component, effect, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BandEditor, BandModel, bandFromJson, bandToJson, emptyBand } from './band-editor';
import { SUPPORTED_LOCALES } from '../../core/format.service';

type Json = Record<string, unknown>;

interface Stage {
  name: string;
  date: string;
  note: string;
}

interface Goal {
  name: string;
  weight: string;
  date: string;
  active: boolean;
  note: string;
  stages: Stage[];
}

/** Editable fields of the tenant settings document, flattened for the form. */
export interface SettingsFormModel {
  goals: Goal[];
  bands: BandModel[];
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
  captureRetentionDays: string;
  timezone: string;
  locale: string;
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
  imports: [FormsModule, BandEditor],
  template: `
    <form class="grid" (ngSubmit)="submit()">
      <fieldset>
        <legend>Goals</legend>
        <p class="v-small v-muted">Keep as many goals as you like; the active one drives every report.</p>
        @for (g of m.goals; track $index; let gi = $index) {
          <div class="goal" [class.active]="g.active">
            <div class="v-form-row head">
              <label class="v-field"><span>Name</span><input name="gn{{ gi }}" [(ngModel)]="g.name" placeholder="main goal" /></label>
              <label class="v-field"><span>Target weight (kg)</span><input name="gw{{ gi }}" type="number" step="0.1" min="1" [(ngModel)]="g.weight" /></label>
              <label class="v-field"><span>Target date</span><input name="gd{{ gi }}" type="date" [(ngModel)]="g.date" /></label>
              <label class="check"><input type="radio" name="activeGoal" [value]="gi" [checked]="g.active" (change)="setActive(gi)" /> active</label>
              <button type="button" class="v-btn quiet small danger" (click)="removeGoal(gi)">remove</button>
            </div>
            <label class="v-field"><span>Note</span><input name="gnote{{ gi }}" [(ngModel)]="g.note" /></label>
            <div class="stages">
              <span class="v-small v-muted">Stages of this goal</span>
              @for (s of g.stages; track $index; let i = $index) {
                <div class="v-form-row stage">
                  <input name="sn{{ gi }}_{{ i }}" [(ngModel)]="s.name" placeholder="Name, e.g. plan / stretch" aria-label="Stage name" />
                  <input name="sd{{ gi }}_{{ i }}" type="date" [(ngModel)]="s.date" aria-label="Stage date" />
                  <input name="so{{ gi }}_{{ i }}" [(ngModel)]="s.note" placeholder="Note" aria-label="Stage note" />
                  <button type="button" class="v-btn quiet small danger" (click)="g.stages.splice(i, 1)">remove</button>
                </div>
              }
              <button type="button" class="v-btn small" (click)="g.stages.push({ name: '', date: '', note: '' })">Add stage</button>
            </div>
          </div>
        }
        <button type="button" class="v-btn" (click)="addGoal()">Add goal</button>
      </fieldset>

      <fieldset>
        <legend>Target bands</legend>
        <p class="v-small v-muted">One profile per training type; a day picks the profile valid on its date. Salt has no other source than this table.</p>
        @for (b of m.bands; track $index; let i = $index) {
          <div class="band-wrap">
            <v-band-editor [(band)]="m.bands[i]" [idx]="i" />
            <button type="button" class="v-btn quiet small danger" (click)="m.bands.splice(i, 1)">remove profile</button>
          </div>
        }
        <button type="button" class="v-btn" (click)="addBand()">Add profile</button>
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

      <fieldset>
        <legend>Region</legend>
        <div class="v-form-row">
          <label class="v-field">
            <span>Time zone <span class="v-muted">(decides which day a reading counts on)</span></span>
            <input name="tz" [(ngModel)]="m.timezone" placeholder="Europe/Berlin" list="tzlist" />
            <datalist id="tzlist">
              @for (z of zones; track z) { <option [value]="z"></option> }
            </datalist>
          </label>
          <label class="v-field">
            <span>Number and date format</span>
            <select name="loc" [(ngModel)]="m.locale">
              <option value="">Default (1.234,5)</option>
              @for (l of locales; track l.tag) { <option [value]="l.tag">{{ l.label }}</option> }
            </select>
          </label>
        </div>
        <p class="v-small v-muted">Timestamps are always stored in UTC. The zone decides which calendar day they belong to, so a weigh-in just after midnight counts on the right day.</p>
      </fieldset>

      <fieldset>
        <legend>Housekeeping</legend>
        <div class="v-form-row">
          <label class="v-field">
            <span>Keep processed captures for <span class="v-muted">(days, 0 keeps them for ever)</span></span>
            <input name="cret" type="number" min="0" max="3650" step="1" [(ngModel)]="m.captureRetentionDays" placeholder="10" />
          </label>
        </div>
        <p class="v-small v-muted">A processed capture has already become line items. After this many days it is deleted together with its photos and recordings, so the store does not grow for ever.</p>
      </fieldset>

      <div class="v-actions">
        <button type="submit" class="v-btn primary">Save as new version</button>
        <span class="v-small v-muted">Keys not shown here are kept as they are.</span>
      </div>
    </form>
  `,
  styles: `
    .grid { display: grid; gap: 1rem; }
    fieldset { border: 1px solid var(--v-line); border-radius: var(--v-radius-l); padding: 0.75rem 1rem 1rem; display: grid; gap: 0.75rem; min-width: 0; }
    legend { padding: 0 0.4rem; color: var(--v-ink-2); font-size: var(--v-fs-s); }
    .goal { display: grid; gap: 0.6rem; padding: 0.6rem; border: 1px solid var(--v-line); border-radius: var(--v-radius); }
    .goal.active { border-color: var(--v-primary); background: var(--v-primary-soft); }
    .goal .head { grid-template-columns: minmax(8rem, 1fr) minmax(7rem, 1fr) minmax(8rem, 1fr) auto auto; align-items: end; }
    .band-wrap { display: grid; gap: 0.4rem; justify-items: start; }
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

  /** A short list of suggestions; any IANA name may be typed. */
  readonly zones = [
    'Europe/Berlin',
    'Europe/Vienna',
    'Europe/Zurich',
    'Europe/Warsaw',
    'Europe/London',
    'Europe/Lisbon',
    'Europe/Nicosia',
    'UTC',
  ];
  readonly locales = SUPPORTED_LOCALES.map((tag) => ({
    tag,
    label: tag === 'de-DE' ? 'German (1.234,5)' : tag === 'en-GB' ? 'British (1,234.5)' : 'American (1,234.5)',
  }));

  constructor() {
    effect(() => {
      this.m = TenantSettingsForm.fromData(this.data());
    });
  }

  addBand(): void {
    this.m.bands.push(emptyBand());
  }

  addGoal(): void {
    this.m.goals.push({ name: '', weight: '', date: '', active: this.m.goals.length === 0, note: '', stages: [] });
  }

  removeGoal(i: number): void {
    const wasActive = this.m.goals[i]?.active;
    this.m.goals.splice(i, 1);
    if (wasActive && this.m.goals.length) this.setActive(0);
  }

  setActive(i: number): void {
    this.m.goals.forEach((g, idx) => (g.active = idx === i));
  }

  static empty(): SettingsFormModel {
    return {
      goals: [], bands: [], kcalPerKg: '', movingAverageDays: '',
      trendWindows: '', tdeeWindows: '', tdeeReferenceWindow: '', corridorMin: '', corridorMax: '',
      corridorAsymmetric: true, birthDate: '', heightCm: '', sex: '', language: '', vocabulary: '', reportPeriod: '',
      captureRetentionDays: '', timezone: '', locale: '',
    };
  }

  static fromData(d: Json): SettingsFormModel {
    const goal = obj(d['goal']);
    const corridor = obj(d['calorie_corridor']);
    const body = obj(d['body']);
    const tr = obj(d['transcription']);
    const rd = obj(d['report_defaults']);
    const caps = obj(d['captures']);
    const reg = obj(d['regional']);
    const rawGoals =
      Array.isArray(d['goals']) && (d['goals'] as Json[]).length
        ? (d['goals'] as Json[])
        : goal['weight_kg'] !== undefined
          ? [goal]
          : [];
    const goals: Goal[] = rawGoals.map((g, i) => ({
      name: str(g['name']) || (i === 0 ? 'main goal' : 'goal ' + (i + 1)),
      weight: str(g['weight_kg']),
      date: str(g['date']),
      active: rawGoals.length === 1 ? true : g['active'] === true,
      note: str(g['note']),
      stages: (Array.isArray(g['stages']) ? (g['stages'] as Json[]) : []).map((s) => ({
        name: str(s['name']),
        date: str(s['date']),
        note: str(s['note']),
      })),
    }));
    if (goals.length && !goals.some((g) => g.active)) goals[0].active = true;
    const bands = (Array.isArray(d['target_bands']) ? (d['target_bands'] as Json[]) : []).map(bandFromJson);
    return {
      goals,
      bands,
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
      captureRetentionDays: str(caps['processed_retention_days']),
      timezone: str(reg['timezone']),
      locale: str(reg['locale']),
    };
  }

  /** Merge the form back into a copy of the current document. */
  toData(): Json {
    return TenantSettingsForm.mergeInto(this.data(), this.m);
  }

  static mergeInto(current: Json, m: SettingsFormModel): Json {
    const d: Json = JSON.parse(JSON.stringify(current));
    const goals: Json[] = m.goals
      .filter((g) => g.name.trim() && num(g.weight) !== undefined && g.date)
      .map((g) => {
        const o: Json = {
          name: g.name.trim(),
          weight_kg: num(g.weight),
          date: g.date,
          active: g.active,
        };
        if (g.note.trim()) o['note'] = g.note.trim();
        const stages = g.stages
          .filter((s) => s.name.trim() && s.date)
          .map((s) => {
            const st: Json = { name: s.name.trim(), date: s.date };
            if (s.note.trim()) st['note'] = s.note.trim();
            return st;
          });
        if (stages.length) o['stages'] = stages;
        return o;
      });
    if (goals.length) {
      if (!goals.some((g) => g['active'])) goals[0]['active'] = true;
      d['goals'] = goals;
      // keep the single 'goal' in sync with the active one, for readers of the old shape
      const activeGoal = goals.find((g) => g['active']) ?? goals[0];
      const legacy: Json = { weight_kg: activeGoal['weight_kg'], date: activeGoal['date'] };
      if (activeGoal['stages']) legacy['stages'] = activeGoal['stages'];
      d['goal'] = legacy;
    } else {
      delete d['goals'];
      delete d['goal'];
    }
    const bands = m.bands.filter((b) => b.name.trim() && b.valid_from).map(bandToJson);
    setOrDelete(d, 'target_bands', bands.length ? bands : undefined);
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
    const caps: Json = { ...obj(d['captures']) };
    // an empty field means "leave it to the default"; 0 is a real answer and must survive
    const retention = m.captureRetentionDays.trim() === '' ? undefined : num(m.captureRetentionDays);
    setOrDelete(caps, 'processed_retention_days', retention);
    setOrDelete(d, 'captures', Object.keys(caps).length ? caps : undefined);
    const reg: Json = { ...obj(d['regional']) };
    setOrDelete(reg, 'timezone', m.timezone.trim() || undefined);
    setOrDelete(reg, 'locale', m.locale.trim() || undefined);
    setOrDelete(d, 'regional', Object.keys(reg).length ? reg : undefined);
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
