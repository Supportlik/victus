"""T-OPS-002/003: CLI surface — version flag and the Stage 3 command groups."""

from typer.testing import CliRunner

from victus import __version__
from victus.cli.main import app

# Plain, wide output: CI terminals otherwise get Rich colours and 80-column wrapping,
# which splits option names across lines.
runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"})

HELP_TARGETS = (
    ["agent", "run", "--help"],
    ["agent", "runs", "--help"],
    ["agent", "unlock", "--help"],
    ["worker", "--help"],
    ["mcp", "--help"],
)


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"victus {__version__}"


def test_stage3_commands_expose_help() -> None:
    for args in HELP_TARGETS:
        result = runner.invoke(app, args)
        assert result.exit_code == 0, (args, result.output)
        assert "--tenant" in result.output or args[0] == "worker"


def test_agent_run_signature() -> None:
    result = runner.invoke(app, ["agent", "run", "--help"])
    for flag in ("--tenant", "--mode", "--captures", "--from", "--to"):
        assert flag in result.output


def test_worker_once_flag_documented() -> None:
    result = runner.invoke(app, ["worker", "--help"])
    assert "--once" in result.output


def test_mcp_requires_tenant() -> None:
    result = runner.invoke(app, ["mcp"])
    assert result.exit_code != 0
    assert "tenant" in result.output.lower()
