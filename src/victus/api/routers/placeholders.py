"""Routes owned by later stages answer 501 with problem details instead of 404,
so the web app can tell "not built yet" from "wrong URL"."""

from __future__ import annotations

from fastapi import APIRouter, Request

from victus.application.errors import NotImplementedYet

router = APIRouter(tags=["planned"])

_PLANNED = {
    "captures": "Stage 3",
    "agent": "Stage 3",
    "backup": "Stage 1 (backup module)",
}


for prefix, stage in _PLANNED.items():

    def _make(prefix: str = prefix, stage: str = stage) -> None:
        @router.api_route(
            f"/{prefix}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False
        )
        @router.api_route(
            f"/{prefix}/{{rest:path}}",
            methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            include_in_schema=False,
        )
        async def _planned(request: Request, rest: str = "") -> None:
            raise NotImplementedYet(f"/{prefix} is planned for {stage}")

    _make()
