"""In-app notifications and email.

Every email is stored in `email_messages` (and sent via SMTP when configured), so
"I never saw it" can be checked: we know what was sent, when, and when the approver
first opened the request.
"""

import logging
import smtplib
from decimal import Decimal
from email.message import EmailMessage as MimeMessage
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.directory import Directory
from app.models import ApprovalStep, EmailMessage, Notification, Role, SpendRequest, User, utcnow
from app.timeutil import company_today

log = logging.getLogger(__name__)


def fmt_money(amount: Decimal | None, currency: str) -> str:
    if amount is None:
        return "-"
    return f"{currency} {Decimal(amount):,.2f}"


def amount_line(req: SpendRequest) -> str:
    base = get_settings().base_currency
    text = fmt_money(req.total_amount, req.currency)
    if req.currency != base:
        text += f" (about {fmt_money(req.total_usd, base)})"
    if req.payment_type == "recurring":
        text += f" over the term, {fmt_money(req.amount, req.currency)} {req.billing_period}"
    return text


def _link(req: SpendRequest | None) -> str:
    base = get_settings().base_url.rstrip("/")
    return f"{base}/requests/{req.ref}" if req else base


def _summary_rows(req: SpendRequest) -> list[tuple[str, str]]:
    rows = [
        ("Request", f"{req.ref}: {req.title}"),
        ("Requested by", req.requester.name if req.requester else ""),
        ("Amount", amount_line(req)),
        ("Supplier", req.supplier or "-"),
        ("Category", req.category.name if req.category else "-"),
    ]
    if req.project:
        rows.append(("Project / trip", req.project.name))
    return rows


def render_email(title: str, body: str, req: SpendRequest | None, cta: str) -> tuple[str, str]:
    app_name = get_settings().app_name
    link = _link(req)
    rows = _summary_rows(req) if req else []
    text_rows = "\n".join(f"{k}: {v}" for k, v in rows)
    text = f"{title}\n\n{body}\n\n{text_rows}\n\n{cta}: {link}\n\n— {app_name}"
    row_html = "".join(
        f'<tr><td style="padding:6px 0;color:#6b7280;font-size:13px;width:120px;vertical-align:top">{escape(k)}</td>'
        f'<td style="padding:6px 0;color:#111827;font-size:14px">{escape(v)}</td></tr>'
        for k, v in rows
    )
    html = f"""<!doctype html><html><body style="margin:0;background:#f4f5f2;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:24px 12px"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#ffffff;border-radius:16px;padding:28px">
<tr><td style="font-size:13px;font-weight:600;letter-spacing:.04em;color:#15803d;text-transform:uppercase">{escape(app_name)}</td></tr>
<tr><td style="padding-top:10px;font-size:20px;font-weight:600;color:#111827">{escape(title)}</td></tr>
<tr><td style="padding-top:8px;font-size:15px;line-height:1.5;color:#374151">{escape(body)}</td></tr>
<tr><td style="padding-top:16px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{row_html}</table></td></tr>
<tr><td style="padding-top:22px"><a href="{escape(link)}" style="display:inline-block;background:#15803d;color:#ffffff;text-decoration:none;font-weight:600;font-size:15px;padding:12px 22px;border-radius:10px">{escape(cta)}</a></td></tr>
<tr><td style="padding-top:22px;font-size:12px;color:#9ca3af">You're receiving this because of your role in {escape(app_name)}. Sign in with your normal work account.</td></tr>
</table></td></tr></table></body></html>"""
    return text, html


def notify(
    db: Session,
    user: User,
    *,
    kind: str,
    title: str,
    body: str,
    request: SpendRequest | None = None,
    email: bool = True,
    cta: str = "Open in Accord",
) -> Notification:
    note = Notification(
        user_id=user.id,
        request_id=request.id if request else None,
        kind=kind,
        title=title,
        body=body,
        link=f"/requests/{request.ref}" if request else None,
    )
    db.add(note)
    if email and user.is_active:
        text, html = render_email(title, body, request, cta)
        queued = get_settings().email_backend == "smtp"
        db.add(
            EmailMessage(
                to_user_id=user.id,
                to_email=user.email,
                subject=f"{title}" if not request else f"[{request.ref}] {title}",
                body_text=text,
                body_html=html,
                kind=kind,
                request_id=request.id if request else None,
                status="queued" if queued else "stored",
            )
        )
    return note


def notify_approvers(db: Session, req: SpendRequest, step: ApprovalStep, *, reminder: bool = False) -> list[User]:
    """Tell the approver, and anyone currently standing in for them."""
    why = ", ".join(step.reasons)
    if reminder:
        title = f"Reminder: {req.requester.name}'s request is still waiting for you"
        body = f"{req.title} has been waiting since you were notified. You're approving as: {why}."
    else:
        title = f"Approval needed: {req.title}"
        body = f"{req.requester.name} needs your approval before spending. You're approving as: {why}."
    recipients = [step.approver]
    for delegate in Directory(db).active_delegates_for(step.approver_id, company_today()):
        if delegate.id == req.requester_id or delegate.id in {u.id for u in recipients}:
            continue
        if any(s.id != step.id and s.status != "skipped" and delegate.id in (s.approver_id, s.acted_by_id) for s in req.current_steps):
            continue  # already an approver on this request; they can't add a second approval
        recipients.append(delegate)
    for user in recipients:
        stand_in = user.id != step.approver_id
        notify(
            db,
            user,
            kind="approval_reminder" if reminder else "approval_needed",
            title=title if not stand_in else f"{title} (standing in for {step.approver.name})",
            body=body,
            request=req,
            cta="Review and approve",
        )
    return recipients


def notify_finance(db: Session, req: SpendRequest, *, title: str, body: str, email: bool = False) -> None:
    for user in Directory(db).holders_of({Role.FINANCE, Role.FINANCE_ADMIN}):
        if user.id != req.requester_id:
            notify(db, user, kind="finance", title=title, body=body, request=req, email=email)


def dispatch_queued_emails(db: Session, limit: int = 50) -> int:
    """Send queued emails over SMTP. Safe to call repeatedly; failures stay visible."""
    settings = get_settings()
    if settings.email_backend != "smtp" or not settings.smtp_host:
        return 0
    queued = list(
        db.execute(select(EmailMessage).where(EmailMessage.status == "queued").order_by(EmailMessage.id).limit(limit)).scalars()
    )
    if not queued:
        return 0
    sent = 0
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            for em in queued:
                msg = MimeMessage()
                msg["From"] = settings.email_from
                msg["To"] = em.to_email
                msg["Subject"] = em.subject
                msg.set_content(em.body_text)
                msg.add_alternative(em.body_html, subtype="html")
                try:
                    smtp.send_message(msg)
                    em.status, em.sent_at, em.error = "sent", utcnow(), None
                    sent += 1
                except smtplib.SMTPException as exc:  # keep going; record the failure
                    em.status, em.error = "failed", str(exc)[:500]
    except (OSError, smtplib.SMTPException) as exc:
        log.warning("SMTP unavailable: %s", exc)
    db.commit()
    return sent
