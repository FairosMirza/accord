# ruff: noqa: E402
"""Shared test infrastructure.

* The schema is built once per run by the real Alembic migrations, so the append-only audit
  trigger and the request reference sequence are exactly what production has.
* Every test runs inside one outer transaction that is rolled back afterwards. That is the only
  way to clean up: the audit log refuses UPDATE, DELETE and TRUNCATE.
* `org` builds a small company. Everything in it is reachable by key: org.coo, org.software,
  org.people (department), org.accra (site).
"""

import os

# The app reads its settings once, on first import, so these must be set before any app import.
os.environ.setdefault("ACCORD_DATABASE_URL", "postgresql+psycopg://accord:accord@localhost:5433/accord_test")
os.environ.setdefault("ACCORD_DEMO_MODE", "true")
os.environ.setdefault("ACCORD_COOKIE_SECURE", "false")
os.environ.setdefault("ACCORD_BASE_URL", "http://testserver")
os.environ.setdefault("ACCORD_RUN_MIGRATIONS_ON_START", "false")
os.environ.setdefault("ACCORD_STORAGE_LOCAL_PATH", "/tmp/accord-test-uploads")

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app import main, workflow
from app.audit import SYSTEM
from app.db import engine, get_db
from app.models import (
    AttachmentKind,
    Category,
    CategoryGroup,
    Department,
    EmailMessage,
    FxRate,
    Invoice,
    Notification,
    RequestStatus,
    Site,
    SpendRequest,
    User,
)
from app.permissions import can_view, visibility_clause
from app.policy import ensure_policy

PDF_QUOTE = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


# ---------------------------------------------------------------- database


@pytest.fixture(scope="session")
def database() -> Iterator[Engine]:
    """A freshly migrated test database (the schema is dropped and rebuilt on every run)."""
    name = engine.url.database or ""
    if not name.endswith("_test"):
        pytest.exit(f"Refusing to run the tests against {name!r}: the suite drops the schema, so use a *_test database.", returncode=2)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    main.run_migrations()
    yield engine
    engine.dispose()


@pytest.fixture
def db(database: Engine) -> Iterator[Session]:
    """A session inside a transaction that is always rolled back.

    Code under test may commit (the API and run_reminders do): with create_savepoint, a commit
    only releases a savepoint and the outer transaction still discards everything.
    """
    connection = database.connect()
    outer = connection.begin()
    # Same settings as app.db.SessionLocal, so the code behaves as it does in production.
    session = Session(bind=connection, join_transaction_mode="create_savepoint", autoflush=False, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


class MemoryStorage:
    """Uploads are validated by the real code, then kept in memory instead of on disk."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.files[key] = data

    def get(self, key: str) -> bytes:
        return self.files[key]


@pytest.fixture(autouse=True)
def storage(monkeypatch: pytest.MonkeyPatch) -> MemoryStorage:
    store = MemoryStorage()
    monkeypatch.setattr("app.storage.get_storage", lambda: store)
    monkeypatch.setattr("app.api.requests.get_storage", lambda: store)
    return store


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    """HTTP client for the real app, sharing the test's session (and so its transaction).

    Not used as a context manager, so the startup lifespan (migrations, seeding) doesn't run.
    """

    def same_session() -> Iterator[Session]:
        yield db

    main.app.dependency_overrides[get_db] = same_session
    yield TestClient(main.app)
    main.app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------- the test company


class Org:
    """A small company, plus shortcuts for raising requests and inspecting the results."""

    def __init__(self, db: Session):
        self.db = db
        self.users: dict[str, User] = {}

    def add(self, key: str, thing: Any) -> Any:
        self.db.add(thing)
        setattr(self, key, thing)
        return thing

    def add_user(
        self, key: str, name: str, *, department: str, site: str = "dubai", manager: str | None = None, roles: list[str] | None = None
    ) -> User:
        user = User(
            email=f"{key}@orvane.test",
            name=name,
            department=getattr(self, department),
            site=getattr(self, site),
            manager=getattr(self, manager) if manager else None,
            roles=roles or [],
        )
        self.users[key] = self.add(key, user)
        self.db.flush()
        return user

    def key_of(self, user: User) -> str:
        return next(key for key, u in self.users.items() if u.id == user.id)

    # ------------------------------------------------------------ raising requests

    def draft(self, requester: User, category: Category, amount: str | int, *, quote: bool = True, **fields: Any) -> SpendRequest:
        """An unsubmitted request, with a PDF quote attached unless quote=False."""
        data = {
            "title": f"{category.name} for {requester.name}",
            "description": "Needed for day-to-day work.",
            "supplier": "Gulf Office Trading LLC",
            "category_id": category.id,
            "amount": Decimal(str(amount)),
            **fields,
        }
        req = workflow.create_draft(self.db, requester, data)
        if quote:
            workflow.add_attachment(self.db, requester, req, "quote.pdf", PDF_QUOTE, AttachmentKind.QUOTE)
        return req

    def submit(self, requester: User, category: Category, amount: str | int, **kwargs: Any) -> SpendRequest:
        """Draft (with a quote) and submit: the request now waits for its first approver."""
        req = self.draft(requester, category, amount, **kwargs)
        return workflow.submit(self.db, requester, req, SYSTEM)

    def approve_all(self, req: SpendRequest) -> SpendRequest:
        """Everyone in the chain approves, in turn."""
        while req.status == RequestStatus.PENDING:
            workflow.approve(self.db, req.pending_step.approver, req, None, SYSTEM)
        return req

    def record_invoice(
        self,
        finance_user: User,
        req: SpendRequest,
        number: str,
        amount: str | Decimal,
        *,
        currency: str = "USD",
        override_reason: str | None = None,
        replaces: Invoice | None = None,
    ) -> Invoice:
        """An invoice dated 20 November 2026, without a file."""
        return workflow.record_invoice(
            self.db,
            finance_user,
            req,
            invoice_number=number,
            invoice_date=date(2026, 11, 20),
            amount=Decimal(amount),
            currency=currency,
            supplier=None,
            notes=None,
            override_reason=override_reason,
            file=None,
            client=SYSTEM,
            replaces_invoice_id=replaces.id if replaces else None,
        )

    # ------------------------------------------------------------ looking at the results

    def approvers(self, req: SpendRequest) -> list[str]:
        """Keys of the people in the current approval chain, in order."""
        return [self.key_of(s.approver) for s in sorted(req.current_steps, key=lambda s: s.sequence)]

    def visible_refs(self, user: User) -> set[str]:
        self.db.flush()
        return set(self.db.scalars(select(SpendRequest.ref).where(visibility_clause(self.db, user))))

    def can_see(self, user: User, req: SpendRequest) -> bool:
        self.db.flush()
        return can_view(self.db, user, req)

    def notifications_for(self, user: User, kind: str) -> list[Notification]:
        self.db.flush()
        return list(self.db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.kind == kind)))

    def emails_for(self, user: User, kind: str) -> list[EmailMessage]:
        self.db.flush()
        return list(self.db.scalars(select(EmailMessage).where(EmailMessage.to_user_id == user.id, EmailMessage.kind == kind)))


def build_org(db: Session) -> Org:
    org = Org(db)
    for key, name in [
        ("exec", "Executive Office"),
        ("ops", "Operations"),
        ("finance", "Finance"),
        ("tech", "Technology"),
        ("people", "People & Culture"),
    ]:
        org.add(key, Department(name=name))
    org.add("dubai", Site(name="Dubai", country="United Arab Emirates", currency="AED", timezone="Asia/Dubai"))
    org.add("accra", Site(name="Accra", country="Ghana", currency="GHS", timezone="Africa/Accra"))

    for key, name, department, site, manager, roles in [
        ("ceo",         "Cyrus Hale",   "exec",    "dubai", None,        ["executive", "ceo"]),
        ("coo",         "Nadia Frost",  "ops",     "dubai", "ceo",       ["executive", "coo"]),
        ("fin_head",    "Tom Becker",   "finance", "dubai", "ceo",       ["finance", "finance_admin"]),
        ("clerk",       "Sara Lind",    "finance", "dubai", "fin_head",  ["finance"]),
        ("tech_lead",   "Daniel Reyes", "tech",    "dubai", "coo",       ["admin"]),
        ("engineer",    "Leo Park",     "tech",    "dubai", "tech_lead", []),
        ("people_head", "Priya Nair",   "people",  "dubai", "coo",       []),
        ("site_mgr",    "Kwame Mensah", "ops",     "accra", "coo",       []),
        ("site_worker", "Ama Owusu",    "ops",     "accra", "site_mgr",  []),
        ("auditor",     "Grace Liu",    "exec",    "dubai", "ceo",       ["auditor"]),
    ]:  # fmt: skip
        org.add_user(key, name, department=department, site=site, manager=manager, roles=roles)

    for department, head in [("exec", "ceo"), ("ops", "coo"), ("finance", "fin_head"), ("tech", "tech_lead"), ("people", "people_head")]:
        getattr(org, department).head = org.users[head]

    for key, name, group, options in [
        ("software", "Software & subscriptions", CategoryGroup.IT, {}),
        ("flights", "Flights", CategoryGroup.TRAVEL, {}),
        ("visa", "Visas & travel fees", CategoryGroup.TRAVEL, {"quote_required": False}),
        ("office", "Office supplies", CategoryGroup.GENERAL, {}),
        ("legal", "Legal services", CategoryGroup.GENERAL, {"confidential_default": True}),
    ]:
        org.add(key, Category(name=name, group=group, **options))

    for currency, usd_per_unit in [("AED", "0.2723"), ("GHS", "0.0890")]:
        db.add(FxRate(currency=currency, usd_per_unit=Decimal(usd_per_unit), effective_date=date(2026, 1, 1)))
    ensure_policy(db)
    db.flush()
    return org


@pytest.fixture
def org(db: Session) -> Org:
    org = build_org(db)
    db.commit()  # releases the savepoint only; still rolled back after the test
    return org
