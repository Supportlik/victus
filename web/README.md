# Victus web app

Angular 22 (standalone components, signals, Vitest) front end for the Victus API. UI language is English;
no personal data lives in this tree — fixtures use the placeholder tenant `alice`.

## Commands

```bash
npm ci                                  # install (Node 24 LTS or 26)
npm start                               # dev server on :4200, proxies /api and /mcp to :8000 (proxy.conf.json)
npm test -- --watch=false               # Vitest (jsdom); setup in src/test-setup.ts
npm run build -- --configuration production
npm outdated                            # TypeScript and vitest stay inside Angular's supported ranges
```

## Structure

```
src/app/
├─ api/            models.ts (hand-written, mirrors docs/API.md), api-client.ts (one method per endpoint)
├─ core/auth/      AuthService (passkeys via @simplewebauthn/browser), authGuard, authInterceptor (CSRF, 401 → /login)
├─ core/problem.ts RFC 9457 error → one sentence
├─ shared/         band-gauge (target strip), macro-line, status-tag, product-search (300 ms debounce), format pipes, markdown pipe
├─ features/
│  ├─ auth/        login-page (passkey, recovery code)
│  ├─ days/        days-page (ledger), day-view (meals, gauges, thread panel), day-thread
│  ├─ drafts/      drafts-page, draft-approval (corrections → POST /drafts/{date}/approve)
│  ├─ products/    products-page, product-detail (+portions), product-form, review-list (unlinked items)
│  ├─ recipes/     recipes-page, recipe-detail (cook a batch)
│  ├─ weight/      weight-page (ECharts, manual entry)
│  ├─ reports/     reports-page + report-blocks/report-block (one branch per block type)
│  ├─ captures/    captures-page (upload, "Process now", run polling)
│  └─ settings/    settings-page (passkeys, target bands, tenant settings JSON, API tokens, health)
└─ app.*           shell: navigation rail (desktop) / bottom bar (phone), health footer, passkey nudge
```

Design tokens live in `src/styles.scss` (`--v-*`): one typeface (IBM Plex Sans, bundled), paper-like surfaces,
colour only where it carries meaning (band zones, drafts). Charts use the shared palette in
`features/reports/report-blocks/palette.ts` and load ECharts lazily.

## API client generation (planned)

`src/app/api/` is the only place that knows URLs and payload shapes. When the backend publishes
`/api/v1/openapi.json`, replace it with a generated client (`@hey-api/openapi-ts`) and keep the folder name
so the features do not change.

## Tests

Test IDs follow `docs/TESTPLAN.md` (`T-WEB-001` …) and appear as comments at the top of each spec.
