import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { AuthService } from '../../core/auth/auth.service';
import { describeError } from '../../core/problem';

@Component({
  selector: 'v-login-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <section class="login">
      <h1>Victus</h1>
      <p class="lead">Sign in with the passkey stored on this device. There is no password.</p>

      @if (error(); as e) {
        <div class="v-error" role="alert">{{ e }}</div>
      }

      <button type="button" class="v-btn primary big" (click)="signIn()" [disabled]="busy()">
        {{ busy() ? 'Waiting for your passkey…' : 'Sign in with passkey' }}
      </button>

      <details class="recovery" [open]="showRecovery()">
        <summary (click)="showRecovery.set(!showRecovery())">Lost your passkey?</summary>
        <p class="v-small v-muted">
          Enter your e-mail and recovery code. You get a short session that only lets you register a new passkey; afterwards sign in with that passkey.
        </p>
        <form (ngSubmit)="recover()" class="v-form-row">
          <label class="v-field"><span>E-mail</span><input name="email" type="email" [(ngModel)]="email" required autocomplete="username" /></label>
          <label class="v-field"><span>Recovery code</span><input name="code" [(ngModel)]="code" required autocomplete="one-time-code" /></label>
          <button type="submit" class="v-btn" [disabled]="busy() || !email || !code">Use recovery code</button>
        </form>
      </details>

      <p class="v-small v-muted hint">
        Tip: register at least two passkeys (phone and computer). You can add one under Settings after signing in.
      </p>
    </section>
  `,
  styles: `
    .login { width: min(26rem, 100%); display: grid; gap: 1rem; }
    h1 { font-size: var(--v-fs-xxl); }
    .lead { color: var(--v-ink-2); }
    .big { justify-content: center; padding: 0.8rem 1rem; font-size: var(--v-fs-m); }
    .recovery summary { cursor: pointer; color: var(--v-primary); }
    .recovery form { margin-top: 0.75rem; align-items: end; }
    .hint { margin: 0; }
  `,
})
export class LoginPage {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

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
      await this.router.navigateByUrl(this.route.snapshot.queryParamMap.get('returnUrl') ?? '/');
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
