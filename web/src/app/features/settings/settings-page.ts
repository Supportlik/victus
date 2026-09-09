import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { LANDINGS, PrefsService } from '../../core/prefs.service';
import { ThemeService } from '../../core/theme.service';
import { TenantSettingsForm } from './settings-form';
import { ApiClient, ApiToken, ApiTokenCreated, Health, Passkey, Rule, TargetBand, TenantSettingsVersion } from '../../api';
import { AuthService } from '../../core/auth/auth.service';
import { FormatService } from '../../core/format.service';
import { I18nService } from '../../core/i18n.service';
import { NoticeService } from '../../core/notice.service';
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
      <header class="v-page-head"><div><h2>{{ i18n.t('Settings') }}</h2><p class="sub">{{ auth.me()?.tenant?.name }} · {{ i18n.t('signed in as {name}', { name: auth.me()?.user?.display_name ?? '' }) }}</p></div></header>
      @if (error(); as e) { <div class="v-error">{{ e }}</div> }

      <section class="v-panel" id="appearance">
        <h3>{{ i18n.t('Appearance') }}</h3>
        <p class="v-small v-muted">{{ i18n.t('Stored in this browser only.') }}</p>
        <div class="v-form-row">
          <label class="v-field"><span>{{ i18n.t('After sign-in open') }}</span>
            <select name="landing" [ngModel]="prefs.landing()" (ngModelChange)="prefs.landing.set($event)">
              @for (l of landings; track l.id) { <option [value]="l.id">{{ i18n.t(l.label) }}</option> }
            </select>
          </label>
          <label class="v-field"><span>{{ i18n.t('Light / dark') }}</span>
            <select name="scheme" [ngModel]="theme.scheme()" (ngModelChange)="theme.scheme.set($event)">
              <option value="system">{{ i18n.t('Follow the device') }}</option><option value="light">{{ i18n.t('Light') }}</option><option value="dark">{{ i18n.t('Dark') }}</option>
            </select>
          </label>
          <div class="v-field"><span>{{ i18n.t('Palette') }}</span>
            <div class="palettes">
              @for (p of theme.palettes; track p.id) {
                <button type="button" class="swatch" [class.active]="theme.palette() === p.id" (click)="theme.palette.set(p.id)" [attr.aria-pressed]="theme.palette() === p.id">
                  <span class="dot" [style.background]="p.swatch"></span>{{ i18n.t(p.label) }}
                </button>
              }
            </div>
          </div>
        </div>
      </section>

      <section class="v-panel" id="passkeys">
        <h3>{{ i18n.t('Passkeys') }}</h3>
        <p class="v-small v-muted">{{ i18n.t('Keep at least two, on different devices.') }}</p>
        <div class="v-scroll-x">
          <table class="v-table"><tbody>
            @for (p of passkeys(); track p.id) {
              <tr><td>{{ p.name }}</td><td class="v-muted">{{ i18n.t('added {date}', { date: format.day(p.created_at) }) }}@if (p.last_used_at) { · {{ i18n.t('last used {date}', { date: format.day(p.last_used_at) }) }}}</td>
              <td class="num"><button type="button" class="v-btn quiet small danger" (click)="removePasskey(p)" [disabled]="passkeys().length < 2">{{ i18n.t('remove') }}</button></td></tr>
            } @empty { <tr><td class="v-muted">{{ i18n.t('No passkeys listed.') }}</td></tr> }
          </tbody></table>
        </div>
        <form class="v-form-row add" (ngSubmit)="addPasskey()">
          <label class="v-field"><span>{{ i18n.t('Name for this device') }}</span><input name="pk" [(ngModel)]="passkeyName" [placeholder]="i18n.t('Phone, Laptop, YubiKey')" required /></label>
          <button type="submit" class="v-btn primary" [disabled]="!passkeyName.trim()">{{ i18n.t('Add passkey') }}</button>
        </form>
      </section>

      <section class="v-panel" id="rules">
        <h3>{{ i18n.t('Your rules for the agent') }}</h3>
        <p class="v-small v-muted">{{ i18n.t('In your words: when something applies, and what to do then. The agent gets these with every run, and you can add them in the chat too.') }}</p>
        <div class="v-scroll-x">
          <table class="v-table">
            <thead><tr><th>{{ i18n.t('When') }}</th><th>{{ i18n.t('Then') }}</th><th>{{ i18n.t('Scope') }}</th><th></th></tr></thead>
            <tbody>
              @for (r of rules(); track r.name) {
                <tr [class.off]="!r.enabled">
                  <td>{{ r.when }}</td><td>{{ r.then }}</td><td class="v-muted">{{ i18n.t(r.scope) }}</td>
                  <td class="num">
                    <button type="button" class="v-btn quiet small" (click)="toggleRule(r)">{{ i18n.t(r.enabled ? 'disable' : 'enable') }}</button>
                    <button type="button" class="v-btn quiet small danger" (click)="removeRule(r)">{{ i18n.t('remove') }}</button>
                  </td>
                </tr>
              } @empty { <tr><td colspan="4" class="v-muted">{{ i18n.t('No rules yet.') }}</td></tr> }
            </tbody>
          </table>
        </div>
        <form class="v-form-row add" (ngSubmit)="addRule()">
          <label class="v-field"><span>{{ i18n.t('When') }}</span><input name="rw" [(ngModel)]="ruleWhen" [placeholder]="i18n.t('bread rolls from the bakery')" required /></label>
          <label class="v-field"><span>{{ i18n.t('Then') }}</span><input name="rt" [(ngModel)]="ruleThen" [placeholder]="thenExample()" required /></label>
          <label class="v-field"><span>{{ i18n.t('Scope') }}</span>
            <select name="rs" [(ngModel)]="ruleScope"><option value="all">{{ i18n.t('all') }}</option><option value="products">{{ i18n.t('products') }}</option><option value="days">{{ i18n.t('days') }}</option><option value="reports">{{ i18n.t('reports') }}</option></select>
          </label>
          <button type="submit" class="v-btn primary" [disabled]="!ruleWhen.trim() || !ruleThen.trim()">{{ i18n.t('Add rule') }}</button>
        </form>
      </section>

      <section class="v-panel">
        <h3>{{ i18n.t('Target bands') }}</h3>
        <p class="v-small v-muted">{{ i18n.t('One profile per training type; salt has no other source than this table. Edit them under “Tenant settings” below.') }}</p>
        <div class="v-scroll-x"><table class="v-table">
          <thead><tr><th>{{ i18n.t('Profile') }}</th><th>{{ i18n.t('Training') }}</th><th>{{ i18n.t('Valid') }}</th><th>{{ i18n.t('Protein') }}</th><th>{{ i18n.t('Carbs') }}</th><th>{{ i18n.t('Fat') }}</th><th>{{ i18n.t('Fiber') }}</th><th>{{ i18n.t('Salt') }}</th></tr></thead>
          <tbody>
            @for (b of bands(); track b.id) {
              <tr><td>{{ b.name }}</td><td>{{ i18n.t((b.training_type ?? 'any').replace('_', ' ')) }}</td><td>{{ b.valid_from }} – {{ b.valid_until ?? i18n.t('open') }}</td>
                <td>{{ band(b.protein) }}</td><td>{{ band(b.carbs) }}</td><td>{{ band(b.fat) }}</td><td>{{ band(b.fiber) }}</td><td>{{ band(b.salt) }}</td></tr>
            } @empty { <tr><td colspan="8" class="v-muted">{{ i18n.t('No target bands defined yet — edit the settings below.') }}</td></tr> }
          </tbody>
        </table></div>
      </section>

      <section class="v-panel">
        <h3>{{ i18n.t('Tenant settings') }} <span class="v-small v-muted">@if (settings(); as s) { {{ i18n.t('version {n} since {date}', { n: s.version, date: s.valid_from }) }} }</span></h3>
        <p class="v-small v-muted">{{ i18n.t('Goal, calculation windows, calorie corridor, body data and transcription vocabulary. Saving creates a new version; older versions stay readable.') }}</p>
        @if (settings(); as s) {
          <v-tenant-settings-form [data]="s.data" (save)="saveSettingsData($event)" />
        } @else { <p class="v-muted v-small">{{ i18n.t('Loading…') }}</p> }
        <details class="advanced">
          <summary>{{ i18n.t('Advanced: edit the document as JSON') }}</summary>
          <textarea class="json" [(ngModel)]="settingsJson" name="settings" rows="18" spellcheck="false"></textarea>
          @if (jsonError(); as je) { <div class="v-error">{{ je }}</div> }
          <div class="v-actions"><button type="button" class="v-btn" (click)="saveSettings()">{{ i18n.t('Save JSON as new version') }}</button></div>
        </details>
      </section>

      <section class="v-panel" id="tokens">
        <h3>{{ i18n.t('API tokens') }}</h3>
        <p class="v-small v-muted">{{ i18n.t('For scripts, the MCP server and external agents. The secret is shown once.') }}</p>
        @if (created(); as t) {
          <div class="v-notice">{{ i18n.t('Copy this token now, it is not shown again:') }}<br /><code>{{ t.token }}</code></div>
        }
        <div class="v-scroll-x">
          <table class="v-table">
            <thead><tr><th>{{ i18n.t('Name') }}</th><th>{{ i18n.t('Prefix') }}</th><th>{{ i18n.t('Scopes') }}</th><th>{{ i18n.t('Expires') }}</th><th>{{ i18n.t('Last used') }}</th><th></th></tr></thead>
            <tbody>
              @for (t of tokens(); track t.id) {
                <tr [class.revoked]="t.revoked_at"><td>{{ t.name }}</td><td><code>{{ t.prefix }}</code></td><td class="v-small">{{ t.scopes.join(', ') }}</td><td>{{ t.expires_at ? format.day(t.expires_at) : i18n.t('never') }}</td><td>{{ t.last_used_at ? format.day(t.last_used_at) : '–' }}</td>
                  <td class="num">@if (!t.revoked_at) { <button type="button" class="v-btn quiet small danger" (click)="revoke(t)">{{ i18n.t('revoke') }}</button> } @else { <span class="v-tag">{{ i18n.t('revoked') }}</span> }</td></tr>
              } @empty { <tr><td colspan="6" class="v-muted">{{ i18n.t('No tokens yet.') }}</td></tr> }
            </tbody>
          </table>
        </div>
        <form class="add" (ngSubmit)="createToken()">
          <div class="v-form-row">
            <label class="v-field"><span>{{ i18n.t('Name') }}</span><input name="tn" [(ngModel)]="tokenName" [placeholder]="i18n.t('Claude Code on laptop')" required /></label>
            <label class="v-field"><span>{{ i18n.t('Expires') }}</span><input name="te" type="date" [(ngModel)]="tokenExpires" /></label>
          </div>
          <fieldset class="scopes"><legend class="v-small v-muted">{{ i18n.t('Scopes') }}</legend>
            @for (s of scopes; track s) { <label><input type="checkbox" [name]="s" [ngModel]="tokenScopes.has(s)" (ngModelChange)="toggleScope(s, $event)" /> {{ s }}</label> }
          </fieldset>
          <button type="submit" class="v-btn primary" [disabled]="!tokenName.trim() || tokenScopes.size === 0">{{ i18n.t('Create token') }}</button>
        </form>
      </section>

      <section class="v-panel">
        <h3>{{ i18n.t('System') }}</h3>
        @if (health(); as h) {
          <dl class="sys"><div><dt>{{ i18n.t('Version') }}</dt><dd>{{ h.version }}</dd></div>@for (c of checks(h); track c[0]) { <div><dt>{{ i18n.t(c[0]) }}</dt><dd>{{ i18n.t(c[1]) }}</dd></div> }
            @if (h.backup_age_hours != null) { <div><dt>{{ i18n.t('Last backup') }}</dt><dd>{{ i18n.t('{n} h ago', { n: h.backup_age_hours }) }}</dd></div> }</dl>
        } @else { <p class="v-muted">{{ i18n.t('API health unavailable.') }}</p> }
      </section>
    </div>
  `,
  styles: `
    .settings { display: grid; grid-template-columns: minmax(0, 1fr); gap: 1.25rem; }
    .add { margin-top: 0.75rem; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.75rem; align-items: end; }
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
  private readonly notices = inject(NoticeService);
  readonly i18n = inject(I18nService);
  readonly format = inject(FormatService);
  readonly landings = LANDINGS;
  /** The apostrophe cannot survive an Angular attribute binding, so this example is built here. */
  readonly thenExample = computed(() =>
    this.i18n.t("take the values from the bakery's own site, they beat any database"),
  );
  readonly passkeys = signal<Passkey[]>([]);
  readonly bands = signal<TargetBand[]>([]);
  readonly rules = signal<Rule[]>([]);
  readonly settings = signal<TenantSettingsVersion | null>(null);
  readonly tokens = signal<ApiToken[]>([]);
  readonly created = signal<ApiTokenCreated | null>(null);
  readonly health = signal<Health | null>(null);
  /** Only what stays wrong while the page is open; anything momentary is a notice. */
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
      error: (e: unknown) => this.failed(e),
    });
  }

  toggleRule(r: Rule): void {
    this.api.putRule({ ...r, enabled: !r.enabled }).subscribe({
      next: () => this.afterRuleChange(),
      error: (e: unknown) => this.failed(e),
    });
  }

  removeRule(r: Rule): void {
    this.api.deleteRule(r.name).subscribe({
      next: () => this.afterRuleChange(),
      error: (e: unknown) => this.failed(e),
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
      this.failed(e);
    }
  }
  removePasskey(p: Passkey): void {
    if (!window.confirm(this.i18n.t('Remove passkey “{name}”?', { name: p.name ?? '' }))) return;
    this.api.deletePasskey(p.id).subscribe({ next: () => this.passkeys.update((l) => l.filter((x) => x.id !== p.id)), error: (e: unknown) => this.failed(e) });
  }

  /** Light client-side check against the schema's top level before the server validates fully. */
  validateSettings(text: string): Record<string, unknown> | null {
    let data: unknown;
    try {
      data = JSON.parse(text);
    } catch {
      this.jsonError.set(this.i18n.t('Not valid JSON.'));
      return null;
    }
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      this.jsonError.set(this.i18n.t('Settings must be a JSON object.'));
      return null;
    }
    const obj = data as Record<string, unknown>;
    if (this.schema) {
      const missing = (this.schema.required ?? []).filter((k) => !(k in obj));
      const unknown = this.schema.properties ? Object.keys(obj).filter((k) => !(k in this.schema!.properties!)) : [];
      if (missing.length || unknown.length) {
        this.jsonError.set([
          missing.length ? this.i18n.t('missing: {keys}', { keys: missing.join(', ') }) : '',
          unknown.length ? this.i18n.t('unknown: {keys}', { keys: unknown.join(', ') }) : '',
        ].filter(Boolean).join(' · '));
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
    this.api.putSettings(data).subscribe({
      next: (s) => {
        this.settings.set(s);
        this.settingsJson = JSON.stringify(s.data, null, 2);
        // the save sits at the end of a long form; the confirmation has to find the reader
        this.notices.ok(this.i18n.t('Saved as version {version}.', { version: s.version }));
      },
      error: (e: unknown) => this.failed(e),
    });
  }

  /** A failed action is an event, not a state of the page, so it floats instead. */
  private failed(e: unknown): void {
    this.notices.error(describeError(e));
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
      error: (e: unknown) => this.failed(e),
    });
  }
  revoke(t: ApiToken): void {
    this.api.revokeToken(t.id).subscribe({ next: () => this.tokens.update((l) => l.map((x) => (x.id === t.id ? { ...x, revoked_at: new Date().toISOString() } : x))), error: (e: unknown) => this.failed(e) });
  }
}
