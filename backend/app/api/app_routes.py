import csv
import io
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app import audit, workflow
from app.api.requests import summary_options
from app.audit import verify_chain
from app.auth import client_info, current_user, require_roles
from app.config import get_settings
from app.db import get_db
from app.directory import Directory
from app.errors import DomainError, NotAllowed
from app.fx import supported_currencies
from app.invoicing import next_step
from app.models import (
    POSITION_ROLES,
    ApprovalStep,
    AuditEvent,
    Category,
    Delegation,
    Department,
    FxRate,
    Invoice,
    InvoiceStatus,
    Notification,
    Project,
    RequestStatus,
    Role,
    Site,
    SpendRequest,
    StepStatus,
    User,
)
from app.permissions import visibility_clause
from app.policy import ROLE_LABELS, current_policy, stand_in_problem
from app.reports import GROUPINGS, aggregate, dashboard_numbers, project_totals, waiting_for
from app.serializers import audit_json, delegation_json, finance_state, request_summary, user_brief
from app.timeutil import company_today

router = APIRouter(prefix="/api", tags=["app"])


# ---------------------------------------------------------------- reference data for forms


@router.get("/lookups")
def lookups(user: User = Depends(current_user), db: Session = Depends(get_db)):
    pv, policy = current_policy(db)
    rates = {}
    for r in db.execute(select(FxRate).order_by(FxRate.currency, FxRate.effective_date.desc())).scalars():
        rates.setdefault(r.currency, {"currency": r.currency, "usd_per_unit": float(r.usd_per_unit), "effective_date": r.effective_date.isoformat()})
    site_currency = user.site.currency if user.site else "USD"
    return {
        "categories": [
            {"id": c.id, "name": c.name, "group": c.group, "description": c.description, "quote_required": c.quote_required, "confidential_default": c.confidential_default}
            for c in db.execute(select(Category).where(Category.is_active.is_(True)).order_by(Category.sort_order, Category.name)).scalars()
        ],
        "projects": [
            {"id": p.id, "code": p.code, "name": p.name, "kind": p.kind, "destination": p.destination, "start_date": p.start_date.isoformat() if p.start_date else None}
            for p in db.execute(select(Project).where(Project.is_active.is_(True)).order_by(Project.kind, Project.name)).scalars()
        ],
        "departments": [{"id": d.id, "name": d.name} for d in db.execute(select(Department).order_by(Department.name)).scalars()],
        "sites": [{"id": s.id, "name": s.name, "country": s.country, "currency": s.currency} for s in db.execute(select(Site).order_by(Site.name)).scalars()],
        "currencies": supported_currencies(db),
        "rates": list(rates.values()),
        "default_currency": site_currency,
        "base_currency": get_settings().base_currency,
        "policy": {
            "version": pv.version,
            "rejection_reasons": policy.rejection_reasons,
            "amendment_tolerance_pct": float(policy.amendment_tolerance_pct),
            "rolling_term_months": policy.rolling_term_months,
        },
    }


# ---------------------------------------------------------------- dashboard and reports


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    waiting = waiting_for(db, user)
    mine = db.execute(
        select(SpendRequest)
        .where(SpendRequest.requester_id == user.id)
        .options(*summary_options())
        .order_by(SpendRequest.updated_at.desc())
        .limit(6)
    ).scalars()
    return {
        "waiting": [request_summary(r) for r in waiting],
        "attention": attention_for(db, user),
        "mine": [request_summary(r) for r in mine],
        "numbers": dashboard_numbers(db, user),
    }


def attention_for(db: Session, user: User) -> list[dict]:
    """Invoice differences where this person owns the next step (approvals already appear in "waiting")."""
    flagged = and_(Invoice.status != InvoiceStatus.VOID, Invoice.exceeds_approval.is_(True))
    handled_by_me = select(Invoice.request_id).where(
        or_(and_(flagged, Invoice.received_by_id == user.id), and_(Invoice.status == InvoiceStatus.QUERIED, Invoice.queried_by_id == user.id))
    )
    rows = db.execute(
        select(SpendRequest)
        .where(
            visibility_clause(db, user),
            SpendRequest.status.in_((RequestStatus.APPROVED, RequestStatus.PENDING)),
            or_(
                and_(SpendRequest.requester_id == user.id, SpendRequest.id.in_(select(Invoice.request_id).where(flagged))),
                SpendRequest.id.in_(handled_by_me),
            ),
        )
        .options(*summary_options())
        .order_by(SpendRequest.updated_at.desc())
    ).scalars()
    out = []
    for r in rows:
        step = next_step(r)
        if step and step.kind != "approval" and step.owner is not None and step.owner.id == user.id:
            out.append(request_summary(r))
    return out


@router.get("/reports/spend")
def spend_report(
    group_by: str = "department",
    date_from: date | None = None,
    date_to: date | None = None,
    category_group: str | None = None,
    department_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if group_by not in GROUPINGS:
        raise HTTPException(400, f"group_by must be one of {', '.join(GROUPINGS)}")
    filters = []
    if category_group:
        filters.append(SpendRequest.category_id.in_(select(Category.id).where(Category.group == category_group)))
    if department_id:
        filters.append(SpendRequest.department_id == department_id)
    return {"rows": aggregate(db, user, group_by, date_from, date_to, filters)}


# ---------------------------------------------------------------- finance


@router.get("/finance/queue")
def finance_queue(
    state: Literal["awaiting_invoice", "awaiting_payment", "differences", "paid", "all"] = "all",
    q: str | None = None,
    user: User = Depends(require_roles(Role.FINANCE, Role.FINANCE_ADMIN, Role.EXECUTIVE, Role.AUDITOR)),
    db: Session = Depends(get_db),
):
    stmt = (
        select(SpendRequest)
        .where(
            visibility_clause(db, user),
            SpendRequest.approved_total_usd.isnot(None),
            SpendRequest.status.in_([RequestStatus.APPROVED, RequestStatus.PENDING, RequestStatus.CLOSED]),
        )
        .options(*summary_options())
        .order_by(SpendRequest.approved_at.desc())
    )
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(SpendRequest.title).like(like), func.lower(SpendRequest.ref).like(like), func.lower(SpendRequest.supplier).like(like)))
    items = [request_summary(r) for r in db.execute(stmt).scalars()]
    totals = {k: {"count": 0, "usd": 0.0} for k in ("awaiting_invoice", "awaiting_payment", "differences", "paid")}
    for it in items:
        f = it["finance"]
        if it["status"] == RequestStatus.CLOSED and f["state"] != "awaiting_payment":
            f["state"] = "paid" if f["invoice_count"] else "closed"
        if f["state"] in totals:
            totals[f["state"]]["count"] += 1
            totals[f["state"]]["usd"] += f["remaining_usd"] if f["state"] == "awaiting_invoice" else (f["invoiced_usd"] - f["paid_usd"] if f["state"] == "awaiting_payment" else f["paid_usd"])
        if f["next_step"]:
            totals["differences"]["count"] += 1
            totals["differences"]["usd"] += f["excess"]["over_usd"] if f["excess"] else 0
    if state == "differences":
        items = [it for it in items if it["finance"]["next_step"]]
    elif state != "all":
        items = [it for it in items if it["finance"]["state"] == state]
    items.sort(key=lambda it: it["finance"]["next_step"] is None)
    return {"items": items, "totals": totals}


@router.get("/finance/export.csv")
def finance_export(user: User = Depends(require_roles(Role.FINANCE, Role.FINANCE_ADMIN, Role.EXECUTIVE, Role.AUDITOR)), db: Session = Depends(get_db)):
    rows = db.execute(
        select(SpendRequest)
        .where(visibility_clause(db, user), SpendRequest.approved_total_usd.isnot(None))
        .options(*summary_options(), selectinload(SpendRequest.steps).selectinload(ApprovalStep.acted_by))
        .order_by(SpendRequest.approved_at)
    ).scalars()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Reference", "Title", "Status", "Requester", "Department", "Site", "Category", "GL code", "Project / trip", "Supplier", "Currency", "Approved amount", "Approved USD", "Approved at", "Approvals", "Invoiced USD", "Paid USD", "Finance state", "Over approval USD", "Next step"])
    for r in rows:
        f = finance_state(r) or {}
        approvals = "; ".join(
            f"{s.acted_by.name if s.acted_by else s.approver.name}"
            + (f" for {s.on_behalf_of.name}" if s.on_behalf_of else "")
            + f" {s.acted_at:%Y-%m-%d %H:%M}Z"
            for s in r.steps
            if s.status == StepStatus.APPROVED and s.acted_at
        )
        w.writerow([r.ref, r.title, r.status, r.requester.name, r.department.name if r.department else "", r.site.name if r.site else "", r.category.name if r.category else "", r.category.gl_code if r.category else "", r.project.name if r.project else "", r.supplier, r.currency, r.approved_total_amount, r.approved_total_usd, r.approved_at.isoformat() if r.approved_at else "", approvals, f.get("invoiced_usd"), f.get("paid_usd"), f.get("state"), (f.get("excess") or {}).get("over_usd", ""), (f.get("next_step") or {}).get("label", "")])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="accord-approved-spend-{company_today()}.csv"'})


# ---------------------------------------------------------------- projects and trips


class ProjectBody(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    kind: Literal["project", "trip"]
    description: str | None = Field(None, max_length=2000)
    destination: str | None = Field(None, max_length=160)
    start_date: date | None = None
    end_date: date | None = None
    budget_usd: Decimal | None = Field(None, ge=0)
    department_id: int | None = None


class ProjectPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=160)
    description: str | None = Field(None, max_length=2000)
    destination: str | None = Field(None, max_length=160)
    start_date: date | None = None
    end_date: date | None = None
    budget_usd: Decimal | None = Field(None, ge=0)
    is_active: bool | None = None


def _project_json(p: Project, totals: dict | None) -> dict:
    t = totals or {}
    return {
        "id": p.id,
        "code": p.code,
        "name": p.name,
        "kind": p.kind,
        "description": p.description,
        "destination": p.destination,
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "end_date": p.end_date.isoformat() if p.end_date else None,
        "budget_usd": float(p.budget_usd) if p.budget_usd is not None else None,
        "is_active": p.is_active,
        "owner": user_brief(p.owner),
        "department": p.department.name if p.department else None,
        "committed_usd": t.get("committed_usd", 0.0),
        "pending_usd": t.get("pending_usd", 0.0),
        "invoiced_usd": t.get("invoiced_usd", 0.0),
        "paid_usd": t.get("paid_usd", 0.0),
        "count": t.get("count", 0),
    }


@router.get("/projects")
def list_projects(kind: str | None = None, include_closed: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Project).order_by(Project.is_active.desc(), Project.start_date.desc().nullslast(), Project.name)
    if kind:
        stmt = stmt.where(Project.kind == kind)
    if not include_closed:
        stmt = stmt.where(Project.is_active.is_(True))
    totals = project_totals(db, user)
    return [_project_json(p, totals.get(p.id)) for p in db.execute(stmt).scalars()]


@router.get("/projects/{project_id}")
def project_detail(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404, "Not found.")
    filt = [SpendRequest.project_id == p.id]
    totals = aggregate(db, user, "project", extra_filters=filt)
    requests = db.execute(
        select(SpendRequest).where(visibility_clause(db, user), *filt, SpendRequest.status != RequestStatus.DRAFT).options(*summary_options()).order_by(SpendRequest.submitted_at.desc())
    ).scalars()
    return {
        **_project_json(p, totals[0] if totals else None),
        "by_category": aggregate(db, user, "category", extra_filters=filt),
        "by_department": aggregate(db, user, "department", extra_filters=filt),
        "requests": [request_summary(r) for r in requests],
    }


def _unique_code(db: Session, kind: str, name: str) -> str:
    stem = "".join(ch for ch in name.upper() if ch.isalnum())[:10] or "X"
    prefix = "PRJ" if kind == "project" else "TRP"
    code, n = f"{prefix}-{stem}", 2
    while db.execute(select(Project.id).where(Project.code == code)).first():
        code, n = f"{prefix}-{stem}{n}", n + 1
    return code


@router.post("/projects", status_code=201)
def create_project(body: ProjectBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    # Anyone can set up a trip; projects need someone with budget responsibility.
    if body.kind == "project" and not (Directory(db).has_reports(user.id) or user.has_role(Role.FINANCE_ADMIN, Role.ADMIN, Role.EXECUTIVE)):
        raise NotAllowed("Projects are set up by managers or Finance. You can create trips.")
    if body.end_date and body.start_date and body.end_date < body.start_date:
        raise DomainError("The end date is before the start date.")
    duplicate = db.execute(select(Project).where(func.lower(Project.name) == body.name.strip().lower(), Project.is_active.is_(True))).scalar()
    if duplicate:
        raise DomainError(f"There's already an open {duplicate.kind} called {duplicate.name}.", "duplicate")
    p = Project(
        code=_unique_code(db, body.kind, body.name),
        name=body.name.strip(),
        kind=body.kind,
        description=body.description,
        destination=body.destination,
        start_date=body.start_date,
        end_date=body.end_date,
        budget_usd=body.budget_usd,
        department_id=body.department_id or user.department_id,
        owner_id=user.id,
        created_by_id=user.id,
    )
    db.add(p)
    db.flush()
    audit.record(db, action="project.created", summary=f"{user.name} created {p.kind} {p.name} ({p.code})", entity_type="project", entity_id=p.id, actor=user, data=body.model_dump(mode="json"), client=client_info(request))
    db.commit()
    return _project_json(p, None)


@router.patch("/projects/{project_id}")
def update_project(project_id: int, body: ProjectPatch, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404, "Not found.")
    if p.owner_id != user.id and not user.has_role(Role.FINANCE_ADMIN, Role.ADMIN):
        raise NotAllowed("Only the owner or Finance can change this.")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(p, k, v)
    audit.record(db, action="project.updated", summary=f"{user.name} updated {p.name}", entity_type="project", entity_id=p.id, actor=user, data=body.model_dump(mode="json", exclude_unset=True), client=client_info(request))
    db.commit()
    return _project_json(p, project_totals(db, user).get(p.id))


# ---------------------------------------------------------------- delegation (cover while away)


class DelegationBody(BaseModel):
    delegate_id: int
    starts_on: date
    ends_on: date
    note: str | None = Field(None, max_length=500)
    principal_id: int | None = None


@router.get("/delegations")
def list_delegations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = company_today()
    mine = db.execute(select(Delegation).where(Delegation.principal_id == user.id).order_by(Delegation.starts_on.desc()).limit(20)).scalars()
    covering = db.execute(select(Delegation).where(Delegation.delegate_id == user.id, Delegation.ends_on >= today, Delegation.revoked_at.is_(None))).scalars()
    result = {"mine": [delegation_json(d) for d in mine], "covering": [delegation_json(d) for d in covering]}
    if user.has_role(Role.ADMIN, *POSITION_ROLES, Role.EXECUTIVE):
        everyone = db.execute(select(Delegation).where(Delegation.ends_on >= today, Delegation.revoked_at.is_(None)).order_by(Delegation.starts_on)).scalars()
        result["all_current"] = [delegation_json(d) for d in everyone]
    return result


@router.get("/delegations/eligible")
def eligible_stand_ins(principal_id: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    principal = db.get(User, principal_id) if principal_id and user.has_role(Role.ADMIN) else user
    _, policy = current_policy(db)
    directory = Directory(db)
    candidates = db.execute(select(User).where(User.is_active.is_(True), User.id != principal.id).order_by(User.name)).scalars()
    eligible = [u for u in candidates if stand_in_problem(principal, u, policy, directory) is None]
    rule = (
        "Stand-ins for " + principal.name + " must be: " + ", ".join(ROLE_LABELS.get(r, r) for r in policy.stand_in_roles)
        if principal.has_role(*POSITION_ROLES)
        else "Stand-ins must be people managers themselves."
    )
    return {"rule": rule, "people": [user_brief(u) for u in eligible]}


@router.post("/delegations", status_code=201)
def create_delegation(body: DelegationBody, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    principal = db.get(User, body.principal_id) if body.principal_id else user
    delegate = db.get(User, body.delegate_id)
    if principal is None or delegate is None:
        raise HTTPException(404, "Person not found.")
    d = workflow.create_delegation(db, user, principal, delegate, body.starts_on, body.ends_on, body.note, client_info(request))
    db.commit()
    return delegation_json(d)


@router.post("/delegations/{delegation_id}/revoke")
def revoke_delegation(delegation_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(Delegation, delegation_id)
    if d is None:
        raise HTTPException(404, "Not found.")
    workflow.revoke_delegation(db, user, d, client_info(request))
    db.commit()
    return delegation_json(d)


# ---------------------------------------------------------------- notifications


class ReadBody(BaseModel):
    ids: list[int] | None = None


@router.get("/notifications")
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc()).limit(50)).scalars()
    return [
        {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "created_at": n.created_at.isoformat(), "read_at": n.read_at.isoformat() if n.read_at else None}
        for n in rows
    ]


@router.post("/notifications/read")
def mark_read(body: ReadBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.models import utcnow

    stmt = select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if body.ids:
        stmt = stmt.where(Notification.id.in_(body.ids))
    for n in db.execute(stmt).scalars():
        n.read_at = utcnow()
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- audit


@router.get("/audit")
def audit_log(
    q: str | None = None,
    action: str | None = None,
    actor_id: int | None = None,
    ref: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not user.sees_everything:
        raise NotAllowed("The full audit log is available to Finance, executives, auditors and administrators.")
    stmt = _audit_query(q, action, actor_id, ref, date_from, date_to)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(stmt.order_by(AuditEvent.id.desc()).limit(max(1, min(limit, 500))).offset(offset)).scalars()
    return {"items": [audit_json(e) | {"request_ref": e.entity_id if e.entity_type == "request" else None} for e in rows], "total": total}


def _audit_query(q, action, actor_id, ref, date_from, date_to):
    from datetime import datetime, time, timedelta

    from app.timeutil import COMPANY_TZ

    stmt = select(AuditEvent)
    if q and q.strip():
        stmt = stmt.where(func.lower(AuditEvent.summary).like(f"%{q.strip().lower()}%"))
    if action:
        stmt = stmt.where(AuditEvent.action.like(f"{action}%"))
    if actor_id:
        stmt = stmt.where(or_(AuditEvent.actor_id == actor_id, AuditEvent.on_behalf_of_id == actor_id))
    if ref:
        stmt = stmt.where(AuditEvent.request_id.in_(select(SpendRequest.id).where(SpendRequest.ref == ref.strip().upper())))
    if date_from:
        stmt = stmt.where(AuditEvent.occurred_at >= datetime.combine(date_from, time.min, tzinfo=COMPANY_TZ))
    if date_to:
        stmt = stmt.where(AuditEvent.occurred_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=COMPANY_TZ))
    return stmt


@router.get("/audit/export.csv")
def audit_export(
    q: str | None = None,
    action: str | None = None,
    actor_id: int | None = None,
    ref: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not user.sees_everything:
        raise NotAllowed()
    rows = db.execute(_audit_query(q, action, actor_id, ref, date_from, date_to).order_by(AuditEvent.id)).scalars()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Event", "When (UTC)", "Action", "Who", "On behalf of", "Request", "Summary", "IP", "Hash", "Previous hash"])
    for e in rows:
        req_ref = None
        if e.request_id:
            req_ref = db.execute(select(SpendRequest.ref).where(SpendRequest.id == e.request_id)).scalar()
        w.writerow([e.id, e.occurred_at.isoformat(), e.action, e.actor.name if e.actor else "System", e.on_behalf_of.name if e.on_behalf_of else "", req_ref or "", e.summary, e.ip or "", e.hash, e.prev_hash])
    audit.record(db, action="audit.exported", summary=f"{user.name} exported the audit log", entity_type="audit", actor=user, data={"filters": {"q": q, "action": action, "actor_id": actor_id, "ref": ref, "from": str(date_from), "to": str(date_to)}})
    db.commit()
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="accord-audit-{company_today()}.csv"'})


@router.get("/audit/verify")
def audit_verify(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.sees_everything:
        raise NotAllowed()
    r = verify_chain(db)
    return {"ok": r.ok, "events_checked": r.events_checked, "first_bad_event_id": r.first_bad_event_id, "problem": r.problem}
