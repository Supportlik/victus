# Contributing to Victus

Bug reports, questions and patches are welcome. This file says what happens to the rights in
code you send, because that has to be settled before the first outside line of code arrives, not
after.

## The short version

You keep the copyright in what you write. By opening a pull request you grant the maintainer a
licence to use your contribution and to sublicense it, including commercially, alongside
[PolyForm Noncommercial](LICENSE). Nothing you send is taken from you; the maintainer is simply
allowed to license the project as a whole, your part included.

## Why it is needed

Victus is published under PolyForm Noncommercial, which grants everyone noncommercial use and
keeps commercial use with the copyright holder. That arrangement only works while one party can
license the whole codebase. Without an agreement like this one, an outside contribution stays
under its author's exclusive control, and the project can no longer be licensed commercially as
a whole. Asking each past contributor for permission years later is how projects get stuck.

## The agreement

By submitting a contribution you confirm that:

1. **It is yours to give.** You wrote it, or you have the right to submit it. If your employer
   holds rights in your work, you have their permission.
2. **You keep your copyright.** This is a licence, not an assignment.
3. **You grant the maintainer** a perpetual, worldwide, irrevocable, royalty-free licence to
   use, reproduce, modify, distribute and sublicense your contribution, under PolyForm
   Noncommercial and under other terms, commercial ones included.
4. **You grant the same for any patents** you control that your contribution would otherwise
   infringe.
5. **You accept the disclaimer.** Your contribution is offered as is, without warranty, as far
   as the law allows.

No signature or form is needed. Saying so in the pull request, or simply opening one after
reading this, is enough.

## Versioning

Victus follows [Semantic Versioning](https://semver.org/). The version lives in exactly one
place, `src/victus/__init__.py`, and `tests/test_version.py` fails if the package metadata drifts
from it.

**What the number covers.** These are the public surfaces; a change that forces someone to adapt
is breaking:

- the REST API under `/api/v1` and the JSON schemas in `schemas/`,
- the MCP tools: their names, their inputs and the shape of what they return,
- the CLI: command names, options and exit codes,
- configuration: `victus.yaml` keys and `VICTUS_*` environment variables,
- the database: a migration that cannot be applied to an existing database, or that loses data.

The web app's markup, the internal module layout and anything under `tests/` are not public.
Changing a component's CSS class is not a breaking change; changing what `day_get` returns is.

Documentation is not a public surface, but it follows the same table: a document that did not
exist is an addition (MINOR), a document that said something wrong is a fix (PATCH). Reshooting
the pictures in `docs/media/` because the interface moved on is a fix — nothing was added.

**Which part to raise.**

| Part | When | Examples |
|---|---|---|
| **MAJOR** | A public surface changes in a way that breaks an existing caller, or a migration is not reversible without loss | Removing an MCP tool or one of its fields, renaming a config key, `/api/v1` behaviour a client depended on, dropping a column that held data |
| **MINOR** | Something is added, and everything that worked still works | A new MCP tool, a new endpoint, a new report block, a new optional field, a new language, a new setting with a default that keeps today's behaviour |
| **PATCH** | A defect is fixed and nothing new is offered | Wrong arithmetic, a wrong unit, an untranslated string, a layout fault, a value that was resolved incorrectly — including when the fix changes what the software *does*, because doing the wrong thing was never the contract |

Two rules that settle most arguments:

1. **A default that changes is a fix, not a feature** — as long as the old value stays accepted.
   A new day now starting as a rest day is PATCH: the API still takes any training type, and a day
   with none was a defect.
2. **When in doubt, take the higher part.** A release that turns out to break someone is worse than
   a version number that was cautious.

**Every release, in order.** Nothing here is optional, and it is the same list for a patch as for
a major:

1. `ruff check .`, `ruff format --check .`, `mypy src`, `pytest -q`, `npm test`,
   `scripts/check_translations.py --strict`, `scripts/privacy_check.py` — all green.
2. Run the suite against PostgreSQL as well, not only SQLite. Dialect-specific migration faults are
   invisible on SQLite and stop every PostgreSQL deployment.
3. The affected areas opened in a browser and looked at (see [the test plan](docs/TESTPLAN.md)).
4. `CHANGELOG.md`: the entries move from `[Unreleased]` into a new `## [x.y.z] - YYYY-MM-DD`
   heading, under Added / Changed / Fixed. An entry says what was wrong and what it did to the
   reader, not which files moved.
5. `__version__` raised in `src/victus/__init__.py`.
6. One commit for the release, then an annotated, signed tag `vX.Y.Z` whose message says what the
   release is for. The tag is what publishes: pushing it builds the tagged images and the GitHub
   release from the changelog.
7. Deploy, then check the running version (`victus version`) and the migration head against what
   was tagged.

**Issues carry their part.** When an issue is picked up, its fix is labelled with the part it will
raise, so a release can be assembled from labels instead of by reading diffs. An issue that would
break a public surface says so in its body — that is what decides whether it waits for a major.

**Before 1.0** the project used `0.1.0.dev0` and no tags. From 1.0.0 on, every deployed state has a
tag, and a deployment that is not on a tag is a debugging session, not a release.

## What makes a contribution easy to accept

- **One concern per pull request.** A fix and a refactor in one branch take three times as long
  to review.
- **A test that fails before and passes after.** `docs/TESTPLAN.md` names every case and its id;
  add yours there.
- **The gate green.** `uv run ruff check . && uv run ruff format --check . && uv run mypy src &&
  uv run pytest` and, for web changes, `cd web && npm test && npm run build`.
- **English throughout**, in code, comments, commits and documentation.
- **No personal data.** `uv run python scripts/privacy_check.py` runs in CI and fails on it.
  Examples use `victus.example.com` and the tenant `alice`.
- **Say why in the commit message**, not what. The diff already says what.

## What will be turned down

- Anything that stores nutrient values on a line item. They are computed from the consumable, so
  storing them would make yesterday's numbers change when a product is corrected.
- Anything that lets the agent approve its own draft. A person decides what counts.
- Dependencies under a copyleft licence, which would force terms on users that this project's
  own licence does not.
