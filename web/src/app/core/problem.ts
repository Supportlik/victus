import { HttpErrorResponse } from '@angular/common/http';

/** RFC 9457 problem details as returned by the API. */
export interface Problem {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  errors?: { field?: string; message: string }[];
}

/** Turns any HTTP error into one sentence a person can act on. */
export function describeError(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    const p = err.error as Problem | null;
    if (p && typeof p === 'object') {
      const fields = p.errors?.map((e) => (e.field ? `${e.field}: ${e.message}` : e.message)).join('; ');
      return [p.detail ?? p.title, fields].filter(Boolean).join(' — ') || `Request failed (${err.status}).`;
    }
    if (err.status === 0) return 'The API is not reachable.';
    return `Request failed (${err.status}).`;
  }
  return err instanceof Error ? err.message : 'Something went wrong.';
}
