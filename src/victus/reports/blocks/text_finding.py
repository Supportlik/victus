from __future__ import annotations

from victus.reports.blocks._meta import meta_for
from victus.reports.context import ReportContext
from victus.reports.definition import TextFindingDef
from victus.reports.results import TextFindingResult


def compute_text_finding(block: TextFindingDef, ctx: ReportContext) -> TextFindingResult:
    markdown: str | None = None
    for source in block.source.split("|"):
        markdown = ctx.source.latest_finding(source)
        if markdown:
            break
    if markdown and block.max_items:
        # Keep at most ``max_items`` bullet points; prose passes through untouched.
        bullets = [ln for ln in markdown.splitlines() if ln.lstrip().startswith(("-", "*"))]
        if len(bullets) > block.max_items:
            keep = set(bullets[: block.max_items])
            markdown = "\n".join(
                ln
                for ln in markdown.splitlines()
                if not ln.lstrip().startswith(("-", "*")) or ln in keep
            )
    return TextFindingResult(meta=meta_for(block), source=block.source, markdown=markdown)
