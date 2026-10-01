/**
 * The scopes a token can hold, and the scope profiles offered as presets next to them.
 *
 * Both mirror the server: `SCOPES` is `ALL_SCOPES` in `application/tenant_context.py`, and each
 * preset is a profile of `application/scope_profiles.py`, documented in docs/API.md under
 * "Scope profiles". `tests/unit/tooling/test_scope_matrix.py` fails when they drift apart.
 * The in-house worker is a profile too, but it holds no token, so it is not offered here.
 */
export const SCOPES = ['read', 'write', 'approve', 'capture:read', 'capture:write', 'agent:write', 'admin'] as const;

export interface ScopePreset {
  key: string;
  /** English label; the key of its translation. */
  title: string;
  /** One line on what a token made from it is for; also a translation key. */
  intent: string;
  scopes: readonly string[];
}

export const SCOPE_PRESETS: readonly ScopePreset[] = [
  { key: 'read-only', title: 'Read-only', intent: 'Reports, days, catalogue; nothing written', scopes: ['read'] },
  {
    key: 'assistant',
    title: 'Assistant that proposes',
    intent: 'Reads everything, drafts days and files catalogue proposals; creates no fact',
    scopes: ['read', 'write', 'capture:read', 'capture:write', 'agent:write'],
  },
  { key: 'capture-uploader', title: 'Capture uploader', intent: 'Uploads photos and recordings, nothing else', scopes: ['capture:write'] },
  {
    key: 'full-delegate',
    title: 'Full delegate',
    intent: 'Can also decide: whatever it writes is a fact',
    scopes: ['read', 'write', 'approve', 'capture:read', 'capture:write', 'agent:write'],
  },
];

/** Where the profiles are explained in full. */
export const SCOPE_PROFILES_DOC = 'https://github.com/Supportlik/victus/blob/main/docs/API.md#scope-profiles';

/** The preset whose scopes are exactly the ticked ones, if any. */
export function presetFor(scopes: ReadonlySet<string>): ScopePreset | undefined {
  return SCOPE_PRESETS.find((p) => p.scopes.length === scopes.size && p.scopes.every((s) => scopes.has(s)));
}
