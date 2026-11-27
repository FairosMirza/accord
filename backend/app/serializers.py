"""Model -> JSON shapes used by the API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.invoicing import amendment_change, excess, live_invoices, next_step
from app.models import (
    ApprovalStep,
    AuditEvent,
    Delegation,
    Invoice,
    InvoiceStatus,
    RequestStatus,
    SpendRequest,
    User,
)
from app.permissions import RequestPermissions
from app.timeutil import company_today
from app.workflow import contract_end, diff_snapshots


def _iso(v: date | datetime | None) -> str | None:
    return v.isoformat() if v else None


def _num(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


def initials(name: str) -> str:
    parts = [p for p in name.replace("-", " ").split() if p]
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper() if parts else "?"


def user_brief(u: User | None) -> dict[str, Any] | None:
    if u is None:
        return None
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "job_title": u.job_title,
        "initials": initials(u.name),
        "department": u.department.name if u.department else None,
        "site": u.site.name if u.site else None,
        "is_active": u.is_active,
    }


def finance_state(req: SpendRequest) -> dict[str, Any] | None:
    if req.approved_total_usd is None:
        return None
    invoices = live_invoices(req)
    invoiced = sum((i.amount_usd for i in invoices), Decimal(0))
    paid = sum((i.amount_usd for i in invoices if i.status == InvoiceStatus.PAID), Decimal(0))
    if not invoices:
        state = "awaiting_invoice"
    elif any(i.status in (InvoiceStatus.RECEIVED, InvoiceStatus.QUERIED) for i in invoices):
        state = "awaiting_payment"
    else:
        state = "paid"
    over = excess(req)
    step = next_step(req)
    flagged = [i for i in invoices if i.exceeds_approval]
    return {
        "state": state,
        "invoiced_usd": float(invoiced),
        "paid_usd": float(paid),
        "remaining_usd": float(Decimal(req.approved_total_usd) - invoiced),
        "invoice_count": len(invoices),
        "over_approval": bool(flagged),
        "excess": {
            "over_usd": float(over.over_usd),
            "invoiced_usd": float(over.invoiced_usd),
            "approved_usd": float(over.approved_usd),
            "currency": over.currency,
            "over_amount": _num(over.over_amount),
            "invoiced_amount": _num(over.invoiced_amount),
            "approved_amount": _num(req.approved_total_amount),
            "invoice_id": flagged[-1].id,
            "invoice_number": flagged[-1].invoice_number,
            "note": flagged[-1].override_reason,
        }
        if over
        else None,
        "next_step": {"kind": step.kind, "owner": user_brief(step.owner), "label": step.label} if step else None,
    }


def request_summary(req: SpendRequest) -> dict[str, Any]:
    step = req.pending_step if req.status == RequestStatus.PENDING else None
    return {
        "id": req.id,
        "ref": req.ref,
        "title": req.title,
        "status": req.status,
        "requester": user_brief(req.requester),
        "department": req.department.name if req.department else None,
        "site": req.site.name if req.site else None,
        "category": {"id": req.category.id, "name": req.category.name, "group": req.category.group} if req.category else None,
        "project": {"id": req.project.id, "name": req.project.name, "kind": req.project.kind, "code": req.project.code} if req.project else None,
        "supplier": req.supplier,
        "currency": req.currency,
        "amount": _num(req.amount),
        "total_amount": _num(req.total_amount),
        "total_usd": _num(req.total_usd),
        "approved_total_usd": _num(req.approved_total_usd),
        "approved_total_amount": _num(req.approved_total_amount),
        "payment_type": req.payment_type,
        "billing_period": req.billing_period,
        "term_months": req.term_months,
        "is_confidential": req.is_confidential,
        "has_quote": any(a.kind == "quote" for a in req.attachments),
        "no_quote_reason": req.no_quote_reason,
        "amendment_in_progress": req.is_amendment_in_progress,
        "change": amendment_change(req),
        "waiting_for": user_brief(step.approver) if step else None,
        "waiting_reasons": step.reasons if step else [],
        "waiting_since": _iso(step.activated_at) if step else None,
        "finance": finance_state(req),
        "revision": req.revision,
        "created_at": _iso(req.created_at),
        "submitted_at": _iso(req.submitted_at),
        "approved_at": _iso(req.approved_at),
        "decided_at": _iso(req.decided_at),
        "updated_at": _iso(req.updated_at),
    }


def step_json(s: ApprovalStep) -> dict[str, Any]:
    return {
        "id": s.id,
        "revision": s.revision,
        "sequence": s.sequence,
        "status": s.status,
        "approver": user_brief(s.approver),
        "acted_by": user_brief(s.acted_by),
        "on_behalf_of": user_brief(s.on_behalf_of),
        "reasons": s.reasons,
        "routing_note": s.routing_note,
        "decision_reason": s.decision_reason,
        "comment": s.comment,
        "activated_at": _iso(s.activated_at),
        "acted_at": _iso(s.acted_at),
        "first_viewed_at": _iso(s.first_viewed_at),
        "reminder_count": s.reminder_count,
        "approved_content_hash": s.approved_content_hash,
    }


def invoice_json(i: Invoice) -> dict[str, Any]:
    replaces = next((x for x in i.request.invoices if x.id == i.replaces_invoice_id), None) if i.replaces_invoice_id else None
    return {
        "id": i.id,
        "invoice_number": i.invoice_number,
        "invoice_date": _iso(i.invoice_date),
        "supplier": i.supplier,
        "currency": i.currency,
        "amount": _num(i.amount),
        "amount_usd": _num(i.amount_usd),
        "status": i.status,
        "exceeds_approval": i.exceeds_approval,
        "override_reason": i.override_reason,
        "notes": i.notes,
        "received_by": user_brief(i.received_by),
        "received_at": _iso(i.received_at),
        "paid_by": user_brief(i.paid_by),
        "paid_on": _iso(i.paid_on),
        "payment_reference": i.payment_reference,
        "query_reason": i.query_reason,
        "queried_by": user_brief(i.queried_by),
        "queried_at": _iso(i.queried_at),
        "query_resolution": i.query_resolution,
        "replaces_invoice_number": replaces.invoice_number if replaces else None,
        "void_reason": i.void_reason,
        "voided_by": user_brief(i.voided_by),
        "voided_at": _iso(i.voided_at),
        "attachments": [{"id": a.id, "filename": a.filename, "size_bytes": a.size_bytes} for a in i.attachments],
    }


def audit_json(e: AuditEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "occurred_at": _iso(e.occurred_at),
        "actor": user_brief(e.actor),
        "on_behalf_of": user_brief(e.on_behalf_of),
        "action": e.action,
        "entity_type": e.entity_type,
        "entity_id": e.entity_id,
        "summary": e.summary,
        "data": e.data,
        "ip": e.ip,
        "hash": e.hash,
    }


def request_detail(db: Session, req: SpendRequest, perms: RequestPermissions) -> dict[str, Any]:
    timeline = db.execute(select(AuditEvent).where(AuditEvent.request_id == req.id).order_by(AuditEvent.id)).scalars()
    revisions = []
    prev_data = None
    for r in req.revisions:
        revisions.append(
            {
                "number": r.number,
                "kind": r.kind,
                "status": r.status,
                "reason": r.reason,
                "total_usd": _num(r.total_usd),
                "content_hash": r.content_hash,
                "created_at": _iso(r.created_at),
                "created_by": user_brief(r.created_by),
                "decided_at": _iso(r.decided_at),
                "changes": diff_snapshots(prev_data, r.data) if prev_data else [],
            }
        )
        prev_data = r.data
    end = contract_end(req)
    return {
        **request_summary(req),
        "description": req.description,
        "needed_by": _iso(req.needed_by),
        "start_date": _iso(req.start_date),
        "contract_end": _iso(end),
        "fx_rate": _num(req.fx_rate),
        "policy_version": req.policy_version.version if req.policy_version else None,
        "approved_revision": req.approved_revision,
        "steps": [step_json(s) for s in req.steps],
        "revisions": revisions,
        "attachments": [
            {
                "id": a.id,
                "kind": a.kind,
                "filename": a.filename,
                "content_type": a.content_type,
                "size_bytes": a.size_bytes,
                "sha256": a.sha256,
                "revision": a.revision,
                "uploaded_by": user_brief(a.uploaded_by),
                "uploaded_at": _iso(a.uploaded_at),
                "invoice_id": a.invoice_id,
            }
            for a in req.attachments
        ],
        "invoices": [invoice_json(i) for i in req.invoices],
        "comments": [
            {"id": c.id, "author": user_brief(c.author), "body": c.body, "created_at": _iso(c.created_at)} for c in req.comments
        ],
        "timeline": [audit_json(e) for e in timeline],
        "permissions": perms.__dict__,
    }


def delegation_json(d: Delegation) -> dict[str, Any]:
    today = company_today()
    if d.revoked_at:
        state = "ended"
    elif d.ends_on < today:
        state = "expired"
    elif d.starts_on > today:
        state = "scheduled"
    else:
        state = "active"
    return {
        "id": d.id,
        "principal": user_brief(d.principal),
        "delegate": user_brief(d.delegate),
        "starts_on": _iso(d.starts_on),
        "ends_on": _iso(d.ends_on),
        "note": d.note,
        "state": state,
        "created_at": _iso(d.created_at),
        "revoked_at": _iso(d.revoked_at),
    }

