"""Where report definitions come from: built-ins shipped with the package, plus a
hook for tenant-defined reports (database, Stage 2 API)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from importlib import resources

from victus.reports.definition import ReportDefinition, load_definition

BuiltinLoader = Callable[[], Iterable[ReportDefinition]]
TenantLoader = Callable[[], Iterable[ReportDefinition]]


def load_builtins() -> list[ReportDefinition]:
    package = resources.files("victus.reports.builtin")
    defs: list[ReportDefinition] = []
    for entry in sorted(package.iterdir(), key=lambda p: p.name):
        if entry.name.endswith((".yaml", ".yml")):
            defs.append(load_definition(entry.read_text(encoding="utf-8")))
    return defs


class ReportRegistry:
    """Built-ins first; a tenant loader may add definitions but not shadow built-ins."""

    def __init__(self, tenant_loader: TenantLoader | None = None) -> None:
        self._builtins = {d.name: d for d in load_builtins()}
        self._tenant_loader = tenant_loader

    @property
    def builtin_names(self) -> frozenset[str]:
        return frozenset(self._builtins)

    def list(self) -> list[ReportDefinition]:
        out = list(self._builtins.values())
        if self._tenant_loader is not None:
            out.extend(d for d in self._tenant_loader() if d.name not in self._builtins)
        return out

    def get(self, name: str) -> ReportDefinition:
        if name in self._builtins:
            return self._builtins[name]
        if self._tenant_loader is not None:
            for d in self._tenant_loader():
                if d.name == name:
                    return d
        raise KeyError(f"unknown report {name!r}")

    def is_builtin(self, name: str) -> bool:
        return name in self._builtins
