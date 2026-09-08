"""Report engine: declarative report definitions rendered to JSON or Markdown (Stage 2).

Public surface:

* :func:`victus.reports.definition.load_definition` — YAML → :class:`ReportDefinition`
* :class:`victus.reports.engine.ReportEngine` — ``render(definition, period, today)``
* :class:`victus.reports.registry.ReportRegistry` — built-ins + tenant hook
* :mod:`victus.reports.render.json` / :mod:`victus.reports.render.markdown`
* :class:`victus.application.ports.report_data.ReportDataSource` — the data port
"""
