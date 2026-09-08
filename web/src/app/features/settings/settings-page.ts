import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { LANDINGS, PrefsService } from '../../core/prefs.service';
import { ThemeService } from '../../core/theme.service';
import { TenantSettingsForm } from './settings-form';
import { ApiClient, ApiToken, ApiTokenCreated, Health, Passkey, Rule, TargetBand, TenantSettingsVersion } from '../../api';
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
  imports: [FormsModule, TenantSettingsForm],
  template: `
    <div class="v-page settings">
      <header class="v-page-head"><div><h2>Settings</h2><p class="sub">{{ auth.me()?.tenant?.name }} · signed in as {{ auth.me()?.user?.display_name }}</p></div></header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }

      <section class="v-panel" id="appearance">
        <h3>Appearance</h3>
        <p class="v-small v-muted">Stored in this browser only.</p>
        <div class="v-form-row">
          <label class="v-field"><span>After sign-in open</span>
            <select name="landing" [ngModel]="prefs.landing()" (ngModelChange)="prefs.landing.set($event)">
              @for (l of landings; track l.id) { <option [value]="l.id">{{ l.label }}</option> }
            </select>
          </label>
          <label class="v-field"><span>Light / dark</span>
            <select name="scheme" [ngModel]="theme.scheme()" (ngModelChange)="theme.scheme.set($event)">
              <option value="system">Follow the device</option><option value="light">Light</option><option value="dark">Dark</option>
            </select>
          </label>
          <div class="v-field"><span>Palette</span>
            <div class="palettes">
              @for (p of theme.palettes; track p.id) {
                <button type="button" class="swatch" [class.active]="theme.palette() === p.id" (click)="theme.palette.set(p.id)" [attr.aria-pressed]="theme.palette() === p.id">
                  <span class="dot" [style.background]="p.swatch"></span>{{ p.label }}
                </button>
              }
            </div>
          </div>
        </div>
      </section>

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

      <section class="v-panel" id="rules">
        <h3>Your rules for the agent</h3>
        <p class="v-small v-muted">In your words: when something applies, and what to do then. The agent gets these with every run, and you can add them in the chat too.</p>
        <table class="v-table">
          <thead><tr><th>When</th><th>Then</th><th>Scope</th><th></th></tr></thead>
          <tbody>
            @for (r of rules(); track r.name) {
              <tr [class.off]="!r.enabled">
                <td>{{ r.when }}</td><td>{{ r.then }}</td><td class="v-muted">{{ r.scope }}</td>
                <td class="num">
                  <button type="button" class="v-btn quiet small" (click)="toggleRule(r)">{{ r.enabled ? 'disable' : 'enable' }}</button>
                  <button type="button" class="v-btn quiet small danger" (click)="removeRule(r)">remove</button>
                </td>
              </tr>
            } @empty { <tr><td colspan="4" class="v-muted">No rules yet.</td></tr> }
          </tbody>
        </table>
        <form class="v-form-row add" (ngSubmit)="addRule()">
          <label class="v-field"><span>When</span><input name="rw" [(ngModel)]="ruleWhen" placeholder="bread rolls from the bakery" required /></label>
          <label class="v-field"><span>Then</span><input name="rt" [(ngModel)]="ruleThen" placeholder="take the values from the bakery's own site, they beat any database" required /></label>
          <label class="v-field"><span>Scope</span>
            <select name="rs" [(ngModel)]="ruleScope"><option value="all">all</option><option value="products">products</option><option value="days">days</option><option value="reports">reports</option></select>
          </label>
          <button type="submit" class="v-btn primary" [disabled]="!ruleWhen.trim() || !ruleThen.trim()">Add rule</button>
        </form>
      </section>

      <section class="v-panel">
        <h3>Target bands</h3>
        <p class="v-small v-muted">One profile per training type; salt has no other source than this table. Edit them under “Tenant settings” below.</p>
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
        <p class="v-small v-muted">Goal, calculation windows, calorie corridor, body data and transcription vocabulary. Saving creates a new version; older versions stay readable.</p>
        @if (settings(); as s) {
          <v-tenant-settings-form [data]="s.data" (save)="saveSettingsData($event)" />
        } @else { <p class="v-muted v-small">Loading…</p> }
        <details class="advanced">
          <summary>Advanced: edit the document as JSON</summary>
          <textarea class="json" [(ngModel)]="settingsJson" name="settings" rows="18" spellcheck="false"></textarea>
          @if (jsonError(); as je) { <div class="v-error">{{ je }}</div> }
          <div class="v-actions"><button type="button" class="v-btn" (click)="saveSettings()">Save JSON as new version</button></div>
        </details>
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
    tr.off td { opacity: 0.55; }
    .palettes { display: flex; gap: 0.4rem; flex-wrap: wrap; }
    .swatch { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.35rem 0.7rem; border: 1px solid var(--v-line-strong); border-radius: 999px; background: var(--v-surface); cursor: pointer; font-size: var(--v-fs-s); }
    .swatch.active { border-color: var(--v-primary); box-shadow: 0 0 0 1px var(--v-primary) inset; }
    .dot { width: 0.8rem; height: 0.8rem; border-radius: 50%; display: inline-block; }
    .advanced { margin-top: 1rem; } .advanced summary { cursor: pointer; color: var(--v-ink-2); font-size: var(--v-fs-s); }
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
  readonly theme = inject(ThemeService);
  readonly prefs = inject(PrefsService);
  readonly landings = LANDINGS;
  readonly passkeys = signal<Passkey[]>([]);
  readonly bands = signal<TargetBand[]>([]);
  readonly rules = signal<Rule[]>([]);
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
  ruleWhen = '';
  ruleThen = '';
  ruleScope: Rule['scope'] = 'all';
  tokenName = '';
  tokenExpires = '';
  tokenScopes = new Set<string>(['read']);

  constructor() {
    const fail = (e: unknown) => this.error.set(describeError(e));
    this.api.passkeys().subscribe({ next: (p) => this.passkeys.set(p), error: fail });
    this.api.targetBands().subscribe({ next: (b) => this.bands.set(b), error: fail });
    this.loadRules();
    this.api.settings().subscribe({ next: (s) => { this.settings.set(s); this.settingsJson = JSON.stringify(s.data, null, 2); }, error: fail });
    this.api.tokens().subscribe({ next: (t) => this.tokens.set(t), error: fail });
    this.api.health().subscribe({ next: (h) => this.health.set(h), error: () => this.health.set(null) });
    this.http.get<SchemaLike>('/schemas/tenant-settings.schema.json').subscribe({ next: (s) => (this.schema = s), error: () => (this.schema = null) });
  }

  loadRules(): void {
    this.api.rules().subscribe({ next: (r) => this.rules.set(r), error: () => undefined });
  }

  /** A rule change writes a new settings version, so the document is reloaded with it. */
  private afterRuleChange(): void {
    this.loadRules();
    this.api.settings().subscribe({
      next: (s) => {
        this.settings.set(s);
        this.settingsJson = JSON.stringify(s.data, null, 2);
      },
      error: () => undefined,
    });
  }

  addRule(): void {
    if (!this.ruleWhen.trim() || !this.ruleThen.trim()) return;
    this.api.putRule({ when: this.ruleWhen.trim(), then: this.ruleThen.trim(), scope: this.ruleScope }).subscribe({
      next: () => {
        this.ruleWhen = '';
        this.ruleThen = '';
        this.afterRuleChange();
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  toggleRule(r: Rule): void {
    this.api.putRule({ ...r, enabled: !r.enabled }).subscribe({
      next: () => this.afterRuleChange(),
      error: (e: unknown) => this.error.set(describeError(e)),
    });
  }

  removeRule(r: Rule): void {
    this.api.deleteRule(r.name).subscribe({
      next: () => this.afterRuleChange(),
      error: (e: unknown) => this.error.set(describeError(e)),
    });
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
    this.saveSettingsData(data);
  }

  saveSettingsData(data: Record<string, unknown>): void {
    this.error.set(null);
    this.api.putSettings(data).subscribe({
      next: (s) => {
        this.settings.set(s);
        this.settingsJson = JSON.stringify(s.data, null, 2);
      },
      error: (e: unknown) => this.error.set(describeError(e)),
    });
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
