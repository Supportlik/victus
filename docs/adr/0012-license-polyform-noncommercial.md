# ADR 0012 — PolyForm Noncommercial, not MIT

**Status:** accepted · **Date:** 2026-09-09

## Context

Victus started under MIT, chosen before anyone had thought about what happens if it turns out to be
worth something. MIT lets anyone take the code, close it, host it for money and sell it, with no
obligation beyond keeping a copyright line. That is the opposite of the intent: the author wants
the software freely available to people who run it for themselves, and wants to be the only party
that sells it, whether as software or as a hosted service he plans to offer later.

Four kinds of licence were considered.

| Option | Why it was not chosen |
|---|---|
| MIT or Apache-2.0 | Permit exactly what is to be prevented: closed forks and paid hosting by others |
| AGPL-3.0 | Permits commercial use and paid hosting, only forcing the source open. Real open source, but it does not reserve selling to the author |
| FSL, BUSL-1.1 | Ban competition, but every version turns permissive after two to four years. The restriction has to hold indefinitely |
| Elastic License 2.0 | Bans hosting as a service but permits other commercial use, and does not clearly cover selling the software itself |

## Decision

The project is licensed under **PolyForm Noncommercial 1.0.0**.

- Every noncommercial purpose is granted: private and household use, study, hobby projects, and use
  by charities, schools, public research, health, safety and environmental organisations regardless
  of their funding.
- Commercial use is not granted: selling the software or a derivative, and running it as a paid or
  hosted service for other people, need a separate licence from the copyright holder.
- The copyright holder is not bound by his own licence and may license the same code commercially,
  which is what keeps a paid hosted version possible.
- `CONTRIBUTING.md` carries a contributor agreement: contributors keep their copyright and grant the
  maintainer the right to license their contribution commercially as well.

The identifier `LicenseRef-PolyForm-Noncommercial-1.0.0` is used in the package metadata and the
image labels, because SPDX has no short id for PolyForm licences.

## Consequences

- **This is not open source**, and the README says so. The Open Source Definition forbids
  restricting fields of endeavour, which is precisely what this licence does. Linux distributions
  and some package indexes will not carry it, and companies with policies against non-OSI licences
  will not adopt it. That is the accepted price.
- **The MIT past cannot be revoked.** Every commit published before this change stays available
  under MIT to anyone who already has it. At the time of the switch the repository had no forks and
  no stars and was one day old, so the practical exposure is nil.
- **Dependencies are unaffected.** Every Python and web dependency is permissive, apart from the
  PostgreSQL driver under LGPL, which permits both this licence and a commercial one and is only
  needed for PostgreSQL. Nothing is passed on under stricter terms than its authors chose.
- **A contribution without the agreement cannot be merged**, because it would leave part of the
  codebase impossible to license commercially. This is the reason the agreement exists before the
  first outside pull request rather than after it.
- **Liability is disclaimed as far as the law allows**, which in Germany does not cover intent,
  gross negligence, or injury to life and health. A paid hosted version will need its own terms and
  its own answer to data protection law, since a food diary carries health data.
