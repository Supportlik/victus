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
