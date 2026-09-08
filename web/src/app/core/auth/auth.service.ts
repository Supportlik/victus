import { computed, inject, Injectable, signal } from '@angular/core';
import { Router } from '@angular/router';
import { startAuthentication, startRegistration } from '@simplewebauthn/browser';
import type {
  PublicKeyCredentialCreationOptionsJSON,
  PublicKeyCredentialRequestOptionsJSON,
} from '@simplewebauthn/browser';
import { firstValueFrom } from 'rxjs';
import { ApiClient, Me } from '../../api';

/** The server embeds a one-time `ceremony_id` in the WebAuthn options; the client echoes it back. */
type WithCeremony<T> = T & { ceremony_id: string };

/**
 * Session state for the web app. Passkeys only: the browser performs WebAuthn ceremonies
 * against /auth/webauthn/*; the server keeps an HttpOnly session cookie.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly api = inject(ApiClient);
  private readonly router = inject(Router);

  readonly me = signal<Me | null>(null);
  readonly loaded = signal(false);
  readonly isAuthenticated = computed(() => this.me() !== null);
  readonly csrfToken = computed(() => this.me()?.csrf_token ?? null);
  /** Recovery-code login: the session may only register a passkey and log out. */
  readonly isRecoverySession = computed(() => this.me()?.recovery_session === true);
  /** Users with a single passkey are one lost phone away from a lockout. */
  readonly needsSecondPasskey = computed(() => (this.me()?.passkeys ?? 2) < 2);

  /** Loads the session once; a 401 simply means "not logged in". */
  async load(): Promise<Me | null> {
    if (this.loaded()) return this.me();
    try {
      const me = await firstValueFrom(this.api.me());
      this.me.set(me);
    } catch {
      this.me.set(null);
    } finally {
      this.loaded.set(true);
    }
    return this.me();
  }

  async loginWithPasskey(email?: string): Promise<Me> {
    const { ceremony_id, ...options } = (await firstValueFrom(
      this.api.webauthnLoginOptions(email ? { email } : {}),
    )) as WithCeremony<PublicKeyCredentialRequestOptionsJSON>;
    const assertion = await startAuthentication({ optionsJSON: options });
    const me = await firstValueFrom(this.api.webauthnLoginVerify({ ...assertion, ceremony_id }));
    this.me.set(me);
    this.loaded.set(true);
    return me;
  }

  async registerPasskey(name?: string, invitation?: string): Promise<void> {
    const { ceremony_id, ...options } = (await firstValueFrom(
      this.api.webauthnRegisterOptions({ name, invitation }),
    )) as WithCeremony<PublicKeyCredentialCreationOptionsJSON>;
    const attestation = await startRegistration({ optionsJSON: options });
    await firstValueFrom(this.api.webauthnRegisterVerify({ ...attestation, ceremony_id, name }));
    const me = this.me();
    if (me) this.me.set({ ...me, passkeys: me.passkeys + 1 });
  }

  /** Recovery code → restricted session; the caller sends the user to passkey registration. */
  async recover(email: string, code: string): Promise<Me> {
    const me = await firstValueFrom(this.api.recovery(code, email));
    this.me.set(me);
    this.loaded.set(true);
    return me;
  }

  async logout(): Promise<void> {
    try {
      await firstValueFrom(this.api.logout());
    } catch {
      // The server session may already be gone; the client side is cleared regardless.
    } finally {
      this.me.set(null);
      await this.router.navigateByUrl('/login');
    }
  }

  /** Called by the interceptor on 401 for a protected request. */
  sessionLost(): void {
    this.me.set(null);
    this.loaded.set(true);
    void this.router.navigate(['/login'], { queryParams: { returnUrl: this.router.url } });
  }
}
