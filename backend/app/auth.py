"""Authentication.

Production: single sign-on through the company identity provider (Microsoft Entra ID
via OpenID Connect). There are no Accord passwords.
Demo: one-click sign-in as any person in the demo organisation (ACCORD_DEMO_MODE).

Sessions are opaque random tokens in an HttpOnly cookie; only an HMAC of the token is
stored, so a database leak can't be replayed, and sessions can be revoked server-side.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.audit import ClientInfo
from app.config import get_settings
from app.db import get_db
from app.models import Role, User, UserSession, utcnow


def client_info(request: Request) -> ClientInfo:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None)
    return ClientInfo(ip=ip, user_agent=request.headers.get("user-agent"))


def _hash_token(token: str) -> str:
    return hmac.new(get_settings().session_secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def start_session(db: Session, user: User, method: str, client: ClientInfo) -> str:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            token_hash=_hash_token(token),
            user_id=user.id,
            auth_method=method,
            expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
            last_seen_at=utcnow(),
            ip=client.ip,
            user_agent=(client.user_agent or "")[:300] or None,
        )
    )
    audit.record(
        db,
        action="auth.signed_in",
        summary=f"{user.name} signed in" + (" (demo persona)" if method == "demo" else f" with {settings.oidc_provider_name}"),
        entity_type="user",
        entity_id=user.id,
        actor=user,
        data={"method": method},
        client=client,
    )
    return token


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def end_session(db: Session, request: Request, response: Response) -> None:
    settings = get_settings()
    token = request.cookies.get(settings.cookie_name)
    if token:
        s = db.execute(select(UserSession).where(UserSession.token_hash == _hash_token(token))).scalar()
        if s and s.revoked_at is None:
            s.revoked_at = utcnow()
    response.delete_cookie(settings.cookie_name, path="/")


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get(get_settings().cookie_name)
    if not token:
        return None
    s = db.execute(
        select(UserSession).where(
            UserSession.token_hash == _hash_token(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > func.now(),
        )
    ).scalar()
    if s is None or not s.user.is_active:
        return None
    now = utcnow()
    if s.last_seen_at is None or now - s.last_seen_at > timedelta(minutes=5):
        s.last_seen_at = now
        db.commit()
    request.state.auth_method = s.auth_method
    return s.user


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return user


def require_roles(*roles: Role):
    def dependency(user: User = Depends(current_user)) -> User:
        if not user.has_role(*roles):
            raise HTTPException(status_code=403, detail="You don't have access to this area.")
        return user

    return dependency


def find_or_provision_oidc_user(db: Session, claims: dict) -> User | None:
    """Match the signed-in identity to a person in the directory."""
    settings = get_settings()
    subject = claims.get("oid") or claims.get("sub")
    email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    user = None
    if subject:
        user = db.execute(select(User).where(User.external_id == subject)).scalar()
    if user is None and email:
        user = db.execute(select(User).where(func.lower(User.email) == email)).scalar()
        if user is not None and user.external_id is None and subject:
            user.external_id = subject
    if user is None and settings.oidc_jit_provisioning and email:
        domain = email.rsplit("@", 1)[-1]
        if settings.allowed_email_domains and domain not in settings.allowed_email_domains:
            return None
        user = User(email=email, name=claims.get("name") or email, external_id=subject, roles=[])
        db.add(user)
        db.flush()
        audit.record(db, action="user.provisioned", summary=f"{user.name} was added on first sign-in", entity_type="user", entity_id=user.id, actor=user)
    return user
