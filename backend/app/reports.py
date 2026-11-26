"""Spend reporting. Everything here is scoped to what the viewer is allowed to see."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    ApprovalStep,
    Category,
    Department,
    Invoice,
    InvoiceStatus,
    Project,
    RequestStatus,
    Site,
    SpendRequest,
    StepStatus,
    User,
)
from app.permissions import reporting_scope, stand_in_already_in_chain, visibility_clause
from app.timeutil import COMPANY_TZ, company_today

GROUPINGS = ("department", "category", "group", "project", "site", "month", "supplier")
COMMITTED_STATUSES = (RequestStatus.APPROVED, RequestStatus.CLOSED, RequestStatus.PENDING)


def _start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=COMPANY_TZ)


def _invoice_totals():
    return (
        select(
            Invoice.request_id.label("request_id"),
            func.sum(Invoice.amount_usd).label("invoiced"),
            func.sum(case((Invoice.status == InvoiceStatus.PAID, Invoice.amount_usd), else_=0)).label("paid"),
        )
        .group_by(Invoice.request_id)
        .subquery()
    )


def _committed_expr():
    return case(
        (
            and_(SpendRequest.approved_total_usd.isnot(None), SpendRequest.status.in_(COMMITTED_STATUSES)),
            SpendRequest.approved_total_usd,
        ),
        else_=0,
    )


def _pending_expr():
    return case(
        (and_(SpendRequest.status == RequestStatus.PENDING, SpendRequest.approved_revision.is_(None)), SpendRequest.total_usd),
        else_=0,
    )


def _period_filter(date_from: date | None, date_to: date | None):
    approved = and_(SpendRequest.approved_total_usd.isnot(None), SpendRequest.status.in_(COMMITTED_STATUSES))
    if date_from:
        approved = and_(approved, SpendRequest.approved_at >= _start(date_from))
    if date_to:
        approved = and_(approved, SpendRequest.approved_at < _start(date_to + timedelta(days=1)))
    in_approval = and_(SpendRequest.status == RequestStatus.PENDING, SpendRequest.approved_revision.is_(None))
    return or_(approved, in_approval)


def aggregate(
    db: Session,
    user: User,
    group_by: str,
    date_from: date | None = None,
    date_to: date | None = None,
    extra_filters: list[Any] | None = None,
) -> list[dict[str, Any]]:
    if group_by not in GROUPINGS:
        raise ValueError(f"group_by must be one of {GROUPINGS}")
    inv = _invoice_totals()
    key_cols = {
        "department": (Department.id, func.coalesce(Department.name, "No department")),
        "category": (Category.id, func.coalesce(Category.name, "Uncategorised")),
        "group": (Category.group, Category.group),
        "project": (Project.id, func.coalesce(Project.name, "Not tagged")),
        "site": (Site.id, func.coalesce(Site.name, "No site")),
        "month": (func.to_char(func.date_trunc("month", func.timezone("Asia/Dubai", SpendRequest.approved_at)), "YYYY-MM"),) * 2,
        "supplier": (func.lower(SpendRequest.supplier), func.min(SpendRequest.supplier)),
    }[group_by]
    key, label = key_cols
    label_col = label if group_by == "supplier" else func.min(label)
    stmt = (
        select(
            key.label("key"),
            label_col.label("label"),
            func.count(SpendRequest.id).label("count"),
            func.sum(_committed_expr()).label("committed"),
            func.sum(_pending_expr()).label("pending"),
            func.sum(func.coalesce(inv.c.invoiced, 0)).label("invoiced"),
            func.sum(func.coalesce(inv.c.paid, 0)).label("paid"),
            func.max(Project.kind).label("kind"),
            func.max(Project.budget_usd).label("budget"),
        )
        .select_from(SpendRequest)
        .outerjoin(Department, Department.id == SpendRequest.department_id)
        .outerjoin(Category, Category.id == SpendRequest.category_id)
        .outerjoin(Project, Project.id == SpendRequest.project_id)
        .outerjoin(Site, Site.id == SpendRequest.site_id)
        .outerjoin(inv, inv.c.request_id == SpendRequest.id)
        .where(visibility_clause(db, user), _period_filter(date_from, date_to), *(extra_filters or []))
        .group_by(key)
    )
    if group_by == "month":
        stmt = stmt.where(SpendRequest.approved_at.isnot(None)).order_by(key)
    else:
        stmt = stmt.order_by(func.sum(_committed_expr()).desc())
    rows = []
    for r in db.execute(stmt):
        rows.append(
            {
                "key": r.key,
                "label": r.label,
                "count": r.count,
                "committed_usd": float(r.committed or 0),
                "pending_usd": float(r.pending or 0),
                "invoiced_usd": float(r.invoiced or 0),
                "paid_usd": float(r.paid or 0),
                **({"kind": r.kind, "budget_usd": float(r.budget) if r.budget is not None else None} if group_by == "project" else {}),
            }
        )
    return rows


def _sum_committed(db: Session, user: User, since: date) -> float:
    val = db.execute(
        select(func.coalesce(func.sum(_committed_expr()), 0)).where(
            visibility_clause(db, user),
            SpendRequest.approved_total_usd.isnot(None),
            SpendRequest.status.in_(COMMITTED_STATUSES),
            SpendRequest.approved_at >= _start(since),
        )
    ).scalar()
    return float(val or 0)


def waiting_for(db: Session, user: User) -> list[SpendRequest]:
    """Requests whose current step is this person's, or someone they're covering."""
    from app.directory import Directory

    principals = [user.id, *Directory(db).principals_delegating_to(user.id, company_today())]
    rows = list(
        db.execute(
            select(SpendRequest)
            .join(ApprovalStep, and_(ApprovalStep.request_id == SpendRequest.id, ApprovalStep.revision == SpendRequest.revision))
            .where(
                SpendRequest.status == RequestStatus.PENDING,
                ApprovalStep.status == StepStatus.PENDING,
                ApprovalStep.approver_id.in_(principals),
                SpendRequest.requester_id != user.id,
            )
            .order_by(ApprovalStep.activated_at)
        )
        .scalars()
        .unique()
    )
    # Stand-ins don't see requests they already approve in their own right (one person, one approval).
    return [r for r in rows if r.pending_step.approver_id == user.id or not stand_in_already_in_chain(user, r.pending_step)]


def dashboard_numbers(db: Session, user: User) -> dict[str, Any]:
    today = company_today()
    month_start = today.replace(day=1)
    quarter_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    year_start = date(today.year, 1, 1)
    visible = visibility_clause(db, user)
    inv = _invoice_totals()

    pending = db.execute(
        select(func.count(SpendRequest.id), func.coalesce(func.sum(SpendRequest.total_usd), 0)).where(
            visible, SpendRequest.status == RequestStatus.PENDING, SpendRequest.approved_revision.is_(None)
        )
    ).one()
    awaiting_invoice = db.execute(
        select(func.count(SpendRequest.id), func.coalesce(func.sum(SpendRequest.approved_total_usd), 0))
        .outerjoin(inv, inv.c.request_id == SpendRequest.id)
        .where(visible, SpendRequest.status == RequestStatus.APPROVED, inv.c.request_id.is_(None))
    ).one()
    awaiting_payment = db.execute(
        select(func.count(Invoice.id), func.coalesce(func.sum(Invoice.amount_usd), 0))
        .join(SpendRequest, SpendRequest.id == Invoice.request_id)
        .where(visible, Invoice.status == InvoiceStatus.RECEIVED)
    ).one()

    trend_from = (today.replace(day=1) - timedelta(days=330)).replace(day=1)
    month_key = func.to_char(func.date_trunc("month", func.timezone("Asia/Dubai", SpendRequest.approved_at)), "YYYY-MM")
    trend_rows = db.execute(
        select(month_key.label("month"), Category.group, func.sum(_committed_expr()))
        .outerjoin(Category, Category.id == SpendRequest.category_id)
        .where(
            visible,
            SpendRequest.approved_total_usd.isnot(None),
            SpendRequest.status.in_(COMMITTED_STATUSES),
            SpendRequest.approved_at >= _start(trend_from),
        )
        .group_by(month_key, Category.group)
        .order_by(month_key)
    ).all()
    months: list[str] = []
    d = trend_from
    while d <= today:
        months.append(d.strftime("%Y-%m"))
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    trend = {m: {"month": m, "it": 0.0, "travel": 0.0, "general": 0.0} for m in months}
    for month, group, total in trend_rows:
        if month in trend and group in ("it", "travel", "general"):
            trend[month][group] = float(total or 0)

    return {
        "scope": reporting_scope(db, user),
        "pending": {"count": pending[0], "usd": float(pending[1])},
        "committed": {
            "month_usd": _sum_committed(db, user, month_start),
            "quarter_usd": _sum_committed(db, user, quarter_start),
            "year_usd": _sum_committed(db, user, year_start),
        },
        "awaiting_invoice": {"count": awaiting_invoice[0], "usd": float(awaiting_invoice[1])},
        "awaiting_payment": {"count": awaiting_payment[0], "usd": float(awaiting_payment[1])},
        "by_group": aggregate(db, user, "group", year_start, today),
        "by_department": aggregate(db, user, "department", year_start, today)[:8],
        "top_projects": [r for r in aggregate(db, user, "project", None, None) if r["key"] is not None][:6],
        "trend": list(trend.values()),
        "period": {"year_start": year_start.isoformat(), "today": today.isoformat()},
    }


def project_totals(db: Session, user: User) -> dict[int, dict[str, Any]]:
    return {r["key"]: r for r in aggregate(db, user, "project") if r["key"] is not None}


def money_float(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None

