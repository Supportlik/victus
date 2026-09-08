import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { ApiClient, ApiToken, ApiTokenCreated, Health, Passkey, TargetBand, TenantSettingsVersion } from '../../api';
import { AuthService } from '../../core/auth/auth.service';
import { describeError } from '../../core/problem';

const SCOPES = ['read', 'write', 'approve', 'capture:read', 'capture:write', 'agent:write', 'settings', 'backup', 'admin'];

interface SchemaLike {
  properties?: Record<string, unknown>;
  required?: string[];
}

@Component({
  selector: 'v-settings-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <div class="v-page settings">
      <header class="v-page-head"><div><h2>Settings</h2><p class="sub">{{ auth.me()?.tenant?.name }} · signed in as {{ auth.me()?.user?.display_name }}</p></div></header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }

      <section class="v-panel" id="passkeys">
        <h3>Passkeys</h3>
        <p class="v-small v-muted">Keep at least two, on different devices.</p>
        <table class="v-table"><tbody>
          @for (p of passkeys(); track p.id) {
            <tr><td>{{ p.name }}</td><td class="v-muted">added {{ p.created_at.slice(0, 10) }}@if (p.last_used_at) { · last used {{ p.last_used_at.slice(0, 10) }}}</td>
            <td class="num"><button type="button" class="v-btn quiet small danger" (click)="removePasskey(p)" [disabled]="passkeys().length < 2">remove</button></td></tr>
          } @empty { <tr><td class="v-muted">No passkeys listed.</td></tr> }
        </tbody></table>
        <form class="v-form-row add" (ngSubmit)="addPasskey()">
          <label class="v-field"><span>Name for this device</span><input name="pk" [(ngModel)]="passkeyName" placeholder="Phone, Laptop, YubiKey" required /></label>
          <button type="submit" class="v-btn primary" [disabled]="!passkeyName.trim()">Add passkey</button>
        </form>
      </section>

      <section class="v-panel">
        <h3>Target bands</h3>
        <p class="v-small v-muted">One profile per training type; salt has no other source than this table.</p>
        <div class="v-scroll-x"><table class="v-table">
          <thead><tr><th>Profile</th><th>Training</th><th>Valid</th><th>Protein</th><th>Carbs</th><th>Fat</th><th>Fiber</th><th>Salt</th></tr></thead>
          <tbody>
            @for (b of bands(); track b.id) {
              <tr><td>{{ b.name }}</td><td>{{ b.training_type ?? 'any' }}</td><td>{{ b.valid_from }} – {{ b.valid_until ?? 'open' }}</td>
                <td>{{ band(b.protein) }}</td><td>{{ band(b.carbs) }}</td><td>{{ band(b.fat) }}</td><td>{{ band(b.fiber) }}</td><td>{{ band(b.salt) }}</td></tr>
            } @empty { <tr><td colspan="8" class="v-muted">No target bands defined yet — edit the settings below.</td></tr> }
          </tbody>
        </table></div>
      </section>

      <section class="v-panel">
        <h3>Tenant settings <span class="v-small v-muted">@if (settings(); as s) { version {{ s.version }} since {{ s.valid_from }} }</span></h3>
        <p class="v-small v-muted">Goal, calorie corridor, windows, target bands and transcription vocabulary as one document. Saving creates a new version.</p>
        <textarea class="json" [(ngModel)]="settingsJson" name="settings" rows="18" spellcheck="false"></textarea>
        @if (jsonError(); as je) { <div class="v-error">{{ je }}</div> }
        <div class="v-actions"><button type="button" class="v-btn primary" (click)="saveSettings()">Save as new version</button></div>
      </section>

      <section class="v-panel" id="tokens">
        <h3>API tokens</h3>
        <p class="v-small v-muted">For scripts, the MCP server and external agents. The secret is shown once.</p>
        @if (created(); as t) {
          <div class="v-notice">Copy this token now, it is not shown again:<br /><code>{{ t.token }}</code></div>
        }
        <table class="v-table">
          <thead><tr><th>Name</th><th>Prefix</th><th>Scopes</th><th>Expires</th><th>Last used</th><th></th></tr></thead>
          <tbody>
            @for (t of tokens(); track t.id) {
              <tr [class.revoked]="t.revoked_at"><td>{{ t.name }}</td><td><code>{{ t.prefix }}</code></td><td class="v-small">{{ t.scopes.join(', ') }}</td><td>{{ t.expires_at?.slice(0, 10) ?? 'never' }}</td><td>{{ t.last_used_at?.slice(0, 10) ?? '–' }}</td>
                <td class="num">@if (!t.revoked_at) { <button type="button" class="v-btn quiet small danger" (click)="revoke(t)">revoke</button> } @else { <span class="v-tag">revoked</span> }</td></tr>
            } @empty { <tr><td colspan="6" class="v-muted">No tokens yet.</td></tr> }
          </tbody>
        </table>
        <form class="add" (ngSubmit)="createToken()">
          <div class="v-form-row">
            <label class="v-field"><span>Name</span><input name="tn" [(ngModel)]="tokenName" placeholder="Claude Code on laptop" required /></label>
            <label class="v-field"><span>Expires</span><input name="te" type="date" [(ngModel)]="tokenExpires" /></label>
          </div>
          <fieldset class="scopes"><legend class="v-small v-muted">Scopes</legend>
            @for (s of scopes; track s) { <label><input type="checkbox" [name]="s" [ngModel]="tokenScopes.has(s)" (ngModelChange)="toggleScope(s, $event)" /> {{ s }}</label> }
          </fieldset>
          <button type="submit" class="v-btn primary" [disabled]="!tokenName.trim() || tokenScopes.size === 0">Create token</button>
        </form>
      </section>

      <section class="v-panel">
        <h3>System</h3>
        @if (health(); as h) {
          <dl class="sys"><div><dt>Version</dt><dd>{{ h.version }}</dd></div>@for (c of checks(h); track c[0]) { <div><dt>{{ c[0] }}</dt><dd>{{ c[1] }}</dd></div> }
            @if (h.backup_age_hours != null) { <div><dt>Last backup</dt><dd>{{ h.backup_age_hours }} h ago</dd></div> }</dl>
        } @else { <p class="v-muted">API health unavailable.</p> }
      </section>
    </div>
  `,
  styles: `
    .settings { display: grid; gap: 1.25rem; }
    .add { margin-top: 0.75rem; display: grid; gap: 0.75rem; align-items: end; }
    .json { width: 100%; font-family: ui-monospace, 'Cascadia Mono', Consolas, monospace; font-size: var(--v-fs-s); padding: 0.6rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); margin: 0.5rem 0; }
    .scopes { border: 1px solid var(--v-line); border-radius: var(--v-radius); padding: 0.5rem 0.75rem; display: flex; flex-wrap: wrap; gap: 0.5rem 1rem; }
    .revoked td { opacity: 0.5; }
    .sys { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: 0.5rem; } dt { font-size: var(--v-fs-xs); color: var(--v-ink-3); } dd { margin: 0; }
    code { background: var(--v-surface-2); padding: 0.1rem 0.3rem; border-radius: 3px; word-break: break-all; }
  `,
})
export class SettingsPage {
  private readonly api = inject(ApiClient);
  private readonly http = inject(HttpClient);
  readonly auth = inject(AuthService);
  readonly passkeys = signal<Passkey[]>([]);
  readonly bands = signal<TargetBand[]>([]);
  readonly settings = signal<TenantSettingsVersion | null>(null);
  readonly tokens = signal<ApiToken[]>([]);
  readonly created = signal<ApiTokenCreated | null>(null);
  readonly health = signal<Health | null>(null);
  readonly error = signal<string | null>(null);
  readonly jsonError = signal<string | null>(null);
  readonly scopes = SCOPES;
  private schema: SchemaLike | null = null;
  settingsJson = '';
  passkeyName = '';
  tokenName = '';
  tokenExpires = '';
  tokenScopes = new Set<string>(['read']);

  constructor() {
    const fail = (e: unknown) => this.error.set(describeError(e));
    this.api.passkeys().subscribe({ next: (p) => this.passkeys.set(p), error: fail });
    this.api.targetBands().subscribe({ next: (b) => this.bands.set(b), error: fail });
    this.api.settings().subscribe({ next: (s) => { this.settings.set(s); this.settingsJson = JSON.stringify(s.data, null, 2); }, error: fail });
    this.api.tokens().subscribe({ next: (t) => this.tokens.set(t), error: fail });
    this.api.health().subscribe({ next: (h) => this.health.set(h), error: () => this.health.set(null) });
    this.http.get<SchemaLike>('/schemas/tenant-settings.schema.json').subscribe({ next: (s) => (this.schema = s), error: () => (this.schema = null) });
  }

  band(b: { min: number; opt_min: number; opt_max: number; max: number }): string {
    return `${b.min} / ${b.opt_min}–${b.opt_max} / ${b.max}`;
  }
  checks(h: Health): [string, string][] {
    return Object.entries(h.checks ?? {});
  }

  async addPasskey(): Promise<void> {
    try {
      await this.auth.registerPasskey(this.passkeyName.trim());
      this.passkeyName = '';
      this.api.passkeys().subscribe({ next: (p) => this.passkeys.set(p) });
    } catch (e) {
      this.error.set(describeError(e));
    }
  }
  removePasskey(p: Passkey): void {
    if (!window.confirm(`Remove passkey “${p.name}”?`)) return;
    this.api.deletePasskey(p.id).subscribe({ next: () => this.passkeys.update((l) => l.filter((x) => x.id !== p.id)), error: (e: unknown) => this.error.set(describeError(e)) });
  }

  /** Light client-side check against the schema's top level before the server validates fully. */
  validateSettings(text: string): Record<string, unknown> | null {
    let data: unknown;
    try {
      data = JSON.parse(text);
    } catch {
      this.jsonError.set('Not valid JSON.');
      return null;
    }
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      this.jsonError.set('Settings must be a JSON object.');
      return null;
    }
    const obj = data as Record<string, unknown>;
    if (this.schema) {
      const missing = (this.schema.required ?? []).filter((k) => !(k in obj));
      const unknown = this.schema.properties ? Object.keys(obj).filter((k) => !(k in this.schema!.properties!)) : [];
      if (missing.length || unknown.length) {
        this.jsonError.set([missing.length ? `missing: ${missing.join(', ')}` : '', unknown.length ? `unknown: ${unknown.join(', ')}` : ''].filter(Boolean).join(' · '));
        return null;
      }
    }
    this.jsonError.set(null);
    return obj;
  }

  saveSettings(): void {
    const data = this.validateSettings(this.settingsJson);
    if (!data) return;
    this.api.putSettings(data).subscribe({ next: (s) => this.settings.set(s), error: (e: unknown) => this.error.set(describeError(e)) });
  }

  toggleScope(s: string, on: boolean): void {
    if (on) this.tokenScopes.add(s);
    else this.tokenScopes.delete(s);
  }
  createToken(): void {
    this.api.createToken({ name: this.tokenName.trim(), scopes: [...this.tokenScopes], expires_at: this.tokenExpires || null }).subscribe({
      next: (t) => {
        this.created.set(t);
        this.tokens.update((l) => [t, ...l]);
        this.tokenName = '';
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }
  revoke(t: ApiToken): void {
    this.api.revokeToken(t.id).subscribe({ next: () => this.tokens.update((l) => l.map((x) => (x.id === t.id ? { ...x, revoked_at: new Date().toISOString() } : x))), error: (e: unknown) => this.error.set(describeError(e)) });
  }
}
