// T-WEB-306..309: problem.ts turns an HTTP refusal into the one sentence a page shows, and
// tells a page whether a refusal named one of its fields.
import { HttpErrorResponse } from '@angular/common/http';
import { describeError, namesField } from './problem';

function refusal(error: unknown, status = 422): HttpErrorResponse {
  return new HttpErrorResponse({ error, status, statusText: 'Refused', url: '/api/v1/days/2026-01-05' });
}

describe('describeError', () => {
  it('T-WEB-306: a problem document yields its detail, then every field error', () => {
    const err = refusal({
      title: 'Unprocessable Content',
      detail: 'The line item was refused',
      errors: [
        { field: 'amount', message: 'must be positive' },
        { message: 'the day is closed' },
      ],
    });
    expect(describeError(err)).toBe('The line item was refused — amount: must be positive; the day is closed');
  });

  it('T-WEB-306: the title stands in for a missing detail, and field errors stand alone', () => {
    expect(describeError(refusal({ title: 'Conflict' }, 409))).toBe('Conflict');
    expect(describeError(refusal({ errors: [{ field: 'kg', message: 'is required' }] }))).toBe('kg: is required');
    expect(describeError(refusal({ detail: 'Not allowed', errors: [] }, 403))).toBe('Not allowed');
  });

  it('T-WEB-307: a problem document that says nothing falls back to the status', () => {
    expect(describeError(refusal({}, 500))).toBe('Request failed (500).');
    expect(describeError(refusal({ type: 'about:blank', status: 500 }, 500))).toBe('Request failed (500).');
  });

  it('T-WEB-307: no body at all names an unreachable API (status 0) or the status', () => {
    expect(describeError(refusal(null, 0))).toBe('The API is not reachable.');
    expect(describeError(refusal(null, 502))).toBe('Request failed (502).');
    expect(describeError(refusal('<html>Bad Gateway</html>', 502))).toBe('Request failed (502).');
  });

  it('T-WEB-308: anything that is not an HTTP error is described without a status', () => {
    expect(describeError(new Error('WebAuthn was cancelled'))).toBe('WebAuthn was cancelled');
    expect(describeError('boom')).toBe('Something went wrong.');
    expect(describeError(undefined)).toBe('Something went wrong.');
  });
});

describe('namesField', () => {
  it('T-WEB-309: true only when a field error of the problem document names the field', () => {
    const err = refusal({ detail: 'Refused', errors: [{ field: 'amount', message: 'must be positive' }, { message: 'other' }] });
    expect(namesField(err, 'amount')).toBe(true);
    expect(namesField(err, 'unit_code')).toBe(false);
  });

  it('T-WEB-309: false for a problem without errors, a missing or non-object body, or a non-HTTP error', () => {
    expect(namesField(refusal({ detail: 'Refused' }), 'amount')).toBe(false);
    expect(namesField(refusal(null, 0), 'amount')).toBe(false);
    expect(namesField(refusal('amount', 400), 'amount')).toBe(false);
    expect(namesField(new Error('amount'), 'amount')).toBe(false);
    expect(namesField(undefined, 'amount')).toBe(false);
  });
});
