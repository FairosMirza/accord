from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import audit, workflow
from app.auth import client_info, current_user, require_roles
from app.db import get_db
from app.directory import Directory
from app.errors import DomainError, NotAllowed
from app.models import (
    POSITION_ROLES,
    Category,
    CategoryGroup,
    Department,
    FxRate,
    PolicyVersion,
    Role,
    Site,
    SpendRequest,
    User,
)
from app.policy import ROLE_LABELS, PolicyDocument, RouteInput, compute_route, current_policy
from app.serializers import user_brief

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------- approval policy


def _policy_payload(db: Session) -> dict:
    pv, doc = current_policy(db)
    versions = db.execute(select(PolicyVersion).order_by(PolicyVersion.version.desc())).scalars()
    directory = Directory(db)
    holders = {}
    for role in [*POSITION_ROLES, Role.FINANCE_ADMIN]:
        holder = directory.holder_of(role)
        holders[role] = user_brief(holder)
    return {
        "current": {"version": pv.version, "document": doc.model_dump(mode="json"), "created_at": pv.created_at.isoformat(), "created_by": user_brief(pv.created_by), "change_note": pv.change_note},
        "versions": [
            {"version": v.version, "created_at": v.created_at.isoformat(), "created_by": user_brief(v.created_by), "change_note": v.change_note}
            for v in versions
        ],
        "role_labels": ROLE_LABELS,
        "position_holders": holders,
        "category_groups": [g.value for g in CategoryGroup],
    }


@router.get("/policy")
def get_policy(user: User = Depends(current_user), db: Session = Depends(get_db)):
    # Everyone may read the rules: transparency about who approves what.
    return _policy_payload(db)


@router.get("/policy/versions/{version}")
def get_policy_version(version: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    pv = db.execute(select(PolicyVersion).where(PolicyVersion.version == version)).scalar()
    if pv is None:
        raise HTTPException(404, "Version not found.")
    return {"version": pv.version, "document": pv.document, "created_at": pv.created_at.isoformat(), "created_by": user_brief(pv.created_by), "change_note": pv.change_note}


class PolicyUpdate(BaseModel):
    document: dict
    change_note: str = Field(min_length=3, max_length=1000)


def _parse_policy(raw: dict) -> PolicyDocument:
    try:
        return PolicyDocument.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", []))
        raise DomainError(f"The policy isn't valid ({where}: {first.get('msg')}).", "policy_invalid") from exc


def _validate_references(db: Session, doc: PolicyDocument) -> None:
    directory = Directory(db)
    for rule in doc.rules:
        if rule.approver.type == "role":
            if not rule.approver.role or directory.holder_of(rule.approver.role) is None:
                raise DomainError(f"Rule '{rule.label}': nobody holds the {ROLE_LABELS.get(rule.approver.role or '', rule.approver.role)} role.", "policy_invalid")
        if rule.approver.type == "user":
            u = directory.user(rule.approver.user_id)
            if u is None or not u.is_active:
                raise DomainError(f"Rule '{rule.label}': choose an active person.", "policy_invalid")
    if directory.holder_of(doc.fallback_approver_role) is None:
        raise DomainError("Nobody holds the fallback approver role.", "policy_invalid")


@router.post("/policy")
def save_policy(body: PolicyUpdate, request: Request, user: User = Depends(require_roles(Role.FINANCE_ADMIN)), db: Session = Depends(get_db)):
    doc = _parse_policy(body.document)
    _validate_references(db, doc)
    pv, current = current_policy(db)
    if doc.model_dump(mode="json") == current.model_dump(mode="json"):
        raise DomainError("No changes to save.", "no_changes")
    new = PolicyVersion(version=pv.version + 1, document=doc.model_dump(mode="json"), change_note=body.change_note.strip(), created_by_id=user.id)
    db.add(new)
    db.flush()
    before = {r.key: r.model_dump(mode="json") for r in current.rules}
    after = {r.key: r.model_dump(mode="json") for r in doc.rules}
    audit.record(
        db,
        action="policy.updated",
        summary=f"{user.name} published approval policy v{new.version}: {new.change_note}",
        entity_type="policy",
        entity_id=new.version,
        actor=user,
        data={
            "from_version": pv.version,
            "to_version": new.version,
            "rules_added": sorted(set(after) - set(before)),
            "rules_removed": sorted(set(before) - set(after)),
            "rules_changed": sorted(k for k in set(before) & set(after) if before[k] != after[k]),
            "document": new.document,
        },
        client=client_info(request),
    )
    db.commit()
    return _policy_payload(db)


class SimulateBody(BaseModel):
    document: dict | None = None
    requester_id: int
    category_id: int
    total_usd: Decimal = Field(ge=0)


@router.post("/policy/simulate")
def simulate(body: SimulateBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Try a draft policy against an example before publishing it."""
    doc = _parse_policy(body.document) if body.document else current_policy(db)[1]
    requester = db.get(User, body.requester_id)
    category = db.get(Category, body.category_id)
    if requester is None or category is None:
        raise HTTPException(404, "Person or category not found.")
    route = compute_route(doc, RouteInput(requester=requester, category=category, department_id=requester.department_id, site_id=requester.site_id, total_usd=body.total_usd), Directory(db))
    return {"steps": [{"approver": user_brief(s.approver), "reasons": s.reasons, "notes": s.notes} for s in route]}


# ---------------------------------------------------------------- categories


class CategoryBody(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    group: CategoryGroup
    description: str | None = Field(None, max_length=500)
    gl_code: str | None = Field(None, max_length=32)
    quote_required: bool = True
    confidential_default: bool = False
    is_active: bool = True
    sort_order: int = 0


def _category_json(c: Category, usage: int = 0) -> dict:
    return {"id": c.id, "name": c.name, "group": c.group, "description": c.description, "gl_code": c.gl_code, "quote_required": c.quote_required, "confidential_default": c.confidential_default, "is_active": c.is_active, "sort_order": c.sort_order, "usage": usage}


@router.get("/categories")
def list_categories(user: User = Depends(current_user), db: Session = Depends(get_db)):
    usage = dict(db.execute(select(SpendRequest.category_id, func.count()).group_by(SpendRequest.category_id)).all())
    rows = db.execute(select(Category).order_by(Category.sort_order, Category.name)).scalars()
    return [_category_json(c, usage.get(c.id, 0)) for c in rows]


@router.post("/categories", status_code=201)
def create_category(body: CategoryBody, request: Request, user: User = Depends(require_roles(Role.FINANCE_ADMIN)), db: Session = Depends(get_db)):
    if db.execute(select(Category).where(func.lower(Category.name) == body.name.strip().lower())).first():
        raise DomainError("A category with that name already exists.", "duplicate")
    c = Category(**body.model_dump())
    c.name = c.name.strip()
    db.add(c)
    db.flush()
    audit.record(db, action="category.created", summary=f"{user.name} added category {c.name} ({c.group})", entity_type="category", entity_id=c.id, actor=user, data=body.model_dump(mode="json"), client=client_info(request))
    db.commit()
    return _category_json(c)


@router.patch("/categories/{category_id}")
def update_category(category_id: int, body: CategoryBody, request: Request, user: User = Depends(require_roles(Role.FINANCE_ADMIN)), db: Session = Depends(get_db)):
    c = db.get(Category, category_id)
    if c is None:
        raise HTTPException(404, "Not found.")
    before = _category_json(c)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    audit.record(db, action="category.updated", summary=f"{user.name} updated category {c.name}", entity_type="category", entity_id=c.id, actor=user, data={"before": before, "after": body.model_dump(mode="json")}, client=client_info(request))
    db.commit()
    return _category_json(c)


# ---------------------------------------------------------------- exchange rates


class RateBody(BaseModel):
    currency: str = Field(min_length=3, max_length=3, pattern="^[A-Za-z]{3}$")
    usd_per_unit: Decimal = Field(gt=0)
    effective_date: date


@router.get("/fx-rates")
def list_rates(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(FxRate).order_by(FxRate.currency, FxRate.effective_date.desc())).scalars()
    return [{"id": r.id, "currency": r.currency, "usd_per_unit": float(r.usd_per_unit), "units_per_usd": float(1 / r.usd_per_unit), "effective_date": r.effective_date.isoformat(), "source": r.source} for r in rows]


@router.post("/fx-rates", status_code=201)
def add_rate(body: RateBody, request: Request, user: User = Depends(require_roles(Role.FINANCE, Role.FINANCE_ADMIN)), db: Session = Depends(get_db)):
    cur = body.currency.upper()
    existing = db.execute(select(FxRate).where(FxRate.currency == cur, FxRate.effective_date == body.effective_date)).scalar()
    if existing:
        raise DomainError(f"There's already a {cur} rate for {body.effective_date:%d %b %Y}.", "duplicate")
    r = FxRate(currency=cur, usd_per_unit=body.usd_per_unit, effective_date=body.effective_date, source="finance", created_by_id=user.id)
    db.add(r)
    db.flush()
    audit.record(db, action="fx.rate_added", summary=f"{user.name} set 1 {cur} = {body.usd_per_unit} USD from {body.effective_date:%d %b %Y}", entity_type="fx_rate", entity_id=r.id, actor=user, data=body.model_dump(mode="json"), client=client_info(request))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- people


class UserPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    job_title: str | None = Field(None, max_length=120)
    department_id: int | None = None
    site_id: int | None = None
    manager_id: int | None = None
    roles: list[Literal["admin", "finance", "finance_admin", "auditor", "executive", "coo", "ceo"]] | None = None


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=120)
    job_title: str | None = Field(None, max_length=120)
    department_id: int | None = None
    site_id: int | None = None
    manager_id: int | None = None


def _person_json(u: User, report_counts: dict[int, int]) -> dict:
    return {**user_brief(u), "roles": u.roles, "manager": user_brief(u.manager), "department_id": u.department_id, "site_id": u.site_id, "direct_reports": report_counts.get(u.id, 0), "external_id": u.external_id}


@router.get("/users")
def list_users(q: str | None = None, include_inactive: bool = False, user: User = Depends(require_roles(Role.ADMIN, Role.FINANCE_ADMIN, Role.EXECUTIVE)), db: Session = Depends(get_db)):
    stmt = select(User).order_by(User.name)
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(User.name).like(like), func.lower(User.email).like(like), func.lower(User.job_title).like(like)))
    counts = dict(db.execute(select(User.manager_id, func.count()).where(User.is_active.is_(True)).group_by(User.manager_id)).all())
    return [_person_json(u, counts) for u in db.execute(stmt).scalars()]


@router.get("/departments")
def departments(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": d.id, "name": d.name, "head": user_brief(d.head)} for d in db.execute(select(Department).order_by(Department.name)).scalars()]


@router.get("/sites")
def sites(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": s.id, "name": s.name, "country": s.country, "currency": s.currency} for s in db.execute(select(Site).order_by(Site.name)).scalars()]


def _would_cycle(db: Session, user_id: int, manager_id: int | None) -> bool:
    seen = set()
    current = manager_id
    while current is not None:
        if current == user_id or current in seen:
            return True
        seen.add(current)
        current = db.execute(select(User.manager_id).where(User.id == current)).scalar()
    return False


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, request: Request, actor: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Not found.")
    changes = body.model_dump(exclude_unset=True)
    if "manager_id" in changes and _would_cycle(db, u.id, changes["manager_id"]):
        raise DomainError("That would make someone their own manager.", "cycle")
    if "roles" in changes and u.id == actor.id and Role.ADMIN not in changes["roles"]:
        raise DomainError("You can't remove your own administrator role.")
    before = {"roles": list(u.roles or []), "manager_id": u.manager_id, "department_id": u.department_id, "site_id": u.site_id, "job_title": u.job_title}
    for k, v in changes.items():
        setattr(u, k, sorted(set(v)) if k == "roles" else v)
    audit.record(db, action="user.updated", summary=f"{actor.name} updated {u.name}" + (f" (roles: {', '.join(u.roles) or 'none'})" if "roles" in changes else ""), entity_type="user", entity_id=u.id, actor=actor, data={"before": before, "changes": changes}, client=client_info(request))
    db.commit()
    counts = dict(db.execute(select(User.manager_id, func.count()).where(User.is_active.is_(True)).group_by(User.manager_id)).all())
    return _person_json(u, counts)


@router.post("/users", status_code=201)
def create_user(body: UserCreate, request: Request, actor: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.execute(select(User).where(func.lower(User.email) == email)).first():
        raise DomainError("Someone with that email already exists.", "duplicate")
    u = User(email=email, name=body.name.strip(), job_title=body.job_title, department_id=body.department_id, site_id=body.site_id, manager_id=body.manager_id, roles=[])
    db.add(u)
    db.flush()
    audit.record(db, action="user.created", summary=f"{actor.name} added {u.name} ({u.email})", entity_type="user", entity_id=u.id, actor=actor, data=body.model_dump(mode="json"), client=client_info(request))
    db.commit()
    return _person_json(u, {})


@router.post("/users/{user_id}/deactivate")
def deactivate(user_id: int, request: Request, actor: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Not found.")
    if u.has_role(*POSITION_ROLES):
        raise NotAllowed(f"{u.name} holds the {', '.join(ROLE_LABELS[r] for r in u.roles if r in POSITION_ROLES)} position. Give it to someone else first.")
    result = workflow.deactivate_user(db, actor, u, client_info(request))
    db.commit()
    return result
