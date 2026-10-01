"""T-OPS-200 … T-OPS-204: administration commands (tenant, user, passkey, token)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from tests.cli_support import CliEnv, cli, configure_cli_env
from victus.cli.main import app
from victus.infrastructure.db import orm
from victus.infrastructure.db.engine import make_engine, make_session_factory

pytestmark = pytest.mark.service


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CliEnv:
    return configure_cli_env(monkeypatch, tmp_path)


def _tenant_with_owner(email: str = "alice@example.com") -> str:
    assert cli.invoke(app, ["tenant", "create", "alice", "--name", "Alice"]).exit_code == 0
    result = cli.invoke(
        app, ["user", "create", "--tenant", "alice", "--email", email, "--name", "Alice"]
    )
    assert result.exit_code == 0, result.output
    return result.stdout


def _tokens(env: CliEnv) -> list[orm.ApiToken]:
    engine = make_engine(env.db_url)
    try:
        with make_session_factory(engine)() as s:
            return list(s.scalars(select(orm.ApiToken).order_by(orm.ApiToken.name)))
    finally:
        engine.dispose()


def test_tenant_create_and_list(env: CliEnv) -> None:
    """T-OPS-200: `tenant create` prints slug and id; `tenant list` shows it; bad input exits 2."""
    created = cli.invoke(app, ["tenant", "create", "alice", "--name", "Alice"])
    assert created.exit_code == 0, created.output
    assert created.stdout.startswith("tenant created: alice (")
    # Without --name the slug is the display name.
    assert cli.invoke(app, ["tenant", "create", "bob"]).exit_code == 0

    listed = cli.invoke(app, ["tenant", "list"])
    assert listed.exit_code == 0
    lines = listed.stdout.strip().splitlines()
    assert [line.split("\t")[:2] for line in lines] == [["alice", "Alice"], ["bob", "bob"]]

    duplicate = cli.invoke(app, ["tenant", "create", "alice"])
    assert duplicate.exit_code == 2
    assert "exists" in duplicate.output
    invalid = cli.invoke(app, ["tenant", "create", "Not A Slug"])
    assert invalid.exit_code == 2
    assert "slug" in invalid.output


def test_user_create_prints_recovery_code_once(env: CliEnv) -> None:
    """T-OPS-201: `user create` prints the recovery code; unknown tenant or bad e-mail exit 2."""
    out = _tenant_with_owner()
    assert "user created: alice@example.com (" in out
    assert "Recovery code (shown once" in out
    code_line = out.splitlines()[3]
    assert code_line.startswith("  ") and len(code_line.strip()) >= 8

    unknown = cli.invoke(
        app, ["user", "create", "--tenant", "nobody", "--email", "x@example.com", "--name", "X"]
    )
    assert unknown.exit_code == 2
    assert "tenant 'nobody' not found" in unknown.output

    bad_mail = cli.invoke(
        app, ["user", "create", "--tenant", "alice", "--email", "not-a-mail", "--name", "X"]
    )
    assert bad_mail.exit_code == 2
    assert "e-mail" in bad_mail.output


def test_passkey_reset_issues_new_code(env: CliEnv) -> None:
    """T-OPS-202: `passkey reset` prints a new recovery code; an unknown user exits 2."""
    first = _tenant_with_owner().splitlines()[3].strip()
    reset = cli.invoke(
        app, ["passkey", "reset", "--tenant", "alice", "--email", "alice@example.com"]
    )
    assert reset.exit_code == 0, reset.output
    lines = reset.stdout.splitlines()
    assert lines[0] == "new recovery code for alice@example.com (shown once):"
    assert lines[1].strip() and lines[1].strip() != first

    missing = cli.invoke(app, ["passkey", "reset", "--tenant", "alice", "--email", "x@example.com"])
    assert missing.exit_code == 2
    assert "not found" in missing.output


def test_token_create_validates_owner_and_scopes(env: CliEnv) -> None:
    """T-OPS-203: `token create` prints the secret once; unknown owner or scope exits 2."""
    _tenant_with_owner()
    created = cli.invoke(
        app,
        [
            "token",
            "create",
            "--tenant",
            "alice",
            "--name",
            "claude-code",
            "--user",
            " Alice@Example.com ",
            "--scopes",
            "read, write,",
            "--expires-days",
            "30",
        ],
    )
    assert created.exit_code == 0, created.output
    lines = created.stdout.splitlines()
    assert lines[0].startswith("token created: ") and "(read, write)" in lines[0]
    assert lines[1] == "Secret (shown once):"
    [token] = _tokens(env)
    assert token.user_id is not None and lines[2].strip().startswith(token.prefix)

    no_user = cli.invoke(
        app,
        ["token", "create", "--tenant", "alice", "--name", "x", "--user", "bob@example.com"],
    )
    assert no_user.exit_code == 2
    assert "user 'bob@example.com' not found in tenant 'alice'" in no_user.output

    bad_scope = cli.invoke(
        app, ["token", "create", "--tenant", "alice", "--name", "x", "--scopes", "root"]
    )
    assert bad_scope.exit_code == 2
    assert "unknown scopes: root" in bad_scope.output
    assert len(_tokens(env)) == 1


def test_token_list_and_revoke_by_prefix(env: CliEnv) -> None:
    """T-OPS-204: `token list` shows prefix and state; `revoke` takes prefix or id; an
    unknown one exits 2."""
    _tenant_with_owner()
    for name in ("ci", "phone"):
        assert (
            cli.invoke(app, ["token", "create", "--tenant", "alice", "--name", name]).exit_code == 0
        )
    ci, phone = _tokens(env)

    revoked = cli.invoke(app, ["token", "revoke", "--tenant", "alice", ci.prefix])
    assert revoked.exit_code == 0, revoked.output
    assert revoked.stdout.strip() == "token revoked"
    by_id = cli.invoke(app, ["token", "revoke", "--tenant", "alice", phone.id])
    assert by_id.exit_code == 0

    listed = cli.invoke(app, ["token", "list", "--tenant", "alice"])
    assert listed.exit_code == 0
    rows = [line.split("\t") for line in listed.stdout.strip().splitlines()]
    assert sorted((r[0], r[1], r[2], r[3]) for r in rows) == sorted(
        [(ci.prefix, "ci", "read", "revoked"), (phone.prefix, "phone", "read", "revoked")]
    )

    unknown = cli.invoke(app, ["token", "revoke", "--tenant", "alice", "vct_nope"])
    assert unknown.exit_code == 2
    assert "token not found" in unknown.output
