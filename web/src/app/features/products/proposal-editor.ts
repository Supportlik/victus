import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiClient, ProductProposal, Unit } from '../../api';
import { I18nService } from '../../core/i18n.service';
import { describeError } from '../../core/problem';
import { formatAmount } from '../../shared/format';

/** The numbers of a product, typed as numbers. */
const NUMERIC = new Set([
  'reference_amount',
  'kcal',
  'protein',
  'carbs',
  'fat',
  'fiber',
  'salt',
  'sugar',
  'saturated_fat',
  'density_g_per_ml',
]);

/** What a `new` proposal always offers, so a value the agent left out can be typed in. */
const NEW_FIELDS = ['name', 'brand', 'reference_amount', 'reference_unit', 'kcal', 'protein', 'carbs', 'fat', 'fiber', 'salt'];

/** One entry of `changes.portions`, with the parts a person corrects made editable. */
interface PortionRow {
  /** The entry as it was proposed; whatever is not edited here travels on unchanged. */
  entry: Record<string, unknown>;
  op: string;
  label: string;
  unit_code: string;
  amount: number | null;
}

/** The body of an approval: the corrected values, and the fields to apply. */
export interface ProposalDecision {
  changes?: Record<string, unknown>;
  fields?: string[];
}

/**
 * A pending proposal with every value the agent suggested as an input (R84).
 *
 * A proposal that is nearly right used to be rejected and typed again. Here the values —
 * name, brand, the nutrients, the reference amount and unit, portions and, for a version,
 * the day it starts on — are inputs: **Save** amends the proposal without deciding it
 * (`PATCH /proposals/{id}`), **Approve** sends the corrections as `changes` with the
 * decision. With `selectable`, each field also carries a tick for deciding field by field;
 * a cleared input counts as not applied.
 */
@Component({
  selector: 'v-proposal-editor',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <div class="editor" [attr.data-proposal]="proposal().id">
      @if (proposal().kind === 'version') {
        <label class="v-field valid-from"><span>{{ i18n.t('Valid from') }}</span>
          <input type="date" [(ngModel)]="values['valid_from']" [ngModelOptions]="{ standalone: true }" [attr.aria-label]="i18n.t('Valid from')" />
        </label>
      }
      <div class="v-scroll-x">
        <table class="v-table diff">
          <thead>
            <tr>
              @if (selectable()) { <th>{{ i18n.t('Apply') }}</th> }
              <th>{{ i18n.t('Field') }}</th>
              @if (proposal().kind !== 'new') { <th class="num">{{ i18n.t('Now') }}</th> }
              <th>{{ i18n.t('Proposed') }}</th>
            </tr>
          </thead>
          <tbody>
            @for (k of fields(); track k) {
              <tr [class.changed]="isEdited(k)">
                @if (selectable()) {
                  <td><input type="checkbox" [checked]="isSelected(k)" (change)="toggle(k)" [attr.aria-label]="i18n.t('apply {field}', { field: k })" /></td>
                }
                <td>{{ i18n.t(k) }}</td>
                @if (proposal().kind !== 'new') { <td class="num v-muted">{{ text(proposal().current[k]) }}</td> }
                <td>
                  @if (k === 'reference_unit') {
                    <select [(ngModel)]="values[k]" [ngModelOptions]="{ standalone: true }" [attr.aria-label]="i18n.t(k)">
                      <option value="g">g</option>
                      <option value="ml">ml</option>
                    </select>
                  } @else if (kindOf(k) === 'boolean') {
                    <input type="checkbox" [(ngModel)]="values[k]" [ngModelOptions]="{ standalone: true }" [attr.aria-label]="i18n.t(k)" />
                  } @else if (kindOf(k) === 'number') {
                    <input type="number" step="any" min="0" [(ngModel)]="values[k]" [ngModelOptions]="{ standalone: true }" [attr.aria-label]="i18n.t(k)" />
                  } @else {
                    <input [(ngModel)]="values[k]" [ngModelOptions]="{ standalone: true }" [attr.aria-label]="i18n.t(k)" />
                  }
                  @if (agentValue(k); as was) { <span class="v-small v-muted was">{{ i18n.t('agent: {value}', { value: was }) }}</span> }
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>
      @if (proposal().kind !== 'version' && (portions.length || proposal().kind === 'new')) {
        <div class="portions">
          <span class="v-small v-muted">{{ i18n.t('Portions') }}</span>
          @for (row of portions; track $index) {
            <div class="portion" [attr.data-portion]="$index">
              @if (row.op !== 'add') { <span class="op v-small">{{ opLabel(row.op) }}</span> }
              @if (row.op === 'delete') {
                <span class="v-small">{{ row.label || row.unit_code }}</span>
              } @else {
                <input class="label" [(ngModel)]="row.label" [ngModelOptions]="{ standalone: true }" [attr.aria-label]="i18n.t('Label')" />
                @if (countUnits().length) {
                  <select [(ngModel)]="row.unit_code" [ngModelOptions]="{ standalone: true }" [attr.aria-label]="i18n.t('Unit')">
                    @for (u of countUnits(); track u.code) { <option [value]="u.code">{{ i18n.t(u.singular) }}</option> }
                  </select>
                } @else {
                  <input class="unit" [(ngModel)]="row.unit_code" [ngModelOptions]="{ standalone: true }" [attr.aria-label]="i18n.t('Unit')" />
                }
                <input class="amount" type="number" step="any" min="0" [(ngModel)]="row.amount" [ngModelOptions]="{ standalone: true }" [attr.aria-label]="i18n.t('Weight')" />
                <span class="v-small v-muted">{{ portionUnit(row) }}</span>
              }
              <button type="button" class="v-btn quiet small danger" (click)="removePortion($index)">{{ i18n.t('remove') }}</button>
            </div>
          }
          @if (proposal().kind === 'new') {
            <button type="button" class="v-btn small quiet add" (click)="addPortion()">{{ i18n.t('Add portion') }}</button>
          }
        </div>
      }
      @if (kept()) { <p class="v-small v-muted">{{ i18n.t('This proposal changed meanwhile. What you typed is kept until you save or decide.') }}</p> }
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }
      <div class="v-actions">
        <button type="button" class="v-btn primary" (click)="approve()" [disabled]="busy() || disabled() || !applicable()">{{ approveLabel() }}</button>
        <button type="button" class="v-btn" (click)="save()" [disabled]="busy() || !dirty()">{{ i18n.t('Save corrections') }}</button>
        <button type="button" class="v-btn" (click)="reject()" [disabled]="busy()">{{ i18n.t('Reject') }}</button>
      </div>
    </div>
  `,
  styles: `
    .editor { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.5rem; }
    .valid-from { max-width: 12rem; }
    .diff { max-width: 36rem; }
    .diff input:not([type='checkbox']), .diff select { width: 100%; min-width: 6rem; padding: 0.25rem 0.4rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); }
    .diff tr.changed td { background: var(--v-primary-soft); }
    .was { display: block; }
    .portions { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.35rem; }
    .portion { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }
    .portion input, .portion select { padding: 0.25rem 0.4rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); }
    .portion .label { flex: 1 1 8rem; min-width: 0; }
    .portion .amount, .portion .unit { width: 5.5rem; }
    .portion .op { font-variant: all-small-caps; color: var(--v-ink-2); }
    .add { justify-self: start; }
    .v-actions { justify-content: flex-start; }
  `,
})
export class ProposalEditor {
  private readonly api = inject(ApiClient);
  readonly i18n = inject(I18nService);
  readonly proposal = input.required<ProductProposal>();
  /** Count units for the portion rows; without them the unit is typed. */
  readonly units = input<Unit[]>([]);
  /** A tick per field, for deciding field by field. */
  readonly selectable = input(false);
  /** Approving is held back from outside, e.g. while a portion line would be refused. */
  readonly disabled = input(false);
  readonly approveText = input<string | null>(null);
  /** The proposal as the server answered: amended, approved or rejected. */
  readonly amended = output<ProductProposal>();
  readonly decided = output<ProductProposal>();
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly kept = signal(false);
  readonly unselected = signal<Set<string>>(new Set());
  /** The values as typed; `portions` lives in its own rows. */
  values: Record<string, unknown> = {};
  portions: PortionRow[] = [];
  private loadedId: string | null = null;

  readonly countUnits = computed(() => this.units().filter((u) => u.unit_type === 'count'));

  /** The fields shown, in the order a label prints them. */
  readonly fields = computed(() => {
    const pr = this.proposal();
    const own = Object.keys(pr.changes).filter((k) => k !== 'portions' && k !== 'valid_from');
    if (pr.kind !== 'new') return own;
    return [...NEW_FIELDS, ...own.filter((k) => !NEW_FIELDS.includes(k))];
  });

  constructor() {
    effect(() => {
      const pr = this.proposal();
      untracked(() => this.take(pr));
    });
  }

  /** The proposal as the server has it; a refresh while something is typed keeps the typing. */
  private take(pr: ProductProposal): void {
    if (this.loadedId === pr.id && this.dirty()) {
      this.kept.set(true);
      return;
    }
    this.loadedId = pr.id;
    this.kept.set(false);
    this.values = { ...pr.changes };
    delete this.values['portions'];
    this.portions = this.rowsOf(pr.changes['portions']);
  }

  private rowsOf(raw: unknown): PortionRow[] {
    if (!Array.isArray(raw)) return [];
    return (raw as Record<string, unknown>[]).map((entry) => ({
      entry,
      op: String(entry['op'] ?? 'add'),
      label: String(entry['label'] ?? ''),
      unit_code: String(entry['unit_code'] ?? ''),
      amount: entry['amount'] == null ? null : Number(entry['amount']),
    }));
  }

  kindOf(key: string): 'number' | 'boolean' | 'text' {
    const v = this.proposal().changes[key];
    if (typeof v === 'boolean' || key === 'verified') return 'boolean';
    if (typeof v === 'number' || NUMERIC.has(key)) return 'number';
    return 'text';
  }

  /** A field's value as it would be sent: a cleared input is `null`, text is trimmed. */
  private normal(key: string, value: unknown): unknown {
    if (value === undefined || value === null || value === '') return null;
    if (this.kindOf(key) === 'number') return Number(value);
    if (typeof value === 'string') return value.trim() || null;
    return value;
  }

  /** The portions as they would be sent, or `null` once none is left. */
  private portionValue(): Record<string, unknown>[] | null {
    if (!this.portions.length) return null;
    return this.portions.map((row) => {
      if (row.op === 'delete') return row.entry;
      // only what was touched is written: an `update` line names just the fields it changes
      const out: Record<string, unknown> = { ...row.entry };
      if (row.unit_code !== String(row.entry['unit_code'] ?? '')) out['unit_code'] = row.unit_code;
      if (row.label !== String(row.entry['label'] ?? '') || (row.op === 'add' && !('label' in row.entry))) {
        out['label'] = row.label.trim() || row.unit_code;
      }
      const was = row.entry['amount'] == null ? null : Number(row.entry['amount']);
      if (row.amount !== was && row.amount !== null) out['amount'] = row.amount;
      return out;
    });
  }

  isEdited(key: string): boolean {
    return this.normal(key, this.values[key]) !== this.normal(key, this.proposal().changes[key]);
  }

  /** Only what differs from the proposal: `null` withdraws a field the proposal carries. */
  edited(): Record<string, unknown> {
    const pr = this.proposal();
    const out: Record<string, unknown> = {};
    for (const key of [...this.fields(), ...(pr.kind === 'version' ? ['valid_from'] : [])]) {
      if (this.isEdited(key)) out[key] = this.normal(key, this.values[key]);
    }
    const portions = this.portionValue();
    if (JSON.stringify(portions) !== JSON.stringify(pr.changes['portions'] ?? null)) out['portions'] = portions;
    // a field the proposal never had and that stays empty is not a change
    for (const [k, v] of Object.entries(out)) if (v === null && !(k in pr.changes)) delete out[k];
    return out;
  }

  dirty(): boolean {
    return Object.keys(this.edited()).length > 0;
  }

  isSelected(key: string): boolean {
    return !this.unselected().has(key);
  }

  toggle(key: string): void {
    this.unselected.update((set) => {
      const next = new Set(set);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  /**
   * What approving sends. Corrected values travel as `changes`; a field unticked or cleared
   * is left out of `fields`, which is only sent when something is left out.
   */
  decision(): ProposalDecision {
    const pr = this.proposal();
    const edited = this.edited();
    const own = Object.keys(pr.changes).filter((k) => k !== 'valid_from');
    const kept = own.filter((k) => this.isSelected(k) && !(k in edited && edited[k] === null));
    const changes: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(edited)) {
      if (v !== null && (this.isSelected(k) || k === 'valid_from')) changes[k] = v;
    }
    const body: ProposalDecision = {};
    if (Object.keys(changes).length) body.changes = changes;
    if (kept.length < own.length) body.fields = kept;
    return body;
  }

  /** Something is left to apply. */
  applicable(): boolean {
    const d = this.decision();
    return !d.fields || d.fields.length > 0 || !!d.changes;
  }

  approveLabel(): string {
    if (this.selectable()) {
      const own = Object.keys(this.proposal().changes).filter((k) => k !== 'valid_from');
      const n = own.filter((k) => this.isSelected(k)).length;
      if (n < own.length) return this.i18n.t('Apply {n} of {total}', { n, total: own.length });
      return this.i18n.t(this.dirty() ? 'Apply with corrections' : 'Apply all');
    }
    if (this.dirty()) return this.i18n.t('Approve with corrections');
    return this.approveText() ?? this.i18n.t('Approve');
  }

  /** The unit a portion's weight is stated in. */
  portionUnit(row: PortionRow): string {
    return String(row.entry['amount_unit'] ?? this.values['reference_unit'] ?? 'g');
  }

  opLabel(op: string): string {
    if (op === 'update') return this.i18n.t('portion update');
    if (op === 'delete') return this.i18n.t('portion delete');
    return this.i18n.t('portion add');
  }

  text(value: unknown): string {
    if (value === null || value === undefined || value === '') return '–';
    if (Array.isArray(value)) return this.i18n.t('{n} entries', { n: value.length });
    if (typeof value === 'number') return formatAmount(value);
    if (typeof value === 'boolean') return this.i18n.t(value ? 'yes' : 'no');
    return String(value);
  }

  /** What the agent filed, beside a field a person has since corrected. */
  agentValue(key: string): string | null {
    const original = this.proposal().proposed;
    if (!original) return null;
    const was = original[key];
    if (this.normal(key, was) === this.normal(key, this.proposal().changes[key])) return null;
    return this.text(was);
  }

  addPortion(): void {
    const unit = this.countUnits()[0]?.code ?? 'piece';
    this.portions = [
      ...this.portions,
      { entry: { op: 'add', amount_unit: this.values['reference_unit'] ?? 'g' }, op: 'add', label: '', unit_code: unit, amount: null },
    ];
  }

  removePortion(index: number): void {
    this.portions = this.portions.filter((_, i) => i !== index);
  }

  /** Amend the proposal without deciding it. */
  save(): void {
    const changes = this.edited();
    if (!Object.keys(changes).length) return;
    this.busy.set(true);
    this.error.set(null);
    this.api.amendProposal(this.proposal().id, { changes }).subscribe({
      next: (pr) => {
        this.busy.set(false);
        this.loadedId = null; // take the answer as the new starting point
        this.take(pr);
        this.amended.emit(pr);
      },
      error: (e: unknown) => this.failed(e),
    });
  }

  approve(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api.approveProposal(this.proposal().id, this.decision()).subscribe({
      next: (pr) => {
        this.busy.set(false);
        this.decided.emit(pr);
      },
      error: (e: unknown) => this.failed(e),
    });
  }

  reject(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api.rejectProposal(this.proposal().id).subscribe({
      next: (pr) => {
        this.busy.set(false);
        this.decided.emit(pr);
      },
      error: (e: unknown) => this.failed(e),
    });
  }

  private failed(e: unknown): void {
    this.busy.set(false);
    this.error.set(describeError(e));
  }
}
