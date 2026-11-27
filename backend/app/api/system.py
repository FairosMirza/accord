import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import workflow
from app.auth import current_user
from app.config import get_settings
from app.db import get_db
from app.models import EmailMessage, User
from app.notifications import dispatch_queued_emails
from app.serializers import user_brief

demo_router = APIRouter(prefix="/api/demo", tags=["demo"])
jobs_router = APIRouter(prefix="/internal/jobs", tags=["jobs"])


def _require_demo():
    if not get_settings().demo_mode:
        raise HTTPException(404, "Not available.")


@demo_router.get("/outbox")
def outbox(to_user_id: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Demo only: every email Accord would have sent, so reviewers can see notifications."""
    _require_demo()
    stmt = select(EmailMessage).order_by(EmailMessage.id.desc()).limit(150)
    if to_user_id:
        stmt = stmt.where(EmailMessage.to_user_id == to_user_id)
    return [
        {"id": e.id, "to": user_brief(e.to_user), "to_email": e.to_email, "subject": e.subject, "kind": e.kind, "status": e.status, "created_at": e.created_at.isoformat(), "body_text": e.body_text}
        for e in db.execute(stmt).scalars()
    ]


@demo_router.get("/outbox/{email_id}")
def outbox_message(email_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_demo()
    e = db.get(EmailMessage, email_id)
    if e is None:
        raise HTTPException(404, "Not found.")
    return {"id": e.id, "to": user_brief(e.to_user), "subject": e.subject, "body_html": e.body_html, "created_at": e.created_at.isoformat()}


@demo_router.post("/run-reminders")
def demo_run_reminders(user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_demo()
    result = workflow.run_reminders(db)
    return result.__dict__


@demo_router.post("/reset")
def demo_reset(user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_demo()
    from app.seed import reset_demo

    # Release this request's own transaction first: it holds locks the schema drop would wait on.
    db.rollback()
    db.close()
    reset_demo()
    return {"ok": True}


@jobs_router.post("/reminders")
def scheduled_reminders(x_job_token: str | None = Header(None), db: Session = Depends(get_db)):
    expected = get_settings().job_token
    if not expected or not x_job_token or not hmac.compare_digest(expected, x_job_token):
        raise HTTPException(403, "Forbidden")
    result = workflow.run_reminders(db)
    sent = dispatch_queued_emails(db)
    return {**result.__dict__, "emails_sent": sent}
