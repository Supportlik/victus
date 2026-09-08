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
  ProductInput,
  Recipe,
  RecipeBatch,
  RecipeIngredient,
  ReportDefinition,
  ReportResult,
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
  products(q: string, opts: { category?: number; limit?: number } = {}): Observable<Product[]> {
    return this.http.get<Product[]>(`${API_BASE}/products`, { params: params({ q, ...opts }) });
  }
  product(id: number): Observable<Product> {
    return this.http.get<Product>(`${API_BASE}/products/${id}`);
  }
  createProduct(body: ProductInput): Observable<Product> {
    return this.http.post<Product>(`${API_BASE}/products`, body);
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
  addMeal(date: string, body: { name: string; time?: string | null }): Observable<Meal> {
    return this.http.post<Meal>(`${API_BASE}/days/${date}/meals`, body);
  }
  addLineItem(mealId: number, body: LineItemInput): Observable<LineItem> {
    return this.http.post<LineItem>(`${API_BASE}/meals/${mealId}/line-items`, body);
  }
  updateLineItem(id: number, body: Partial<LineItemInput>): Observable<LineItem> {
    return this.http.patch<LineItem>(`${API_BASE}/line-items/${id}`, body);
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

  // settings
  targetBands(): Observable<TargetBand[]> {
    return this.http.get<TargetBand[]>(`${API_BASE}/target-bands`);
  }
  /** Upsert keyed by (valid_from, training_type). */
  upsertTargetBand(body: Omit<TargetBand, 'id'>): Observable<TargetBand> {
    return this.http.post<TargetBand>(`${API_BASE}/target-bands`, body);
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
  captures(status?: string, date?: string): Observable<Capture[]> {
    return this.http.get<Capture[]>(`${API_BASE}/captures`, { params: params({ status, date }) });
  }
  capture(id: string): Observable<Capture> {
    return this.http.get<Capture>(`${API_BASE}/captures/${id}`);
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
  renderReport(name: string, from: string, to: string): Observable<ReportResult> {
    return this.http.post<ReportResult>(`${API_BASE}/reports/${name}/render`, {}, {
      params: params({ format: 'json', from, to }),
    });
  }
}
