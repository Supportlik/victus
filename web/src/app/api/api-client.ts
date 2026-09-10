import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import {
  AgentLock,
  AgentRun,
  AgentRunStatus,
  ApiToken,
  ApiTokenCreated,
  ApproveRequest,
  Capture,
  CaptureStatus,
  Category,
  DayFlags,
  DayLog,
  DayMessage,
  DaySummary,
  DraftListEntry,
  DraftSummary,
  Health,
  LineItem,
  LineItemInput,
  MatchCandidate,
  Me,
  Meal,
  Passkey,
  Portion,
  Product,
  ProductProposal,
  ProductUsage,
  ProductInput,
  Recipe,
  RecipeBatch,
  RecipeIngredient,
  ReportDefinition,
  ReportResult,
  AgentStatus,
  BodyMeasurement,
  BodyMeasurementInput,
  ReportSnapshot,
  Rule,
  TargetBand,
  TenantSettingsVersion,
  Unit,
  WeightEntry,
} from './models';

export const API_BASE = '/api/v1';

type Params = Record<string, string | number | boolean | null | undefined>;

function params(p: Params): HttpParams {
  let hp = new HttpParams();
  for (const [k, v] of Object.entries(p)) {
    if (v !== undefined && v !== null && v !== '') hp = hp.set(k, String(v));
  }
  return hp;
}

/**
 * Thin, typed wrapper around the REST API. One method per endpoint, no business logic.
 * Replaced by a generated client later; features import only from `./api`.
 */
@Injectable({ providedIn: 'root' })
export class ApiClient {
  private readonly http = inject(HttpClient);

  // system
  health(): Observable<Health> {
    return this.http.get<Health>(`${API_BASE}/health`);
  }

  // auth
  me(): Observable<Me> {
    return this.http.get<Me>(`${API_BASE}/auth/me`);
  }
  logout(): Observable<void> {
    return this.http.post<void>(`${API_BASE}/auth/logout`, {});
  }
  webauthnRegisterOptions(body: { name?: string; invitation?: string } = {}): Observable<unknown> {
    return this.http.post(`${API_BASE}/auth/webauthn/register/options`, body);
  }
  webauthnRegisterVerify(body: unknown): Observable<Passkey> {
    return this.http.post<Passkey>(`${API_BASE}/auth/webauthn/register/verify`, body);
  }
  webauthnLoginOptions(body: { email?: string } = {}): Observable<unknown> {
    return this.http.post(`${API_BASE}/auth/webauthn/login/options`, body);
  }
  webauthnLoginVerify(body: unknown): Observable<Me> {
    return this.http.post<Me>(`${API_BASE}/auth/webauthn/login/verify`, body);
  }
  recovery(code: string, email: string): Observable<Me> {
    return this.http.post<Me>(`${API_BASE}/auth/recovery`, { code, email });
  }
  passkeys(): Observable<Passkey[]> {
    return this.http.get<Passkey[]>(`${API_BASE}/auth/passkeys`);
  }
  deletePasskey(id: string): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/auth/passkeys/${id}`);
  }
  tokens(): Observable<ApiToken[]> {
    return this.http.get<ApiToken[]>(`${API_BASE}/auth/tokens`);
  }
  createToken(body: { name: string; scopes: string[]; expires_at: string | null }): Observable<ApiTokenCreated> {
    return this.http.post<ApiTokenCreated>(`${API_BASE}/auth/tokens`, body);
  }
  revokeToken(id: string): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/auth/tokens/${id}`);
  }

  // master data
  units(): Observable<Unit[]> {
    return this.http.get<Unit[]>(`${API_BASE}/units`);
  }
  categories(): Observable<Category[]> {
    return this.http.get<Category[]>(`${API_BASE}/categories`);
  }
  products(q: string, opts: { category?: number; limit?: number; offset?: number; on?: string | null } = {}): Observable<Product[]> {
    return this.http.get<Product[]>(`${API_BASE}/products`, { params: params({ q, ...opts }) });
  }
  product(id: number): Observable<Product> {
    return this.http.get<Product>(`${API_BASE}/products/${id}`);
  }
  createProduct(body: ProductInput): Observable<Product> {
    return this.http.post<Product>(`${API_BASE}/products`, body);
  }
  productUsage(id: number, limit = 100): Observable<ProductUsage> {
    return this.http.get<ProductUsage>(`${API_BASE}/products/${id}/usage`, { params: params({ limit }) });
  }
  updateProduct(id: number, body: Partial<ProductInput>): Observable<Product> {
    return this.http.patch<Product>(`${API_BASE}/products/${id}`, body);
  }
  deleteProduct(id: number): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/products/${id}`);
  }
  matchProducts(text: string): Observable<MatchCandidate[]> {
    return this.http.post<MatchCandidate[]>(`${API_BASE}/products/match`, { text });
  }
  createPortion(productId: number, body: Omit<Portion, 'id' | 'product_id'>): Observable<Portion> {
    return this.http.post<Portion>(`${API_BASE}/products/${productId}/portions`, body);
  }
  updatePortion(id: number, body: Partial<Portion>): Observable<Portion> {
    return this.http.patch<Portion>(`${API_BASE}/portions/${id}`, body);
  }
  deletePortion(id: number): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/portions/${id}`);
  }
  recipes(): Observable<Recipe[]> {
    return this.http.get<Recipe[]>(`${API_BASE}/recipes`);
  }
  recipe(id: number): Observable<Recipe> {
    return this.http.get<Recipe>(`${API_BASE}/recipes/${id}`);
  }
  cookBatch(recipeId: number, body: { cooked_at: string; servings?: number; total_weight_g: number }): Observable<RecipeBatch> {
    return this.http.post<RecipeBatch>(`${API_BASE}/recipes/${recipeId}/batches`, body);
  }
  updateRecipe(id: number, body: Partial<Pick<Recipe, 'name' | 'default_servings'>>): Observable<Recipe> {
    return this.http.patch<Recipe>(`${API_BASE}/recipes/${id}`, body);
  }
  replaceIngredients(id: number, ingredients: Omit<RecipeIngredient, 'id'>[]): Observable<Recipe> {
    return this.http.put<Recipe>(`${API_BASE}/recipes/${id}/ingredients`, { ingredients });
  }
  batch(id: number): Observable<RecipeBatch> {
    return this.http.get<RecipeBatch>(`${API_BASE}/batches/${id}`);
  }

  // days
  days(from: string, to: string, status?: string): Observable<DaySummary[]> {
    return this.http.get<DaySummary[]>(`${API_BASE}/days`, { params: params({ from, to, status }) });
  }
  day(date: string): Observable<DayLog> {
    return this.http.get<DayLog>(`${API_BASE}/days/${date}`);
  }
  /** Creates the day; `reliable` is mandatory because there is no default. */
  createDay(date: string, body: { reliable: boolean; training_type?: string | null; notes?: string | null }): Observable<DayLog> {
    return this.http.post<DayLog>(`${API_BASE}/days/${date}`, body);
  }
  updateDay(date: string, body: DayFlags): Observable<DayLog> {
    return this.http.put<DayLog>(`${API_BASE}/days/${date}`, body);
  }
  updateMeal(mealId: number, body: { name?: string; time?: string | null }): Observable<Meal> {
    return this.http.patch<Meal>(`${API_BASE}/meals/${mealId}`, body);
  }
  deleteMeal(mealId: number): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/meals/${mealId}`);
  }
  addMeal(date: string, body: { name: string; time?: string | null }): Observable<Meal> {
    return this.http.post<Meal>(`${API_BASE}/days/${date}/meals`, body);
  }
  addLineItem(mealId: number, body: LineItemInput): Observable<LineItem> {
    return this.http.post<LineItem>(`${API_BASE}/meals/${mealId}/line-items`, body);
  }
  updateLineItem(id: number, body: Partial<LineItemInput>): Observable<LineItem> {
    return this.http.patch<LineItem>(`${API_BASE}/line-items/${id}`, body);
  }
  approveLineItem(id: number, body: Record<string, unknown> = {}): Observable<LineItem> {
    return this.http.post<LineItem>(`${API_BASE}/line-items/${id}/approve`, body);
  }
  deleteLineItem(id: number): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/line-items/${id}`);
  }
  closeDay(date: string): Observable<DayLog> {
    return this.http.post<DayLog>(`${API_BASE}/days/${date}/close`, {});
  }
  reopenDay(date: string): Observable<DayLog> {
    return this.http.post<DayLog>(`${API_BASE}/days/${date}/reopen`, {});
  }
  dayMessages(date: string): Observable<DayMessage[]> {
    return this.http.get<DayMessage[]>(`${API_BASE}/days/${date}/messages`);
  }
  addDayMessage(date: string, text: string): Observable<DayMessage> {
    return this.http.post<DayMessage>(`${API_BASE}/days/${date}/messages`, { text });
  }

  // drafts
  drafts(): Observable<DraftListEntry[]> {
    return this.http.get<DraftListEntry[]>(`${API_BASE}/drafts`);
  }
  draftSummary(date: string): Observable<DraftSummary> {
    return this.http.get<DraftSummary>(`${API_BASE}/drafts/${date}/summary`);
  }
  approveDraft(date: string, body: ApproveRequest): Observable<DayLog> {
    return this.http.post<DayLog>(`${API_BASE}/drafts/${date}/approve`, body);
  }
  discardDraft(date: string): Observable<{ removed: number }> {
    return this.http.post<{ removed: number }>(`${API_BASE}/drafts/${date}/discard`, {});
  }

  // weight
  weight(from: string, to: string): Observable<WeightEntry[]> {
    return this.http.get<WeightEntry[]>(`${API_BASE}/weight`, { params: params({ from, to }) });
  }
  addWeight(body: { measured_at: string; kg: number }): Observable<WeightEntry> {
    return this.http.post<WeightEntry>(`${API_BASE}/weight`, body);
  }
  deleteWeight(id: number): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/weight/${id}`);
  }
  /** Tape-measure sessions, oldest first (R76). */
  bodyMeasurements(query: { from?: string; to?: string; limit?: number } = {}): Observable<BodyMeasurement[]> {
    return this.http.get<BodyMeasurement[]>(`${API_BASE}/body-measurements`, {
      params: params({ from: query.from, to: query.to, limit: query.limit }),
    });
  }
  addBodyMeasurement(body: BodyMeasurementInput): Observable<BodyMeasurement> {
    return this.http.post<BodyMeasurement>(`${API_BASE}/body-measurements`, body);
  }
  deleteBodyMeasurement(id: number): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/body-measurements/${id}`);
  }

  // settings
  targetBands(): Observable<TargetBand[]> {
    return this.http.get<TargetBand[]>(`${API_BASE}/target-bands`);
  }
  /** Upsert keyed by (valid_from, training_type). */
  upsertTargetBand(body: Omit<TargetBand, 'id'>): Observable<TargetBand> {
    return this.http.post<TargetBand>(`${API_BASE}/target-bands`, body);
  }
  rules(): Observable<Rule[]> {
    return this.http.get<Rule[]>(`${API_BASE}/settings/rules`);
  }
  putRule(body: Partial<Rule> & { when: string; then: string }): Observable<Rule> {
    return this.http.put<Rule>(`${API_BASE}/settings/rules`, body);
  }
  deleteRule(name: string): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/settings/rules/${encodeURIComponent(name)}`);
  }
  settings(): Observable<TenantSettingsVersion> {
    return this.http.get<TenantSettingsVersion>(`${API_BASE}/settings`);
  }
  putSettings(data: Record<string, unknown>): Observable<TenantSettingsVersion> {
    return this.http.put<TenantSettingsVersion>(`${API_BASE}/settings`, { data });
  }
  settingsVersions(): Observable<TenantSettingsVersion[]> {
    return this.http.get<TenantSettingsVersion[]>(`${API_BASE}/settings/versions`);
  }

  // captures & agent
  captures(status?: string, date?: string, productId?: number): Observable<Capture[]> {
    return this.http.get<Capture[]>(`${API_BASE}/captures`, { params: params({ status, date, product_id: productId }) });
  }
  capture(id: string): Observable<Capture> {
    return this.http.get<Capture>(`${API_BASE}/captures/${id}`);
  }
  deleteCapture(id: string): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/captures/${id}`);
  }
  snapshots(report?: string, limit = 50): Observable<ReportSnapshot[]> {
    return this.http.get<ReportSnapshot[]>(`${API_BASE}/reports/snapshots`, { params: params({ report, limit }) });
  }
  snapshot(id: string): Observable<ReportSnapshot> {
    return this.http.get<ReportSnapshot>(`${API_BASE}/reports/snapshots/${id}`);
  }
  createSnapshot(report: string, range: { from?: string | null; to?: string | null; label?: string; asOf?: string | null } = {}): Observable<ReportSnapshot> {
    return this.http.post<ReportSnapshot>(`${API_BASE}/reports/${report}/snapshots`, {}, { params: params({ from: range.from, to: range.to, label: range.label, as_of: range.asOf }) });
  }
  assessSnapshot(id: string, markdown: string): Observable<ReportSnapshot> {
    return this.http.post<ReportSnapshot>(`${API_BASE}/reports/snapshots/${id}/assess`, { markdown });
  }
  deleteSnapshot(id: string): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/reports/snapshots/${id}`);
  }
  proposals(params_: { status?: string; product_id?: number } = {}): Observable<ProductProposal[]> {
    return this.http.get<ProductProposal[]>(`${API_BASE}/proposals`, { params: params({ status: params_.status ?? 'pending', product_id: params_.product_id }) });
  }
  approveProposal(id: string, body: { changes?: Record<string, unknown>; fields?: string[] } = {}): Observable<ProductProposal> {
    return this.http.post<ProductProposal>(`${API_BASE}/proposals/${id}/approve`, body);
  }
  rejectProposal(id: string): Observable<ProductProposal> {
    return this.http.post<ProductProposal>(`${API_BASE}/proposals/${id}/reject`, {});
  }
  uploadCapture(form: FormData): Observable<Capture> {
    return this.http.post<Capture>(`${API_BASE}/captures`, form);
  }
  updateCapture(id: string, body: { status?: CaptureStatus; target_date?: string | null }): Observable<Capture> {
    return this.http.patch<Capture>(`${API_BASE}/captures/${id}`, body);
  }
  transcribeCapture(id: string, force = false): Observable<Capture> {
    return this.http.post<Capture>(`${API_BASE}/captures/${id}/transcribe`, {}, {
      params: params({ force: force ? 'true' : undefined }),
    });
  }
  /** URL of an attachment (image, audio); served inline, session cookie authenticates. */
  attachmentUrl(id: string): string {
    return `${API_BASE}/attachments/${id}`;
  }
  /** Every version of a product, oldest first (R70). */
  productVersions(id: number): Observable<Product[]> {
    return this.http.get<Product[]>(`${API_BASE}/products/${id}/versions`);
  }
  /** Record changed values from a day on; the old version keeps the days before it. */
  createProductVersion(id: number, validFrom: string, changes: Record<string, unknown>): Observable<Product> {
    return this.http.post<Product>(`${API_BASE}/products/${id}/versions`, { valid_from: validFrom, changes });
  }
  /** Whether a queued run would be picked up: ready, no_key or disabled. */
  agentStatus(): Observable<AgentStatus> {
    return this.http.get<AgentStatus>(`${API_BASE}/agent/status`);
  }
  startAgentRun(body: { mode: AgentRun['mode']; captures?: string[]; from?: string; to?: string }): Observable<AgentRun> {
    return this.http.post<AgentRun>(`${API_BASE}/agent/runs`, body);
  }
  agentRun(id: string): Observable<AgentRun> {
    return this.http.get<AgentRun>(`${API_BASE}/agent/runs/${id}`);
  }
  agentRuns(query: { limit?: number; status?: AgentRunStatus } = {}): Observable<AgentRun[]> {
    return this.http.get<AgentRun[]>(`${API_BASE}/agent/runs`, {
      params: params({ limit: query.limit, status: query.status }),
    });
  }
  cancelAgentRun(id: string): Observable<AgentRun> {
    return this.http.post<AgentRun>(`${API_BASE}/agent/runs/${id}/cancel`, {});
  }
  agentLocks(): Observable<AgentLock[]> {
    return this.http.get<AgentLock[]>(`${API_BASE}/agent/locks`);
  }
  forceUnlock(date: string): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/agent/locks/${date}`);
  }

  // reports
  reports(): Observable<ReportDefinition[]> {
    return this.http.get<ReportDefinition[]>(`${API_BASE}/reports`);
  }
  renderReport(name: string, from: string, to: string, asOf?: string): Observable<ReportResult> {
    return this.http.post<ReportResult>(`${API_BASE}/reports/${name}/render`, {}, {
      params: params({ format: 'json', from, to, as_of: asOf }),
    });
  }
}
