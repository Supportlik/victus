"""Fixtures for the backup tests: a file-based SQLite database with two tenants,
products, days, line items, a weigh-in, an API token, a passkey and one attachment
on disk. File-based because ``VACUUM INTO`` needs a real database file."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine

from victus.application.tenant_context import TenantContext
from victus.infrastructure.db import orm
from victus.infrastructure.db.engine import make_engine, make_session_factory
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork
from victus.infrastructure.migrations import runner

pytestmark = pytest.mark.service


@dataclass
class Seeded:
    engine: Engine
    db_path: Path
    storage: Path
    backups: Path
    alice: TenantContext
    bob: TenantContext
    alice_day: date


def _seed_tenant(
    factory: object, ctx: TenantContext, storage: Path, *, name: str, with_attachment: bool
) -> None:
    from sqlalchemy.orm import Session, sessionmaker

    assert isinstance(factory, sessionmaker)
    sf: sessionmaker[Session] = factory
    with SqlAlchemyUnitOfWork(sf, ctx) as u:
        user = u.users.add(
            orm.User(
                tenant_id=ctx.tenant_id,
                display_name=name,
                email=f"{name.lower()}@example.com",
                role="owner",
            )
        )
        u.users.add_passkey(
            orm.PasskeyCredential(
                user_id=user.id,
                credential_id=hashlib.sha256(name.encode()).digest(),
                public_key=b"\x01\x02\x03" + name.encode(),
                sign_count=3,
                transports=["internal"],
                name="phone",
            )
        )
        u.users.add_token(
            orm.ApiToken(
                tenant_id=ctx.tenant_id,
                user_id=user.id,
                name="ci",
                prefix="vct_abcd",
                token_hash=hashlib.sha256(f"tok-{name}".encode()).hexdigest(),
                scopes=["read"],
            )
        )
        cat = u.products.add_category(orm.Category(tenant_id=ctx.tenant_id, name="Dairy"))
        skyr = u.products.add_product(
            "Skyr natural",
            category_id=cat.id,
            kcal=63.0,
            protein=11.0,
            carbs=4.0,
            fat=0.2,
            fiber=0.0,
            salt=0.1,
        )
        u.products.add_portion(
            orm.Portion(
                product_id=skyr.id,
                unit_code="tub",
                label="tub",
                amount=400.0,
                amount_unit="g",
                is_default=True,
            )
        )
        oats = u.products.add_product(
            "Oats", kcal=372.0, protein=13.5, carbs=58.7, fat=7.0, fiber=10.0, salt=0.0
        )
        day = u.day_logs.add(
            orm.DayLog(
                tenant_id=ctx.tenant_id,
                date=date(2026, 1, 5),
                reliable=True,
                status="closed",
                created_by_kind="user",
            )
        )
        meal = u.day_logs.add_meal(orm.Meal(day_log_id=day.id, position=1, name="Breakfast"))
        for pos, (cid, grams) in enumerate([(skyr.id, 400.0), (oats.id, 60.0)], start=1):
            u.day_logs.add_line_item(
                orm.LineItem(
                    meal_id=meal.id,
                    position=pos,
                    consumable_id=cid,
                    unit_code="g",
                    amount=grams,
                    base_amount=grams,
                    base_unit="g",
                    origin="manual",
                )
            )
        u.weights.add(
            orm.WeightEntry(
                tenant_id=ctx.tenant_id,
                measured_at=datetime(2026, 1, 5, 6, 30, tzinfo=UTC),
                kg=91.2,
                source="manual",
            )
        )
        u.target_bands.add(
            orm.TargetBand(
                tenant_id=ctx.tenant_id,
                name="Rest day",
                training_type="rest",
                valid_from=date(2026, 1, 1),
                protein_min=105,
                protein_opt_min=150,
                protein_opt_max=185,
                protein_target=165,
                protein_max=200,
                carbs_min=120,
                carbs_opt_min=155,
                carbs_opt_max=200,
                carbs_target=180,
                carbs_max=230,
                fat_min=45,
                fat_opt_min=55,
                fat_opt_max=70,
                fat_target=58,
                fat_max=75,
                fiber_min=25,
                fiber_opt_min=32,
                fiber_opt_max=38,
                fiber_target=35,
                fiber_max=50,
                salt_min=4,
                salt_opt_min=6,
                salt_opt_max=8,
                salt_target=7,
                salt_max=15,
            )
        )
        u.settings.add_version({"kcal_per_kg": 7716.17}, date(2026, 1, 1), "test")
        if with_attachment:
            payload = f"photo of {name}".encode()
            sha = hashlib.sha256(payload).hexdigest()
            key = f"{ctx.tenant_id}/2026/01/{sha}"
            (storage / key).parent.mkdir(parents=True, exist_ok=True)
            (storage / key).write_bytes(payload)
            att = u.captures.add_attachment(
                orm.Attachment(
                    tenant_id=ctx.tenant_id,
                    sha256=sha,
                    mime="image/jpeg",
                    size=len(payload),
                    storage_key=key,
                    original_name="photo.jpg",
                )
            )
            u.captures.add(
                orm.Capture(
                    tenant_id=ctx.tenant_id,
                    user_id=user.id,
                    kind="image",
                    target_date=date(2026, 1, 5),
                    status="new",
                    attachment_id=att.id,
                    content_hash=sha,
                )
            )
        u.audit.record("seed", "tenant", ctx.tenant_id, {"name": name})
        u.commit()


@pytest.fixture
def seeded(tmp_path: Path) -> Iterator[Seeded]:
    db_path = tmp_path / "victus.db"
    storage = tmp_path / "blobs"
    backups = tmp_path / "backups"
    storage.mkdir()
    engine = make_engine(f"sqlite:///{db_path.as_posix()}")
    runner.upgrade(engine=engine)
    factory = make_session_factory(engine)
    with factory() as s:
        a = orm.Tenant(slug="alice", name="Alice")
        b = orm.Tenant(slug="bob", name="Bob")
        s.add_all([a, b])
        s.commit()
        alice = TenantContext(tenant_id=a.id, user_id=None)
        bob = TenantContext(tenant_id=b.id, user_id=None)
    _seed_tenant(factory, alice, storage, name="Alice", with_attachment=True)
    _seed_tenant(factory, bob, storage, name="Bob", with_attachment=False)
    yield Seeded(engine, db_path, storage, backups, alice, bob, date(2026, 1, 5))
    engine.dispose()


@pytest.fixture
def fresh_engine(tmp_path: Path) -> Iterator[Engine]:
    eng = make_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    yield eng
    eng.dispose()
