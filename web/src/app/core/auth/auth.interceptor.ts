import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { AuthService } from './auth.service';

const AUTH_FREE = ['/auth/me', '/auth/webauthn/login', '/auth/recovery', '/health', '/version'];

/**
 * Adds the CSRF header to writes and sends the user to the login page when a protected
 * request answers 401 (session expired or revoked).
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const csrf = auth.csrfToken();
  const isWrite = !['GET', 'HEAD', 'OPTIONS'].includes(req.method);
  const request = isWrite && csrf ? req.clone({ setHeaders: { 'X-CSRF-Token': csrf } }) : req;

  return next(request).pipe(
    catchError((err: unknown) => {
      if (err instanceof HttpErrorResponse && err.status === 401 && !AUTH_FREE.some((p) => req.url.includes(p))) {
        auth.sessionLost();
      }
      return throwError(() => err);
    }),
  );
};
