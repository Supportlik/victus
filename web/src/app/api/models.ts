/**
 * Hand-written API models for Stage 1. Field names follow docs/API.md, docs/REPORTS.md and
 * docs/GLOSSARY.md exactly, so a generated client (planned: @hey-api/openapi-ts) can replace this
 * file without touching the features.
 */

export type MacroKey = 'kcal' | 'protein' | 'carbs' | 'fat' | 'fiber' | 'salt';
export const MACRO_KEYS: readonly MacroKey[] = ['kcal', 'protein', 'carbs', 'fat', 'fiber', 'salt'];
export const MACRO_LABEL: Record<MacroKey, string> = {
  kcal: 'Calories',
  protein: 'Protein',
  carbs: 'Carbs',
  fat: 'Fat',
  fiber: 'Fiber',
  salt: 'Salt',
};
export const MACRO_UNIT: Record<MacroKey, string> = {
  kcal: 'kcal',
  protein: 'g',
  carbs: 'g',
  fat: 'g',
  fiber: 'g',
  salt: 'g',
};

export type Macros = Partial<Record<MacroKey, number | null>>;

export type DayStatus = 'draft' | 'open' | 'closed';
export type TrainingType = 'rest' | 'strength' | 'martial_arts';
export type ConsumableKind = 'product' | 'recipe_batch' | 'ad_hoc';
export type BandZone = 'below_min' | 'below_optimum' | 'optimal' | 'above_optimum' | 'above_max';
export type Quality = 'red' | 'yellow' | 'green';

export interface Health {
  status: string;
  version: string;
  checks: Record<string, string>;
  backup_age_hours?: number | null;
}

// ── Auth ─────────────────────────────────────────────────────────────────
export interface Me {
  user: { id: string; display_name: string; email: string; role: 'owner' | 'member' };
  tenant: { id: string; slug: string; name: string };
  csrf_token: string;
  passkeys: number;
  /** True after a recovery-code login: only passkey registration and logout are allowed. */
  recovery_session: boolean;
}

export interface Passkey {
  id: string;
  name: string | null;
  created_at: string;
  last_used_at: string | null;
}

export interface ApiToken {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface ApiTokenCreated extends ApiToken {
  /** Full secret, shown exactly once. */
  token: string;
}

// ── Master data ──────────────────────────────────────────────────────────
export interface Unit {
  code: string;
  singular: string;
  plural: string;
  unit_type: 'mass' | 'volume' | 'count';
}

export interface Category {
  id: number;
  name: string;
}

export interface Portion {
  id: number;
  product_id: number;
  unit_code: string;
  label: string;
  description?: string | null;
  amount: number;
  amount_unit: 'g' | 'ml';
  is_default: boolean;
  weight_source?: 'weighed' | 'estimated' | null;
}

export interface Product extends Macros {
  id: number;
  name: string;
  icon?: string | null;
  brand?: string | null;
  category_id?: number | null;
  category?: string | null;
  reference_amount: number;
  reference_unit: 'g' | 'ml';
  source?: string | null;
  verified: boolean;
  ean?: string | null;
  note?: string | null;
  portions?: Portion[];
}

export type ProductInput = Omit<Product, 'id' | 'portions'>;

export interface MatchCandidate {
  consumable_id: number;
  name: string;
  kind: ConsumableKind;
  tier: number;
  score: number;
}

export interface RecipeIngredient {
  id: number;
  position: number;
  product_id?: number | null;
  product_name?: string | null;
  amount?: number | null;
  unit_code?: string | null;
  free_text?: string | null;
}

export interface RecipeBatch extends Macros {
  id: number;
  cooked_at: string | null;
  servings?: number | null;
  total_weight_g?: number | null;
  finished_at?: string | null;
}

export interface Recipe {
  id: number;
  name: string;
  default_servings?: number | null;
  ingredients?: RecipeIngredient[];
  batches?: RecipeBatch[];
}

// ── Days ─────────────────────────────────────────────────────────────────
export interface LineItem extends Macros {
  id: number;
  meal_id: number;
  position: number;
  consumable_id: number;
  consumable_name: string;
  consumable_kind: ConsumableKind;
  amount?: number | null;
  unit_code?: string | null;
  base_amount: number;
  base_unit: 'g' | 'ml';
  estimated: boolean;
  amount_estimated: boolean;
  is_draft: boolean;
  confidence?: number | null;
  rationale?: string | null;
  alternatives?: MatchCandidate[] | null;
  raw_text?: string | null;
  /** The capture this item came from, so a draft can be shown next to its source. */
  source_capture_id?: string | null;
  source_kind?: 'transcript' | 'image' | 'text' | null;
  /** Product category name; drives the small icon in front of the item. */
  category?: string | null;
  /** The product's own icon, which wins over the guessed one. */
  icon?: string | null;
}

export interface Meal {
  id: number;
  position: number;
  name: string;
  time?: string | null;
  line_items: LineItem[];
  totals: Macros;
}

export interface BandSpec {
  min: number;
  opt_min: number;
  opt_max: number;
  target: number;
  max: number;
  stretch?: number | null;
}

export interface TargetBand {
  id: number;
  name: string;
  training_type: TrainingType | null;
  valid_from: string;
  valid_until: string | null;
  kcal?: BandSpec | null;
  protein: BandSpec;
  carbs: BandSpec;
  fat: BandSpec;
  fiber: BandSpec;
  salt: BandSpec;
  note?: string | null;
}

export interface Finding {
  kind: number;
  code: string;
  message: string;
}

export interface DaySummary {
  date: string;
  status: DayStatus;
  reliable: boolean | null;
  training_type: TrainingType | null;
  macros: Macros;
  has_drafts?: boolean;
  weight_kg?: number | null;
}

export interface DayLog extends DaySummary {
  weekday?: string;
  meals: Meal[];
  target_band: TargetBand | null;
  zones?: Partial<Record<MacroKey, BandZone>>;
  findings: Finding[];
  notes?: string | null;
}

export interface DayFlags {
  reliable?: boolean | null;
  training_type?: TrainingType | null;
  notes?: string | null;
}

export interface LineItemInput {
  consumable_id: number;
  amount: number;
  unit_code: string;
  portion_id?: number | null;
  estimated?: boolean;
}

export interface DayMessage {
  id: string;
  role: 'user' | 'agent' | 'system';
  kind: 'text' | 'summary' | 'question' | 'correction' | 'note';
  content: string;
  created_at: string;
  /** For user messages: capture processing state. */
  processing_state?: CaptureStatus | null;
  /** Set when the message is a capture (text typed here, voice note, photo). */
  capture_id?: string | null;
  capture_kind?: 'text' | 'audio' | 'image' | null;
  attachment_id?: string | null;
  attachment_mime?: string | null;
  transcript?: string | null;
}

/** A report frozen at a point in time, with the assessment written for those numbers. */
export interface ReportSnapshot {
  id: string;
  report_name: string;
  title: string;
  label?: string | null;
  period_start: string;
  period_end: string;
  today: string;
  status: 'frozen' | 'assessed' | 'failed';
  created_at: string;
  created_by?: string | null;
  assessment_md?: string | null;
  assessed_at?: string | null;
  model?: string | null;
  prompt_version?: string | null;
  input_tokens?: number;
  output_tokens?: number;
  cost_usd?: number;
  /** The frozen render; only the detail carries it. */
  result?: Record<string, unknown> | null;
}

/** A product change the agent read from a label photo or note; a person decides. */
export interface ProductProposal {
  id: string;
  product_id: number;
  product_name?: string | null;
  capture_id?: string | null;
  run_id?: string | null;
  changes: Record<string, unknown>;
  current: Record<string, unknown>;
  rationale?: string | null;
  source?: string | null;
  status: 'pending' | 'approved' | 'rejected';
  created_at: string;
  decided_at?: string | null;
}

// ── Drafts ───────────────────────────────────────────────────────────────
export interface DraftListEntry {
  date: string;
  status: DayStatus;
  draft_items: number;
  kcal?: number | null;
  estimated_items: number;
  created_by?: string;
}

export interface DraftSummary {
  date: string;
  markdown: string;
  day: DayLog;
}

export interface DraftCorrection {
  line_item_id: number;
  amount?: number;
  unit_code?: string;
  consumable_id?: number;
  delete?: boolean;
}

export interface ApproveRequest {
  corrections: DraftCorrection[];
  close: boolean;
}

// ── Weight ───────────────────────────────────────────────────────────────
export interface WeightEntry {
  id: number;
  measured_at: string;
  kg: number;
  source: 'scale_sync' | 'manual' | 'import';
}

// ── Captures & agent ─────────────────────────────────────────────────────
export type CaptureStatus = 'new' | 'in_progress' | 'assigned' | 'processed' | 'discarded' | 'failed';

export interface Capture {
  id: string;
  kind: 'text' | 'audio' | 'image';
  captured_at: string;
  target_date: string | null;
  text?: string | null;
  status: CaptureStatus;
  transcript?: string | null;
  attachment_id?: string | null;
  attachment_mime?: string | null;
  content_hash?: string;
  processed_at?: string | null;
  agent_run_id?: string | null;
  /** Set when the capture is about one product (label photo, correction). */
  product_id?: number | null;
  /** False when the upload matched an existing capture by content hash (no-op). */
  created?: boolean;
}

export type AgentRunStatus = 'queued' | 'running' | 'finished' | 'budget_exceeded' | 'failed' | 'cancelled';
export type AgentRunMode = 'historical' | 'batch' | 'manual' | 'follow_up';

export interface AgentSession {
  date: string;
  model: string | null;
  prompt_version?: string | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  outcome: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface AgentRun {
  id: string;
  runner?: 'worker' | 'external';
  mode: AgentRunMode;
  status: AgentRunStatus;
  created_at?: string;
  started_at: string | null;
  finished_at: string | null;
  captures?: string[];
  days: string[];
  input_tokens?: number;
  output_tokens?: number;
  cost_usd?: number;
  model?: string | null;
  prompt_version?: string | null;
  summary_md?: string | null;
  error?: string | null;
  sessions?: AgentSession[];
}

export interface AgentLock {
  date: string;
  runner: 'worker' | 'external';
  run_id: string;
  locked_until: string;
}

// ── Settings ─────────────────────────────────────────────────────────────
export interface TenantSettingsVersion {
  version: number;
  valid_from: string;
  data: Record<string, unknown>;
  changed_by?: string | null;
}

// ── Reports ──────────────────────────────────────────────────────────────
// Shapes follow src/victus/reports/results.py rendered by render/json.py
// (dates ISO, enums as strings, every block carries `meta` and an `error` flag).
export interface ReportDefinition {
  name: string;
  title: string;
  description?: string | null;
  builtin: boolean;
  period: { default: string; options: string[] };
}

export interface BlockMeta {
  type: string;
  id: string | null;
  title: string;
}

interface BlockBase {
  meta: BlockMeta;
  error: boolean;
}

export interface KpiTileBlock extends BlockBase {
  source: string;
  value: number | null;
  unit: string;
  decimals: number;
  delta?: number | null;
  zone?: BandZone | null;
  quality?: Quality | null;
  note?: string | null;
}

export interface BandStat {
  below_min: number;
  below_optimum: number;
  optimal: number;
  above_optimum: number;
  above_max: number;
  mean: number | null;
  n: number;
}
export interface BandDistributionRow {
  macro: MacroKey | string;
  stat: BandStat;
  band: BandSpec | null;
  days_rated: number;
}
export interface BandDistributionBlock extends BlockBase {
  rows: BandDistributionRow[];
}

export interface TdeeWindowRow {
  window_days: number;
  start: string;
  end: string;
  mean_kcal: number | null;
  delta_ma_kg: number | null;
  tdee: number | null;
  rejected_tdee: number | null;
  coverage_pct: number;
  days_with_kcal: number;
  measured_days: number;
  days_without_macros: number;
  in_corridor: number;
  above_corridor: number;
  below_corridor: number;
  mean_protein: number | null;
  quality: Quality | null;
}
export interface TdeeWindowsBlock extends BlockBase {
  rows: TdeeWindowRow[];
  show_quality: boolean;
  reference_tdee: number | null;
  reference_basis: string;
}

export interface TrendRow {
  window: number;
  slope_per_day: number | null;
  kg_per_week: number | null;
  actual_delta: number | null;
  start: string;
  end: string;
  points: number;
  measured_days: number;
}
export interface TrendBlock extends BlockBase {
  rows: TrendRow[];
}

export interface ForecastRow {
  window: number;
  kg_per_week: number | null;
  m1: number | null;
  m3: number | null;
  m6: number | null;
  at_goal_date: number | null;
  eta: string | null;
}
export interface ForecastBlock extends BlockBase {
  rows: ForecastRow[];
  horizons: string[];
  with_eta: boolean;
  current_kg: number | null;
  goal_kg: number;
  goal_date: string;
}

export interface StageRow {
  /** The stage's own planned line: [date, remaining kg]. */
  path?: [string, number][];
  name: string;
  date: string;
  planned_remaining_today: number;
  gap: number;
  required_kg_per_week: number;
  required_pct_per_week: number;
  eat_kcal_per_day: number | null;
  feasible: boolean;
}
export interface BurndownResult {
  anchor: string;
  remaining_at_anchor: number;
  remaining_today: number;
  planned_remaining_today: number;
  gap: number;
  burned: number;
  days_elapsed: number;
  actual_rate_per_week: number;
  planned_rate_per_week: number;
  required_rate_per_week: number;
  target_path: [string, number][];
  actual: [string, number][];
  stages: StageRow[];
}
export interface BurndownBlock extends BlockBase {
  result: BurndownResult;
  goal_kg: number;
  goal_date: string;
}

export interface WeeklyChartRow {
  week_start: string;
  mean_kg: number | null;
  delta_kg: number | null;
  mean_kcal: number | null;
  days_with_kcal: number;
  tdee: number | null;
}
export interface WeeklyChartBlock extends BlockBase {
  rows: WeeklyChartRow[];
  series: string[];
}

export interface DayListRow {
  date: string;
  macros: Macros;
  weight: number | null;
  training_type: TrainingType | null;
  status: DayStatus | null;
  reliable: boolean | null;
  countable: boolean;
}
export interface DayListBlock extends BlockBase {
  columns: string[];
  rows: DayListRow[];
}

export interface TextFindingBlock extends BlockBase {
  source: 'agent' | 'manual' | string;
  markdown: string | null;
}

export interface ErrorBlock extends BlockBase {
  error: true;
  message: string;
}

export type ReportBlock =
  | KpiTileBlock
  | BandDistributionBlock
  | TdeeWindowsBlock
  | TrendBlock
  | ForecastBlock
  | BurndownBlock
  | WeeklyChartBlock
  | DayListBlock
  | TextFindingBlock
  | ErrorBlock;

export interface ReportResult {
  name: string;
  title: string;
  description: string | null;
  period: { start: string; end: string; days: number };
  from?: string;
  to?: string;
  today: string;
  generated_at: string;
  blocks: ReportBlock[];
}

export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
}
