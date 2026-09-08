"""T-OPS-002/003: CLI surface — version flag and honest 'not implemented' exits."""

from typer.testing import CliRunner

from victus import __version__
from victus.cli.main import NOT_IMPLEMENTED_EXIT, app

runner = CliRunner()

PLANNED = (
    ["import", "vault", "/tmp/vault"],
    ["backup", "create"],
    ["mcp"],
    ["worker"],
    ["migrate"],
)


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"victus {__version__}"


def test_planned_commands_exit_with_code_3() -> None:
    for args in PLANNED:
        result = runner.invoke(app, args)
        assert result.exit_code == NOT_IMPLEMENTED_EXIT, args
        assert "planned for Stage" in result.output
