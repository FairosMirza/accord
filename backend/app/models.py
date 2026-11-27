from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

_clock: ContextVar[datetime | None] = ContextVar("accord_clock", default=None)


def utcnow() -> datetime:
    return _clock.get() or datetime.now(UTC)


@contextmanager
def clock_at(moment: datetime) -> Iterator[None]:
    """Run code as if it were `moment`. Used to generate realistic demo history."""
    token = _clock.set(moment.astimezone(UTC))
    try:
        yield
    finally:
        _clock.reset(token)


class Base(DeclarativeBase):
    pass


class Role(StrEnum):
    ADMIN = "admin"  # IT administration: people, roles
    FINANCE = "finance"  # Finance team: invoices and payments
    FINANCE_ADMIN = "finance_admin"  # Owns the approval policy, categories and FX rates
    AUDITOR = "auditor"  # Read-only access to everything, including the audit log
    EXECUTIVE = "executive"  # Sees all spend
    # Position roles. Approval rules route to whoever currently holds the position.
    COO = "coo"
    CEO = "ceo"


SEE_ALL_ROLES = {Role.ADMIN, Role.FINANCE, Role.FINANCE_ADMIN, Role.AUDITOR, Role.EXECUTIVE}
POSITION_ROLES = {Role.COO, Role.CEO}


class CategoryGroup(StrEnum):
    IT = "it"
    TRAVEL = "travel"
    GENERAL = "general"


class RequestStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    RETURNED = "returned"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    CANCELLED = "cancelled"
    CLOSED = "closed"


class StepStatus(StrEnum):
    WAITING = "waiting"  # later in the chain, not yet active
    PENDING = "pending"  # waiting for this approver now
    APPROVED = "approved"
    REJECTED = "rejected"
    RETURNED = "returned"
    SKIPPED = "skipped"  # no longer needed (request rejected, withdrawn or re-routed)


class PaymentType(StrEnum):
    ONE_OFF = "one_off"
    RECURRING = "recurring"


class BillingPeriod(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUALLY = "annually"


PERIOD_MONTHS = {BillingPeriod.MONTHLY: 1, BillingPeriod.QUARTERLY: 3, BillingPeriod.ANNUALLY: 12}


class AttachmentKind(StrEnum):
    QUOTE = "quote"
    INVOICE = "invoice"
    SUPPORTING = "supporting"


class InvoiceStatus(StrEnum):
    RECEIVED = "received"
    QUERIED = "queried"  # Finance asked the supplier for a corrected invoice; not payable meanwhile
    PAID = "paid"
    VOID = "void"  # replaced by a corrected invoice; kept for the record, excluded from totals


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    head_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", use_alter=True, name="fk_departments_head_id")
    )

    head: Mapped[User | None] = relationship(foreign_keys=[head_id], post_update=True)


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    country: Mapped[str] = mapped_column(String(80))
    currency: Mapped[str] = mapped_column(String(3))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Dubai")


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    job_title: Mapped[str | None] = mapped_column(String(120))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"))
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    external_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    department: Mapped[Department | None] = relationship(foreign_keys=[department_id])
    site: Mapped[Site | None] = relationship()
    manager: Mapped[User | None] = relationship(remote_side=[id])

    def has_role(self, *roles: str) -> bool:
        return any(r in (self.roles or []) for r in roles)

    @property
    def sees_everything(self) -> bool:
        return self.has_role(*SEE_ALL_ROLES)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    group: Mapped[str] = mapped_column(String(16))
    description: Mapped[str | None] = mapped_column(Text)
    gl_code: Mapped[str | None] = mapped_column(String(32))
    quote_required: Mapped[bool] = mapped_column(Boolean, default=True)
    confidential_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Project(TimestampMixin, Base):
    """A project or a trip that spend can be tagged to."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(16))  # project | trip
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    destination: Mapped[str | None] = mapped_column(String(160))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id])
    department: Mapped[Department | None] = relationship()


class FxRate(TimestampMixin, Base):
    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("currency", "effective_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(3))
    usd_per_unit: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    effective_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(40), default="finance")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class PolicyVersion(TimestampMixin, Base):
    """Immutable snapshot of the approval policy. Every request records which version routed it."""

    __tablename__ = "policy_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    document: Mapped[dict] = mapped_column(JSONB)
    change_note: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    created_by: Mapped[User | None] = relationship()


class SpendRequest(TimestampMixin, Base):
    __tablename__ = "spend_requests"
    __table_args__ = (
        Index("ix_spend_requests_status", "status"),
        Index("ix_spend_requests_requester", "requester_id"),
        Index("ix_spend_requests_department", "department_id"),
        Index("ix_spend_requests_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(20), unique=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"))

    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    supplier: Mapped[str | None] = mapped_column(String(200))

    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # per payment for recurring spend
    payment_type: Mapped[str] = mapped_column(String(16), default=PaymentType.ONE_OFF)
    billing_period: Mapped[str | None] = mapped_column(String(16))
    term_months: Mapped[int | None] = mapped_column(Integer)  # None + recurring = rolling
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # full commitment
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(20, 10))  # USD per unit of currency
    total_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    needed_by: Mapped[date | None] = mapped_column(Date)
    start_date: Mapped[date | None] = mapped_column(Date)  # recurring: when the contract starts
    no_quote_reason: Mapped[str | None] = mapped_column(Text)
    is_confidential: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[str] = mapped_column(String(16), default=RequestStatus.DRAFT)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    current_step: Mapped[int | None] = mapped_column(Integer)
    policy_version_id: Mapped[int | None] = mapped_column(ForeignKey("policy_versions.id"))

    # What has actually been authorised; stays in force while an amendment is re-approved.
    approved_total_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    approved_total_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    approved_revision: Mapped[int | None] = mapped_column(Integer)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    renewal_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )

    requester: Mapped[User] = relationship(foreign_keys=[requester_id])
    department: Mapped[Department | None] = relationship()
    site: Mapped[Site | None] = relationship()
    category: Mapped[Category | None] = relationship()
    project: Mapped[Project | None] = relationship()
    policy_version: Mapped[PolicyVersion | None] = relationship()
    steps: Mapped[list[ApprovalStep]] = relationship(
        back_populates="request",
        order_by="(ApprovalStep.revision, ApprovalStep.sequence)",
        cascade="all, delete-orphan",
    )
    revisions: Mapped[list[RequestRevision]] = relationship(
        back_populates="request", order_by="RequestRevision.number", cascade="all, delete-orphan"
    )
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="request", order_by="Attachment.id", cascade="all, delete-orphan"
    )
    invoices: Mapped[list[Invoice]] = relationship(
        back_populates="request", order_by="Invoice.id", cascade="all, delete-orphan"
    )
    comments: Mapped[list[Comment]] = relationship(
        back_populates="request", order_by="Comment.id", cascade="all, delete-orphan"
    )

    @property
    def current_steps(self) -> list[ApprovalStep]:
        return [s for s in self.steps if s.revision == self.revision]

    @property
    def pending_step(self) -> ApprovalStep | None:
        return next((s for s in self.current_steps if s.status == StepStatus.PENDING), None)

    @property
    def is_amendment_in_progress(self) -> bool:
        return self.status == RequestStatus.PENDING and self.approved_revision is not None


class RequestRevision(TimestampMixin, Base):
    """Snapshot of what was submitted for approval. Never modified after creation except status."""

    __tablename__ = "request_revisions"
    __table_args__ = (UniqueConstraint("request_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("spend_requests.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # submission | resubmission | amendment
    status: Mapped[str] = mapped_column(String(16))  # pending | approved | rejected | returned | withdrawn | applied
    data: Mapped[dict] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    total_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reason: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    request: Mapped[SpendRequest] = relationship(back_populates="revisions")
    created_by: Mapped[User | None] = relationship()


class ApprovalStep(Base):
    __tablename__ = "approval_steps"
    __table_args__ = (
        Index("ix_approval_steps_approver_status", "approver_id", "status"),
        Index("ix_approval_steps_request", "request_id", "revision"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("spend_requests.id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(Integer)
    approver_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    position_role: Mapped[str | None] = mapped_column(String(32))
    reasons: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    rule_keys: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    routing_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=StepStatus.WAITING)

    acted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    on_behalf_of_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decision_reason: Mapped[str | None] = mapped_column(String(120))
    comment: Mapped[str | None] = mapped_column(Text)
    approved_content_hash: Mapped[str | None] = mapped_column(String(64))

    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)

    request: Mapped[SpendRequest] = relationship(back_populates="steps")
    approver: Mapped[User] = relationship(foreign_keys=[approver_id])
    acted_by: Mapped[User | None] = relationship(foreign_keys=[acted_by_id])
    on_behalf_of: Mapped[User | None] = relationship(foreign_keys=[on_behalf_of_id])


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("spend_requests.id", ondelete="CASCADE"))
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(300))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )

    request: Mapped[SpendRequest] = relationship(back_populates="attachments")
    uploaded_by: Mapped[User | None] = relationship()


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("spend_requests.id", ondelete="CASCADE"))
    invoice_number: Mapped[str] = mapped_column(String(80))
    invoice_date: Mapped[date] = mapped_column(Date)
    supplier: Mapped[str | None] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(16), default=InvoiceStatus.RECEIVED)
    exceeds_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    override_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    received_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    paid_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_on: Mapped[date | None] = mapped_column(Date)
    payment_reference: Mapped[str | None] = mapped_column(String(120))
    query_reason: Mapped[str | None] = mapped_column(Text)
    queried_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    queried_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_invoices_queried_by_id"))
    query_resolution: Mapped[str | None] = mapped_column(Text)
    replaces_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id", name="fk_invoices_replaces_invoice_id"))
    void_reason: Mapped[str | None] = mapped_column(Text)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_invoices_voided_by_id"))

    request: Mapped[SpendRequest] = relationship(back_populates="invoices")
    received_by: Mapped[User | None] = relationship(foreign_keys=[received_by_id])
    paid_by: Mapped[User | None] = relationship(foreign_keys=[paid_by_id])
    queried_by: Mapped[User | None] = relationship(foreign_keys=[queried_by_id])
    voided_by: Mapped[User | None] = relationship(foreign_keys=[voided_by_id])
    attachments: Mapped[list[Attachment]] = relationship(viewonly=True)

    @property
    def is_live(self) -> bool:
        return self.status != InvoiceStatus.VOID


class Delegation(TimestampMixin, Base):
    """While active, the delegate can act on the principal's approvals (recorded as on-behalf-of)."""

    __tablename__ = "delegations"

    id: Mapped[int] = mapped_column(primary_key=True)
    principal_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    delegate_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    principal: Mapped[User] = relationship(foreign_keys=[principal_id])
    delegate: Mapped[User] = relationship(foreign_keys=[delegate_id])
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])


class Comment(TimestampMixin, Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("spend_requests.id", ondelete="CASCADE"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)

    request: Mapped[SpendRequest] = relationship(back_populates="comments")
    author: Mapped[User] = relationship()


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[int | None] = mapped_column(ForeignKey("spend_requests.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(300))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailMessage(TimestampMixin, Base):
    """Every email Accord sends is kept here, so delivery is provable."""

    __tablename__ = "email_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    to_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    to_email: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(300))
    body_text: Mapped[str] = mapped_column(Text)
    body_html: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(40))
    request_id: Mapped[int | None] = mapped_column(ForeignKey("spend_requests.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="stored")  # stored | sent | failed
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    to_user: Mapped[User | None] = relationship()


class AuditEvent(Base):
    """Append-only, hash-chained log. Updates and deletes are blocked by a database trigger."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_request", "request_id"),
        Index("ix_audit_events_occurred", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    on_behalf_of_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    request_id: Mapped[int | None] = mapped_column(ForeignKey("spend_requests.id"))
    summary: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)

    actor: Mapped[User | None] = relationship(foreign_keys=[actor_id])
    on_behalf_of: Mapped[User | None] = relationship(foreign_keys=[on_behalf_of_id])


class UserSession(TimestampMixin, Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    auth_method: Mapped[str] = mapped_column(String(16))  # oidc | demo
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))

    user: Mapped[User] = relationship()


class DemoPersona(Base):
    __tablename__ = "demo_personas"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer)
    headline: Mapped[str] = mapped_column(String(160))
    blurb: Mapped[str] = mapped_column(Text)

    user: Mapped[User] = relationship()
