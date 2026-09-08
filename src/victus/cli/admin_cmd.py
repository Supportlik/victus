"""Administration commands: tenants, users, tokens, passkey recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer

from victus.application.errors import ApplicationError
from victus.application.tenant_context import ALL_SCOPES, TenantContext
from victus.application.use_cases import auth as auth_uc
from victus.application.use_cases import tenants as tenant_uc
from victus.cli._db import uow_factory_from_config

tenant_app = typer.Typer(help="Manage tenants.", no_args_is_help=True)
user_app = typer.Typer(help="Manage users of a tenant.", no_args_is_help=True)
token_app = typer.Typer(help="Manage API tokens.", no_args_is_help=True)
passkey_app = typer.Typer(help="Passkey recovery.", no_args_is_help=True)


def _ctx_for(slug: str, user_email: str | None = None) -> TenantContext:
    _, session_factory = uow_factory_from_config()
    from victus.infrastructure.db import orm  # local: CLI resolves the slug itself

    with session_factory() as s:
        from sqlalchemy import select

        tenant = s.scalar(select(orm.Tenant).where(orm.Tenant.slug == slug))
        if tenant is None:
            raise typer.BadParameter(f"tenant '{slug}' not found")
        user_id = None
        if user_email:
            user = s.scalar(
                select(orm.User).where(
                    orm.User.tenant_id == tenant.id, orm.User.email == user_email.strip().lower()
                )
            )
            if user is None:
                raise typer.BadParameter(f"user '{user_email}' not found in tenant '{slug}'")
            user_id = user.id
        return TenantContext(tenant_id=tenant.id, user_id=user_id, scopes=ALL_SCOPES)


@tenant_app.command("create")
def tenant_create(
    slug: Annotated[str, typer.Argument(help="URL-safe identifier, e.g. alice")],
    name: Annotated[str, typer.Option(help="Display name.")] = "",
) -> None:
    """Create a tenant."""
    factory, _ = uow_factory_from_config()
    try:
        view = tenant_uc.CreateTenant(factory, TenantContext(tenant_id="-")).execute(
            slug, name or slug
        )
    except ApplicationError as exc:
        raise typer.BadParameter(exc.detail) from exc
    typer.echo(f"tenant created: {view.slug} ({view.id})")


@tenant_app.command("list")
def tenant_list() -> None:
    """List tenants."""
    _, session_factory = uow_factory_from_config()
    from sqlalchemy import select

    from victus.infrastructure.db import orm

    with session_factory() as s:
        for t in s.scalars(select(orm.Tenant).order_by(orm.Tenant.slug)):
            typer.echo(f"{t.slug}\t{t.name}\t{t.id}")


@user_app.command("create")
def user_create(
    tenant: Annotated[str, typer.Option(help="Tenant slug.")],
    email: Annotated[str, typer.Option(help="E-mail (login name).")],
    name: Annotated[str, typer.Option(help="Display name.")],
    role: Annotated[str, typer.Option(help="owner | member")] = "owner",
) -> None:
    """Create a user and print the one-time recovery code."""
    factory, _ = uow_factory_from_config()
    try:
        created = tenant_uc.CreateUser(factory, _ctx_for(tenant)).execute(name, email, role)
    except ApplicationError as exc:
        raise typer.BadParameter(exc.detail) from exc
    typer.echo(f"user created: {created.user.email} ({created.user.id})")
    typer.echo("")
    typer.echo("Recovery code (shown once — store it in your password manager):")
    typer.echo(f"  {created.recovery_code}")
    typer.echo("")
    typer.echo("Sign in with 'Use recovery code' in the web app, then register a passkey.")


@passkey_app.command("reset")
def passkey_reset(
    tenant: Annotated[str, typer.Option(help="Tenant slug.")],
    email: Annotated[str, typer.Option(help="User e-mail.")],
) -> None:
    """Issue a new recovery code (the old one stops working)."""
    factory, _ = uow_factory_from_config()
    try:
        result = tenant_uc.ResetRecoveryCode(factory, _ctx_for(tenant)).execute(email)
    except ApplicationError as exc:
        raise typer.BadParameter(exc.detail) from exc
    typer.echo(f"new recovery code for {result.user.email} (shown once):")
    typer.echo(f"  {result.recovery_code}")


@token_app.command("create")
def token_create(
    tenant: Annotated[str, typer.Option(help="Tenant slug.")],
    name: Annotated[str, typer.Option(help="Label, e.g. 'claude-code'.")],
    user: Annotated[str | None, typer.Option(help="Owner e-mail (optional).")] = None,
    scopes: Annotated[str, typer.Option(help="Comma-separated scopes.")] = "read",
    expires_days: Annotated[int, typer.Option(help="Lifetime in days (max 365).")] = 90,
) -> None:
    """Create an API token and print it once."""
    factory, _ = uow_factory_from_config()
    scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
    expires = datetime.now(UTC) + timedelta(days=expires_days)
    try:
        created = auth_uc.CreateToken(factory, _ctx_for(tenant, user)).execute(
            name, scope_list, expires
        )
    except ApplicationError as exc:
        raise typer.BadParameter(exc.detail) from exc
    scopes_txt = ", ".join(created.scopes)
    typer.echo(f"token created: {created.prefix} ({scopes_txt}), expires {created.expires_at}")
    typer.echo("Secret (shown once):")
    typer.echo(f"  {created.token}")


@token_app.command("list")
def token_list(tenant: Annotated[str, typer.Option(help="Tenant slug.")]) -> None:
    """List tokens of a tenant (prefixes only)."""
    factory, _ = uow_factory_from_config()
    for t in auth_uc.ListTokens(factory, _ctx_for(tenant)).execute():
        state = "revoked" if t.revoked_at else "active"
        typer.echo(f"{t.prefix}\t{t.name}\t{','.join(t.scopes)}\t{state}\texpires {t.expires_at}")


@token_app.command("revoke")
def token_revoke(
    tenant: Annotated[str, typer.Option(help="Tenant slug.")],
    token_id: Annotated[str, typer.Argument(help="Token id (see `token list`).")],
) -> None:
    """Revoke a token."""
    factory, _ = uow_factory_from_config()
    try:
        auth_uc.RevokeToken(factory, _ctx_for(tenant)).execute(token_id)
    except ApplicationError as exc:
        raise typer.BadParameter(exc.detail) from exc
    typer.echo("token revoked")
