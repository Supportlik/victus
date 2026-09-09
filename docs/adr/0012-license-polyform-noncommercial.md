# ADR 0012 — PolyForm Noncommercial as the project licence

**Status:** accepted · **Date:** 2026-09-09

## Context

Victus is published so that people can read it, run it and change it. It is also meant to earn
money one day, as a paid hosted version the author operates himself. Those two goals put three
requirements on the licence:

1. Anyone may run it for themselves or their household, with no obligation and no fee.
2. Selling the software, or running it as a paid service for other people, stays with the
   copyright holder.
3. The restriction holds indefinitely, not for a few years.

Four families of licence were weighed against those requirements.

| Option | Verdict |
|---|---|
| MIT, BSD, Apache-2.0 | Permissive: they allow closed forks and paid hosting by anyone. They fail requirement 2 outright |
| AGPL-3.0 | Copyleft with a network clause. Real open source, and it forces a hoster to publish their source, but it still permits anyone to charge for hosting. Fails requirement 2 |
| FSL, BUSL-1.1 | Ban competing use, but every version turns permissive after two to four years. Fails requirement 3 |
| Elastic License 2.0 | Bans offering the software as a hosted service, but permits other commercial use and does not clearly cover selling the software itself. Only partly meets requirement 2 |

## Decision

The project is licensed under **PolyForm Noncommercial 1.0.0**.

- Every noncommercial purpose is granted: private and household use, study, hobby projects, and
  use by charities, schools, public research, health, safety and environmental organisations
  regardless of their funding.
- Commercial use is not granted. Selling the software or a derivative, and running it as a paid
  or hosted service for other people, need a separate licence from the copyright holder.
- The copyright holder is not bound by his own licence and may license the same code
  commercially, which is what keeps a paid hosted version possible.
- `CONTRIBUTING.md` carries a contributor agreement: contributors keep their copyright and grant
  the maintainer the right to license their contribution commercially as well.

The identifier `LicenseRef-PolyForm-Noncommercial-1.0.0` is used in the package metadata and the
container image labels, because SPDX has no short id for PolyForm licences.

## Consequences

- **This is not open source**, and the README says so plainly. The Open Source Definition forbids
  restricting fields of endeavour, which is precisely what this licence does. Linux distributions
  and some package indexes will not carry it, and companies with policies against non-OSI licences
  will not adopt it. That is the accepted price of requirement 2.
- **Dependencies are unaffected.** Every Python and web dependency is permissive, apart from the
  PostgreSQL driver under LGPL, which permits both this licence and a commercial one and is only
  needed when running on PostgreSQL. Nothing is passed on under stricter terms than its own
  authors chose.
- **A contribution without the agreement cannot be merged**, because it would leave part of the
  codebase impossible to license commercially. This is why the agreement exists before the first
  outside pull request rather than after it.
- **Liability is disclaimed as far as the law allows**, which under German law does not cover
  intent, gross negligence, or injury to life and health. A paid hosted version will need its own
  terms of service and its own answer to data protection law, since a food diary carries health
  data.
