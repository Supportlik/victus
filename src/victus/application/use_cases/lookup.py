"""Look a barcode up in a public product database (#78, ``agent.lookup.ean``).

The answer is a suggestion, not a product: the caller files it with ``product_create``,
which a person approves. Nothing is written here.
"""

from __future__ import annotations

import re

from victus.application.errors import (
    Conflict,
    ExternalServiceError,
    NotFound,
    ValidationFailed,
)
from victus.application.ports.product_lookup import (
    LookedUpProduct,
    ProductLookupError,
    ProductLookupPort,
)
from victus.application.tenant_context import SCOPE_READ, TenantContext
from victus.application.use_cases._base import UowFactory, UseCase

_EAN = re.compile(r"^\d{8,14}$")


class LookupDisabled(Conflict):
    title = "Lookup switched off"


class LookupProductByEan(UseCase):
    def __init__(
        self, uow_factory: UowFactory, ctx: TenantContext, lookup: ProductLookupPort | None
    ) -> None:
        super().__init__(uow_factory, ctx)
        self.lookup = lookup

    def execute(self, ean: str) -> LookedUpProduct:
        self.ctx.require(SCOPE_READ)
        if self.lookup is None:
            raise LookupDisabled(
                "barcode lookup is switched off on this server (agent.lookup.ean); say in "
                "open_questions that the barcode could be looked up instead of estimating"
            )
        code = re.sub(r"[\s-]", "", ean)
        if not _EAN.match(code):
            raise ValidationFailed(f"'{ean}' is not a barcode: expected 8 to 14 digits")
        try:
            found = self.lookup.by_ean(code)
        except ProductLookupError as exc:
            raise ExternalServiceError(f"barcode lookup failed: {exc}") from exc
        if found is None:
            raise NotFound(f"no product with barcode {code} in the lookup database")
        return found
