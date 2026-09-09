import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { AuthService } from '../../core/auth/auth.service';
import { I18nService } from '../../core/i18n.service';
import { PrefsService } from '../../core/prefs.service';
import { describeError } from '../../core/problem';
import { Logo } from '../../shared/logo';

/**
 * Sign-in: a passkey and nothing else. Recovery stays behind a disclosure so the
 * normal path is one button.
 */
@Component({
  selector: 'v-login-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, Logo],
  template: `
    <div class="wrap">
      <section class="pitch">
        <div class="mark"><v-logo [size]="56" /><span class="word">Victus</span></div>
        <p class="tag">{{ i18n.t('Your food log, on your own server.') }}</p>
        <ul class="points">
          <li><span aria-hidden="true">🎙</span> {{ i18n.t('Say or photograph what you ate') }}</li>
          <li><span aria-hidden="true">✎</span> {{ i18n.t('The agent drafts, you accept') }}</li>
          <li><span aria-hidden="true">▥</span> {{ i18n.t('Weight, TDEE and target bands in one check-up') }}</li>
        </ul>
      </section>

      <section class="card">
        <h1>{{ i18n.t('Sign in') }}</h1>
        <p class="v-small v-muted">{{ i18n.t('With the passkey on this device. There is no password.') }}</p>

        @if (error(); as e) { <div class="v-error" role="alert">{{ e }}</div> }

        <button type="button" class="v-btn primary big" (click)="signIn()" [disabled]="busy()">
          <span aria-hidden="true">🔑</span> {{ busy() ? i18n.t('Waiting for your passkey…') : i18n.t('Sign in with passkey') }}
        </button>

        <details class="recovery" [open]="showRecovery()">
          <summary (click)="showRecovery.set(!showRecovery())">{{ i18n.t('Lost your passkey?') }}</summary>
          <p class="v-small v-muted">
            {{ i18n.t('Enter your e-mail and recovery code. You get a short session that only lets you register a new passkey; afterwards sign in with that passkey.') }}
          </p>
          <form (ngSubmit)="recover()" class="rec-form">
            <label class="v-field"><span>{{ i18n.t('E-mail') }}</span><input name="email" type="email" [(ngModel)]="email" required autocomplete="username" /></label>
            <label class="v-field"><span>{{ i18n.t('Recovery code') }}</span><input name="code" [(ngModel)]="code" required autocomplete="one-time-code" /></label>
            <button type="submit" class="v-btn" [disabled]="busy() || !email || !code">{{ i18n.t('Use recovery code') }}</button>
          </form>
        </details>

        <p class="v-small v-muted hint">{{ i18n.t('Keep two passkeys, on two devices. You can add one under Settings.') }}</p>
      </section>
    </div>
  `,
  styles: `
    .wrap {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(20rem, 26rem);
      gap: 3rem;
      align-items: center;
      width: 100%;
      max-width: 64rem;
      margin: 0 auto;
      padding: 2rem 1.5rem;
    }
    .pitch { display: grid; grid-template-columns: minmax(0, 1fr); gap: 1rem; }
    .mark { display: flex; align-items: center; gap: 0.75rem; }
    .word { font-size: 2.5rem; font-weight: 600; letter-spacing: -0.01em; }
    .tag { font-size: var(--v-fs-l); color: var(--v-ink-2); margin: 0; max-width: 26ch; }
    .points { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.6rem; color: var(--v-ink-2); font-size: var(--v-fs-s); }
    .points li { display: flex; gap: 0.6rem; align-items: center; }
    .points span { width: 1.4rem; text-align: center; color: var(--v-primary); }

    .card {
      display: grid; grid-template-columns: minmax(0, 1fr);
      gap: 0.75rem;
      padding: 1.75rem;
      background: var(--v-surface);
      border: 1px solid var(--v-line);
      border-radius: var(--v-radius-l);
      box-shadow: 0 8px 30px light-dark(rgb(0 0 0 / 0.07), rgb(0 0 0 / 0.5));
    }
    .card h1 { font-size: var(--v-fs-xl); }
    .big { justify-content: center; padding: 0.7rem 1rem; font-size: var(--v-fs-m); }
    .recovery summary { cursor: pointer; color: var(--v-ink-2); font-size: var(--v-fs-s); }
    .rec-form { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.6rem; margin-top: 0.6rem; }
    .hint { margin: 0; }

    @media (max-width: 52rem) {
      .wrap { grid-template-columns: 1fr; gap: 1.5rem; padding: 1.5rem 1rem 2.5rem; }
      .word { font-size: 2rem; }
      .points { display: none; }
      .card { padding: 1.25rem; }
    }
  `,
})
export class LoginPage {
  readonly i18n = inject(I18nService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly prefs = inject(PrefsService);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly showRecovery = signal(false);
  email = '';
  code = '';

  async signIn(): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      await this.auth.loginWithPasskey();
      const back = this.route.snapshot.queryParamMap.get('returnUrl');
      await this.router.navigateByUrl(back && !back.startsWith('/login') ? back : this.prefs.landingUrl());
    } catch (e) {
      this.error.set(describeError(e));
    } finally {
      this.busy.set(false);
    }
  }

  async recover(): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      await this.auth.recover(this.email.trim(), this.code.trim());
      await this.router.navigate(['/settings'], { fragment: 'passkeys' });
    } catch (e) {
      this.error.set(describeError(e));
    } finally {
      this.busy.set(false);
    }
  }
}
