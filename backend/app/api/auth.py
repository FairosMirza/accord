from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import audit
from app.auth import (
    client_info,
    current_user,
    end_session,
    find_or_provision_oidc_user,
    optional_user,
    set_session_cookie,
    start_session,
)
from app.config import get_settings
from app.db import get_db
from app.directory import Directory
from app.models import POSITION_ROLES, Delegation, DemoPersona, Notification, Role, User
from app.reports import waiting_for
from app.serializers import delegation_json, user_brief
from app.timeutil import company_today

router = APIRouter(prefix="/api/auth", tags=["auth"])

_oauth = None


def _oidc_client():
    global _oauth
    settings = get_settings()
    if not settings.oidc_enabled:
        raise HTTPException(404, "Single sign-on is not configured.")
    if _oauth is None:
        from authlib.integrations.starlette_client import OAuth

        _oauth = OAuth()
        _oauth.register(
            name="sso",
            server_metadata_url=f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            client_kwargs={"scope": settings.oidc_scopes, "code_challenge_method": "S256"},
        )
    return _oauth.sso


@router.get("/config")
def auth_config():
    s = get_settings()
    return {
        "app_name": s.app_name,
        "environment": s.environment,
        "demo_mode": s.demo_mode,
        "sso_enabled": s.oidc_enabled,
        "sso_provider": s.oidc_provider_name,
    }


def _require_demo():
    if not get_settings().demo_mode:
        raise HTTPException(404, "Not available.")


@router.get("/personas")
def personas(db: Session = Depends(get_db)):
    _require_demo()
    rows = db.execute(select(DemoPersona).order_by(DemoPersona.sort_order)).scalars()
    return [
        {"user": user_brief(p.user), "roles": p.user.roles, "headline": p.headline, "blurb": p.blurb}
        for p in rows
        if p.user.is_active
    ]


@router.get("/people")
def demo_people(q: str = "", db: Session = Depends(get_db)):
    """Demo only: sign in as anyone in the organisation, not just the featured personas."""
    _require_demo()
    stmt = select(User).where(User.is_active.is_(True)).order_by(User.name).limit(25)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(User.name).like(like), func.lower(User.job_title).like(like)))
    return [user_brief(u) for u in db.execute(stmt).scalars()]


class DemoLogin(BaseModel):
    user_id: int


@router.post("/demo")
def demo_login(body: DemoLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    _require_demo()
    user = db.get(User, body.user_id)
    if user is None or not user.is_active:
        raise HTTPException(404, "Person not found.")
    end_session(db, request, response)
    token = start_session(db, user, "demo", client_info(request))
    db.commit()
    set_session_cookie(response, token)
    return {"ok": True}


@router.get("/login")
async def sso_login(request: Request):
    client = _oidc_client()
    redirect_uri = f"{get_settings().base_url.rstrip('/')}/api/auth/callback"
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def sso_callback(request: Request, db: Session = Depends(get_db)):
    client = _oidc_client()
    try:
        token = await client.authorize_access_token(request)
    except Exception:  # state mismatch, expired code, invalid token signature...
        return RedirectResponse("/signin?error=sso_failed", status_code=303)
    claims = token.get("userinfo") or {}
    user = find_or_provision_oidc_user(db, claims)
    if user is None or not user.is_active:
        db.rollback()
        return RedirectResponse("/signin?error=not_registered", status_code=303)
    session_token = start_session(db, user, "oidc", client_info(request))
    db.commit()
    response = RedirectResponse("/", status_code=303)
    set_session_cookie(response, session_token)
    return response


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db), user: User | None = Depends(optional_user)):
    end_session(db, request, response)
    if user is not None:
        audit.record(db, action="auth.signed_out", summary=f"{user.name} signed out", entity_type="user", entity_id=user.id, actor=user, client=client_info(request))
    db.commit()
    return {"ok": True}


def capabilities(db: Session, user: User) -> dict:
    directory = Directory(db)
    has_reports = directory.has_reports(user.id)
    heads = bool(directory.headed_department_ids(user.id))
    covering = directory.principals_delegating_to(user.id, company_today())
    return {
        "sees_everything": user.sees_everything,
        "is_finance": user.has_role(Role.FINANCE, Role.FINANCE_ADMIN),
        "can_view_finance": user.has_role(Role.FINANCE, Role.FINANCE_ADMIN, Role.EXECUTIVE, Role.AUDITOR),
        "can_manage_policy": user.has_role(Role.FINANCE_ADMIN),
        "can_manage_reference_data": user.has_role(Role.FINANCE_ADMIN, Role.FINANCE),
        "can_manage_people": user.has_role(Role.ADMIN),
        "can_view_audit": user.sees_everything,
        "is_manager": has_reports,
        "is_department_head": heads,
        "is_approver": has_reports or heads or user.has_role(*POSITION_ROLES) or bool(covering),
        "can_create_projects": has_reports or user.has_role(Role.FINANCE_ADMIN, Role.ADMIN, Role.EXECUTIVE),
        "read_only": user.has_role(Role.AUDITOR) and not user.has_role(Role.FINANCE, Role.FINANCE_ADMIN, Role.ADMIN),
    }


@router.get("/me")
def me(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = company_today()
    my_cover = db.execute(
        select(Delegation)
        .where(Delegation.principal_id == user.id, Delegation.revoked_at.is_(None), Delegation.ends_on >= today)
        .order_by(Delegation.starts_on)
    ).scalars()
    covering = db.execute(
        select(Delegation)
        .where(Delegation.delegate_id == user.id, Delegation.revoked_at.is_(None), Delegation.ends_on >= today)
        .order_by(Delegation.starts_on)
    ).scalars()
    unread = db.execute(select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.read_at.is_(None))).scalar()
    return {
        "user": {**user_brief(user), "roles": user.roles, "manager": user_brief(user.manager)},
        "capabilities": capabilities(db, user),
        "my_cover": [delegation_json(d) for d in my_cover],
        "covering": [delegation_json(d) for d in covering],
        "counts": {"waiting_for_me": len(waiting_for(db, user)), "unread_notifications": unread or 0},
        "auth_method": getattr(request.state, "auth_method", None),
        "demo_mode": get_settings().demo_mode,
    }
