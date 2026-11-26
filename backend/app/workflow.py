"""Request lifecycle.

draft -> pending -> approved -> closed
                 -> rejected
                 -> returned -> (edit) -> pending ...
pending/returned -> withdrawn;  approved (no invoices) -> cancelled
approved -> amendment: within tolerance = applied immediately, otherwise pending again
            (the previous approval stays in force until the change is decided)
"""

from __future__ import annotations

import calendar
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app import audit
from app.audit import ClientInfo
from app.directory import Directory
from app.errors import Conflict, DomainError, NotAllowed, NotFound
from app.fx import money, to_usd, usd_per_unit
from app.models import (
    ApprovalStep,
    Attachment,
    AttachmentKind,
    Category,
    Comment,
    Delegation,
    Invoice,
    InvoiceStatus,
    PaymentType,
    Project,
    RequestRevision,
    RequestStatus,
    Role,
    SpendRequest,
    StepStatus,
    User,
    UserSession,
    utcnow,
)
from app.notifications import amount_line, fmt_money, notify, notify_approvers, notify_finance
from app.permissions import acting_principal, request_permissions, stand_in_already_in_chain
from app.policy import (
    PlannedStep,
    PolicyDocument,
    RouteInput,
    RuleApprover,
    assess_amendment,
    commitment_total,
    compute_route,
    current_policy,
    resolve_approver,
    stand_in_problem,
)
from app.storage import validate_and_store
from app.timeutil import company_today

EDITABLE_FIELDS = (
    "title",
    "description",
    "supplier",
    "category_id",
    "project_id",
    "currency",
    "amount",
    "payment_type",
    "billing_period",
    "term_months",
    "start_date",
    "needed_by",
    "no_quote_reason",
    "is_confidential",
)
MAX_DELEGATION_DAYS = 92


# ---------------------------------------------------------------- helpers


def next_ref(db: Session) -> str:
    n = db.execute(text("SELECT nextval('request_ref_seq')")).scalar_one()
    return f"AC-{n}"


def get_request(db: Session, ref: str) -> SpendRequest:
    req = db.execute(select(SpendRequest).where(SpendRequest.ref == ref.upper())).scalar()
    if req is None:
        raise NotFound("Request not found.")
    return req


def _route_input(req: SpendRequest) -> RouteInput:
    if req.category is None:
        raise DomainError("Choose a category.", "category_required")
    return RouteInput(
        requester=req.requester,
        category=req.category,
        department_id=req.department_id,
        site_id=req.site_id,
        total_usd=Decimal(req.total_usd),
    )


def _apply_fields(db: Session, req: SpendRequest, data: dict[str, Any], policy: PolicyDocument, *, keep_rate: bool = False) -> None:
    for key in EDITABLE_FIELDS:
        if key in data and key not in ("category_id", "project_id"):
            setattr(req, key, data[key])
    # Set relationships (not just FK columns) so validation below sees the new values.
    if "category_id" in data:
        category = db.get(Category, data["category_id"]) if data["category_id"] is not None else None
        if data["category_id"] is not None and (category is None or not category.is_active):
            raise DomainError("That category isn't available.", "category_invalid")
        req.category = category
        if category is not None and "is_confidential" not in data and category.confidential_default:
            req.is_confidential = True
    if "project_id" in data:
        project = db.get(Project, data["project_id"]) if data["project_id"] is not None else None
        if data["project_id"] is not None and (project is None or not project.is_active):
            raise DomainError("That project or trip isn't open for new spend.", "project_invalid")
        req.project = project
    req.title = (req.title or "").strip()
    req.currency = (req.currency or "USD").upper()
    if req.payment_type != PaymentType.RECURRING:
        req.payment_type = PaymentType.ONE_OFF
        req.billing_period = None
        req.term_months = None
    if req.amount is None:
        req.amount = Decimal(0)
    req.amount = money(req.amount)
    if req.amount < 0:
        raise DomainError("The amount can't be negative.", "amount_invalid")
    total, _ = commitment_total(req.amount, req.payment_type, req.billing_period, req.term_months, policy.rolling_term_months)
    req.total_amount = money(total)
    if not keep_rate or req.fx_rate is None:
        req.fx_rate = usd_per_unit(db, req.currency, company_today())
    req.total_usd = to_usd(req.total_amount, req.fx_rate)


def _check_ready(req: SpendRequest) -> None:
    problems = []
    if not req.title:
        problems.append("Give the request a short title.")
    if req.amount is None or req.amount <= 0:
        problems.append("Enter an amount greater than zero.")
    if req.category is None:
        problems.append("Choose a category.")
    if not (req.description or "").strip():
        problems.append("Explain what it's for, so approvers can decide.")
    if not (req.supplier or "").strip():
        problems.append("Say who you're paying.")
    has_quote = any(a.kind == AttachmentKind.QUOTE for a in req.attachments)
    if req.category is not None and req.category.quote_required and not has_quote and not (req.no_quote_reason or "").strip():
        problems.append("Attach a quote, or explain why there isn't one.")
    if problems:
        raise DomainError(" ".join(problems), "incomplete")


def snapshot(req: SpendRequest) -> dict[str, Any]:
    return {
        "title": req.title,
        "description": req.description,
        "supplier": req.supplier,
        "category": {"id": req.category_id, "name": req.category.name, "group": req.category.group} if req.category else None,
        "project": {"id": req.project_id, "name": req.project.name, "kind": req.project.kind} if req.project else None,
        "department_id": req.department_id,
        "site_id": req.site_id,
        "currency": req.currency,
        "amount": str(req.amount),
        "payment_type": req.payment_type,
        "billing_period": req.billing_period,
        "term_months": req.term_months,
        "start_date": req.start_date.isoformat() if req.start_date else None,
        "total_amount": str(req.total_amount),
        "fx_rate": str(req.fx_rate),
        "total_usd": str(req.total_usd),
        "needed_by": req.needed_by.isoformat() if req.needed_by else None,
        "no_quote_reason": req.no_quote_reason,
        "is_confidential": req.is_confidential,
        "attachments": [
            {"id": a.id, "filename": a.filename, "sha256": a.sha256, "kind": a.kind}
            for a in req.attachments
            if a.kind != AttachmentKind.INVOICE
        ],
    }


def _hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _restore(req: SpendRequest, data: dict[str, Any]) -> None:
    req.title = data["title"]
    req.description = data["description"]
    req.supplier = data["supplier"]
    req.category_id = data["category"]["id"] if data.get("category") else None
    req.project_id = data["project"]["id"] if data.get("project") else None
    req.currency = data["currency"]
    req.amount = Decimal(data["amount"])
    req.payment_type = data["payment_type"]
    req.billing_period = data["billing_period"]
    req.term_months = data["term_months"]
    req.start_date = date.fromisoformat(data["start_date"]) if data.get("start_date") else None
    req.total_amount = Decimal(data["total_amount"])
    req.fx_rate = Decimal(data["fx_rate"])
    req.total_usd = Decimal(data["total_usd"])
    req.needed_by = date.fromisoformat(data["needed_by"]) if data.get("needed_by") else None
    req.no_quote_reason = data["no_quote_reason"]
    req.is_confidential = data["is_confidential"]
    db = Session.object_session(req)
    if db is not None:
        db.flush()
        db.refresh(req, ["category", "project"])


_DIFF_LABELS = {
    "title": "Title",
    "supplier": "Supplier",
    "currency": "Currency",
    "amount": "Amount",
    "total_amount": "Total",
    "total_usd": "Total (USD)",
    "payment_type": "Payment type",
    "billing_period": "Billing",
    "term_months": "Term (months)",
    "start_date": "Start date",
    "needed_by": "Needed by",
    "is_confidential": "Confidential",
    "description": "Description",
}


def diff_snapshots(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    one_off = new.get("payment_type") == PaymentType.ONE_OFF and old.get("payment_type") == PaymentType.ONE_OFF
    changes = [
        {"field": label, "from": old.get(key), "to": new.get(key)}
        for key, label in _DIFF_LABELS.items()
        if old.get(key) != new.get(key) and not (one_off and key == "total_amount")
    ]
    for key, label in (("category", "Category"), ("project", "Project / trip")):
        o, n = (old.get(key) or {}).get("name"), (new.get(key) or {}).get("name")
        if o != n:
            changes.append({"field": label, "from": o, "to": n})
    old_files = {a["id"] for a in old.get("attachments", [])}
    added = [a["filename"] for a in new.get("attachments", []) if a["id"] not in old_files]
    if added:
        changes.append({"field": "Documents added", "from": None, "to": ", ".join(added)})
    return changes


def _current_revision(req: SpendRequest) -> RequestRevision:
    return next(r for r in req.revisions if r.number == req.revision)


def _new_revision(db: Session, req: SpendRequest, *, kind: str, actor: User, reason: str | None) -> RequestRevision:
    db.flush()
    db.refresh(req, ["attachments", "category", "project"])
    data = snapshot(req)
    rev = RequestRevision(
        number=req.revision,
        kind=kind,
        status="pending",
        data=data,
        content_hash=_hash(data),
        total_usd=req.total_usd,
        reason=reason,
        created_by_id=actor.id,
    )
    req.revisions.append(rev)
    return rev


def _create_steps(req: SpendRequest, route: list[PlannedStep]) -> None:
    now = utcnow()
    for i, planned in enumerate(route, start=1):
        step = ApprovalStep(
            revision=req.revision,
            sequence=i,
            approver_id=planned.approver.id,
            position_role=planned.position_role,
            reasons=planned.reasons,
            rule_keys=planned.rule_keys,
            routing_note="; ".join(planned.notes) or None,
            status=StepStatus.PENDING if i == 1 else StepStatus.WAITING,
            activated_at=now if i == 1 else None,
        )
        step.approver = planned.approver
        req.steps.append(step)
    req.current_step = 1


def _route_summary(route: list[PlannedStep]) -> list[dict[str, Any]]:
    return [
        {"approver_id": s.approver.id, "approver": s.approver.name, "reasons": s.reasons, "notes": s.notes}
        for s in route
    ]


def _skip_open_steps(req: SpendRequest) -> None:
    for s in req.current_steps:
        if s.status in (StepStatus.PENDING, StepStatus.WAITING):
            s.status = StepStatus.SKIPPED


def _actor_label(actor: User, principal: User | None) -> str:
    return f"{actor.name} (on behalf of {principal.name})" if principal else actor.name


# ---------------------------------------------------------------- drafting and submission


def create_draft(db: Session, actor: User, data: dict[str, Any]) -> SpendRequest:
    _, policy = current_policy(db)
    req = SpendRequest(
        ref=next_ref(db),
        requester=actor,
        department_id=actor.department_id,
        site_id=actor.site_id,
        status=RequestStatus.DRAFT,
        revision=1,
        currency="USD",
        amount=Decimal(0),
        payment_type=PaymentType.ONE_OFF,
    )
    _apply_fields(db, req, data, policy)
    db.add(req)
    db.flush()
    return req


def update_draft(db: Session, actor: User, req: SpendRequest, data: dict[str, Any]) -> SpendRequest:
    if req.requester_id != actor.id:
        raise NotAllowed("Only the requester can edit this request.")
    if req.status not in (RequestStatus.DRAFT, RequestStatus.RETURNED):
        raise Conflict("This request can't be edited now. Approved requests can be changed with 'Change request'.")
    _, policy = current_policy(db)
    _apply_fields(db, req, data, policy)
    return req


def delete_draft(db: Session, actor: User, req: SpendRequest) -> None:
    if req.requester_id != actor.id or req.status != RequestStatus.DRAFT:
        raise NotAllowed("Only unsubmitted drafts can be deleted.")
    db.delete(req)


def preview_route(db: Session, actor: User, data: dict[str, Any]) -> dict[str, Any]:
    """Who would approve this, without saving anything. Powers the live preview on the form."""
    pv, policy = current_policy(db)
    probe = SpendRequest(
        requester=actor,
        department_id=actor.department_id,
        site_id=actor.site_id,
        currency="USD",
        amount=Decimal(0),
        payment_type=PaymentType.ONE_OFF,
    )
    try:
        _apply_fields(db, probe, data, policy)
        if probe.category is None:
            return {"ready": False, "total_amount": str(probe.total_amount), "total_usd": str(probe.total_usd), "steps": []}
        route = compute_route(policy, _route_input(probe), Directory(db))
        return {
            "ready": True,
            "policy_version": pv.version,
            "total_amount": str(probe.total_amount),
            "total_usd": str(probe.total_usd),
            "fx_rate": str(probe.fx_rate),
            "steps": [
                {"approver": {"id": s.approver.id, "name": s.approver.name, "job_title": s.approver.job_title}, "reasons": s.reasons, "notes": s.notes}
                for s in route
            ],
        }
    finally:
        db.expunge(probe) if probe in db else None
        db.rollback()


def submit(db: Session, actor: User, req: SpendRequest, client: ClientInfo) -> SpendRequest:
    if req.requester_id != actor.id:
        raise NotAllowed("Only the requester can submit this request.")
    if req.status not in (RequestStatus.DRAFT, RequestStatus.RETURNED):
        raise Conflict("This request has already been submitted.")
    pv, policy = current_policy(db)
    _apply_fields(db, req, {}, policy)
    _check_ready(req)
    route = compute_route(policy, _route_input(req), Directory(db))
    kind = "submission"
    if req.status == RequestStatus.RETURNED:
        req.revision += 1
        kind = "resubmission"
    rev = _new_revision(db, req, kind=kind, actor=actor, reason=None)
    _create_steps(req, route)
    req.status = RequestStatus.PENDING
    req.policy_version_id = pv.id
    req.submitted_at = req.submitted_at or utcnow()
    req.decided_at = None
    db.flush()
    audit.record(
        db,
        action="request.submitted" if kind == "submission" else "request.resubmitted",
        summary=f"{actor.name} {'submitted' if kind == 'submission' else 'resubmitted'} {req.ref} for {amount_line(req)}",
        entity_type="request",
        entity_id=req.ref,
        actor=actor,
        request=req,
        data={"revision": req.revision, "content_hash": rev.content_hash, "policy_version": pv.version, "route": _route_summary(route)},
        client=client,
    )
    notify_approvers(db, req, req.pending_step)
    return req


# ---------------------------------------------------------------- decisions


def _actionable_step(db: Session, actor: User, req: SpendRequest) -> tuple[ApprovalStep, User | None]:
    if req.status != RequestStatus.PENDING or req.pending_step is None:
        raise Conflict("This request isn't waiting for approval.")
    if actor.id == req.requester_id:
        raise NotAllowed("You can't approve your own request.")
    step = req.pending_step
    allowed, principal = acting_principal(db, actor, step)
    if not allowed:
        covering = Directory(db).active_delegation(step.approver_id, actor.id, company_today()) is not None
        if covering and stand_in_already_in_chain(actor, step):
            raise NotAllowed(f"You're already an approver on this request, so you can't also approve it for {step.approver.name}. It stays with them.")
        raise NotAllowed(f"This request is waiting for {step.approver.name}, not you.")
    return step, principal


def approve(db: Session, actor: User, req: SpendRequest, comment: str | None, client: ClientInfo) -> SpendRequest:
    step, principal = _actionable_step(db, actor, req)
    now = utcnow()
    rev = _current_revision(req)
    step.status = StepStatus.APPROVED
    step.acted_by_id = actor.id
    step.on_behalf_of_id = principal.id if principal else None
    step.acted_at = now
    step.comment = (comment or "").strip() or None
    step.approved_content_hash = rev.content_hash
    who = _actor_label(actor, principal)
    audit.record(
        db,
        action="step.approved",
        summary=f"{who} approved {req.ref} as {', '.join(step.reasons)}",
        entity_type="approval_step",
        entity_id=step.id,
        actor=actor,
        on_behalf_of=principal,
        request=req,
        data={"revision": req.revision, "sequence": step.sequence, "content_hash": rev.content_hash, "comment": step.comment},
        client=client,
    )
    nxt = next((s for s in sorted(req.current_steps, key=lambda s: s.sequence) if s.status == StepStatus.WAITING), None)
    if nxt is not None:
        nxt.status = StepStatus.PENDING
        nxt.activated_at = now
        req.current_step = nxt.sequence
        notify_approvers(db, req, nxt)
        notify(
            db,
            req.requester,
            kind="progress",
            title=f"{who} approved {req.ref}",
            body=f"It's now with {nxt.approver.name}.",
            request=req,
            email=False,
        )
    else:
        _finalise_approval(db, req, actor, principal, rev, client)
    return req


def _finalise_approval(db: Session, req: SpendRequest, actor: User, principal: User | None, rev: RequestRevision, client: ClientInfo) -> None:
    now = utcnow()
    is_amendment = req.approved_revision is not None
    previous = req.approved_total_usd
    req.status = RequestStatus.APPROVED
    req.current_step = None
    req.decided_at = now
    req.approved_at = req.approved_at or now
    req.approved_total_amount = req.total_amount
    req.approved_total_usd = req.total_usd
    req.approved_revision = req.revision
    rev.status = "approved"
    rev.decided_at = now
    audit.record(
        db,
        action="amendment.approved" if is_amendment else "request.approved",
        summary=f"{req.ref} {'change ' if is_amendment else ''}fully approved for {amount_line(req)}",
        entity_type="request",
        entity_id=req.ref,
        actor=actor,
        on_behalf_of=principal,
        request=req,
        data={
            "revision": req.revision,
            "content_hash": rev.content_hash,
            "approved_total_usd": str(req.approved_total_usd),
            "previous_approved_total_usd": str(previous) if previous is not None else None,
        },
        client=client,
    )
    notify(
        db,
        req.requester,
        kind="approved",
        title=f"Approved: {req.title}" if not is_amendment else f"Change approved: {req.title}",
        body=f"You can go ahead. Ask the supplier to put {req.ref} on the invoice so Finance can match it.",
        request=req,
    )
    notify_finance(db, req, title=f"Approved spend: {req.title}", body=f"{req.ref} approved for {amount_line(req)}. Waiting for the invoice.")


def reject(db: Session, actor: User, req: SpendRequest, reason: str, comment: str | None, client: ClientInfo) -> SpendRequest:
    reason = (reason or "").strip()
    if not reason:
        raise DomainError("Pick or type a reason, so the requester knows what to do next.", "reason_required")
    step, principal = _actionable_step(db, actor, req)
    now = utcnow()
    step.status = StepStatus.REJECTED
    step.acted_by_id = actor.id
    step.on_behalf_of_id = principal.id if principal else None
    step.acted_at = now
    step.decision_reason = reason[:120]
    step.comment = (comment or "").strip() or None
    _skip_open_steps(req)
    rev = _current_revision(req)
    rev.status = "rejected"
    rev.decided_at = now
    who = _actor_label(actor, principal)
    detail = reason + (f": {step.comment}" if step.comment else "")
    if req.approved_revision is not None:
        approved = next(r for r in req.revisions if r.number == req.approved_revision)
        _restore(req, approved.data)
        req.status = RequestStatus.APPROVED
        req.current_step = None
        audit.record(
            db,
            action="amendment.rejected",
            summary=f"{who} rejected the change to {req.ref}: {detail}",
            entity_type="approval_step",
            entity_id=step.id,
            actor=actor,
            on_behalf_of=principal,
            request=req,
            data={"revision": rev.number, "reason": reason, "comment": step.comment},
            client=client,
        )
        notify(
            db,
            req.requester,
            kind="rejected",
            title=f"Change not approved: {req.title}",
            body=f"{who} said: {detail}. The original approval for {fmt_money(req.approved_total_amount, req.currency)} still stands.",
            request=req,
        )
    else:
        req.status = RequestStatus.REJECTED
        req.current_step = None
        req.decided_at = now
        audit.record(
            db,
            action="request.rejected",
            summary=f"{who} rejected {req.ref}: {detail}",
            entity_type="approval_step",
            entity_id=step.id,
            actor=actor,
            on_behalf_of=principal,
            request=req,
            data={"revision": rev.number, "reason": reason, "comment": step.comment},
            client=client,
        )
        notify(db, req.requester, kind="rejected", title=f"Not approved: {req.title}", body=f"{who} said: {detail}.", request=req)
    return req


def return_to_requester(db: Session, actor: User, req: SpendRequest, comment: str, client: ClientInfo) -> SpendRequest:
    comment = (comment or "").strip()
    if not comment:
        raise DomainError("Say what needs to change.", "comment_required")
    if req.is_amendment_in_progress:
        raise Conflict("A change to an approved request can be approved or rejected, not sent back.")
    step, principal = _actionable_step(db, actor, req)
    now = utcnow()
    step.status = StepStatus.RETURNED
    step.acted_by_id = actor.id
    step.on_behalf_of_id = principal.id if principal else None
    step.acted_at = now
    step.comment = comment
    _skip_open_steps(req)
    rev = _current_revision(req)
    rev.status = "returned"
    rev.decided_at = now
    req.status = RequestStatus.RETURNED
    req.current_step = None
    who = _actor_label(actor, principal)
    audit.record(
        db,
        action="request.returned",
        summary=f"{who} sent {req.ref} back for changes: {comment}",
        entity_type="approval_step",
        entity_id=step.id,
        actor=actor,
        on_behalf_of=principal,
        request=req,
        data={"revision": rev.number, "comment": comment},
        client=client,
    )
    notify(db, req.requester, kind="returned", title=f"Changes needed: {req.title}", body=f"{who} said: {comment}", request=req, cta="Update the request")
    return req


def withdraw(db: Session, actor: User, req: SpendRequest, client: ClientInfo) -> SpendRequest:
    if req.requester_id != actor.id:
        raise NotAllowed("Only the requester can withdraw this request.")
    if req.status not in (RequestStatus.PENDING, RequestStatus.RETURNED):
        raise Conflict("Only requests that are still being approved can be withdrawn.")
    waiting_for = req.pending_step.approver if req.pending_step else None
    _skip_open_steps(req)
    rev = _current_revision(req)
    rev.status = "withdrawn"
    rev.decided_at = utcnow()
    if req.approved_revision is not None:
        approved = next(r for r in req.revisions if r.number == req.approved_revision)
        _restore(req, approved.data)
        req.status = RequestStatus.APPROVED
        action, summary = "amendment.withdrawn", f"{actor.name} withdrew the proposed change to {req.ref}"
    else:
        req.status = RequestStatus.WITHDRAWN
        req.decided_at = utcnow()
        action, summary = "request.withdrawn", f"{actor.name} withdrew {req.ref}"
    req.current_step = None
    audit.record(db, action=action, summary=summary, entity_type="request", entity_id=req.ref, actor=actor, request=req, client=client)
    if waiting_for is not None:
        notify(db, waiting_for, kind="withdrawn", title=f"Withdrawn: {req.title}", body=f"{actor.name} withdrew it. Nothing for you to do.", request=req, email=False)
    return req


# ---------------------------------------------------------------- after approval


def amend(db: Session, actor: User, req: SpendRequest, changes: dict[str, Any], reason: str, client: ClientInfo) -> tuple[SpendRequest, str, bool]:
    if req.requester_id != actor.id:
        raise NotAllowed("Only the requester can change this request.")
    if req.status != RequestStatus.APPROVED:
        raise Conflict("Only approved requests can be changed this way.")
    reason = (reason or "").strip()
    if not reason:
        raise DomainError("Explain why it changed (for example, a new quote).", "reason_required")
    pv, policy = current_policy(db)
    before = snapshot(req)
    same_currency = changes.get("currency", req.currency) == req.currency
    _apply_fields(db, req, changes, policy, keep_rate=same_currency)
    if req.amount <= 0:
        raise DomainError("Enter an amount greater than zero.", "amount_invalid")
    db.flush()
    db.refresh(req, ["attachments", "category", "project"])
    changed = diff_snapshots(before, snapshot(req))
    if not changed:
        raise DomainError("Nothing has changed.", "no_changes")
    route = compute_route(policy, _route_input(req), Directory(db))
    previously_approved = {s.approver_id for s in req.steps if s.status == StepStatus.APPROVED}
    decision = assess_amendment(policy, Decimal(req.approved_total_usd), Decimal(req.total_usd), previously_approved, route)
    req.revision += 1
    rev = _new_revision(db, req, kind="amendment", actor=actor, reason=reason)
    if not decision.needs_reapproval:
        now = utcnow()
        rev.status = "applied"
        rev.decided_at = now
        previous = req.approved_total_usd
        req.approved_total_amount = req.total_amount
        req.approved_total_usd = req.total_usd
        req.approved_revision = req.revision
        audit.record(
            db,
            action="request.amended",
            summary=f"{actor.name} changed {req.ref} within tolerance: {reason}",
            entity_type="request",
            entity_id=req.ref,
            actor=actor,
            request=req,
            data={"revision": req.revision, "changes": changed, "reason": reason, "decision": decision.explanation, "previous_approved_total_usd": str(previous), "content_hash": rev.content_hash},
            client=client,
        )
        notify_finance(db, req, title=f"Changed within tolerance: {req.title}", body=f"{req.ref} is now {amount_line(req)}. Reason: {reason}")
        for approver_id in previously_approved:
            approver = db.get(User, approver_id)
            if approver:
                notify(db, approver, kind="amended", title=f"FYI: {req.ref} changed within tolerance", body=f"{actor.name}: {reason}", request=req, email=False)
    else:
        _create_steps(req, route)
        req.status = RequestStatus.PENDING
        req.policy_version_id = pv.id
        db.flush()
        audit.record(
            db,
            action="amendment.submitted",
            summary=f"{actor.name} asked to change {req.ref}: {reason}",
            entity_type="request",
            entity_id=req.ref,
            actor=actor,
            request=req,
            data={"revision": req.revision, "changes": changed, "reason": reason, "decision": decision.explanation, "route": _route_summary(route), "content_hash": rev.content_hash},
            client=client,
        )
        notify_approvers(db, req, req.pending_step)
    return req, decision.explanation, decision.needs_reapproval


def cancel(db: Session, actor: User, req: SpendRequest, reason: str, client: ClientInfo) -> SpendRequest:
    if not request_permissions(db, actor, req).can_cancel:
        raise NotAllowed("This request can't be cancelled. Requests with invoices are closed by Finance instead.")
    reason = (reason or "").strip()
    if not reason:
        raise DomainError("Say why it's not going ahead.", "reason_required")
    req.status = RequestStatus.CANCELLED
    req.closed_at = utcnow()
    audit.record(db, action="request.cancelled", summary=f"{actor.name} cancelled {req.ref}: {reason}", entity_type="request", entity_id=req.ref, actor=actor, request=req, data={"reason": reason}, client=client)
    notify_finance(db, req, title=f"Cancelled: {req.title}", body=f"{req.ref} isn't going ahead: {reason}")
    if actor.id != req.requester_id:
        notify(db, req.requester, kind="cancelled", title=f"Cancelled: {req.title}", body=f"{actor.name}: {reason}", request=req)
    return req


def close(db: Session, actor: User, req: SpendRequest, note: str | None, client: ClientInfo) -> SpendRequest:
    if not request_permissions(db, actor, req).can_close:
        raise NotAllowed("Only Finance can close approved requests.")
    req.status = RequestStatus.CLOSED
    req.closed_at = utcnow()
    invoiced = sum((i.amount_usd for i in req.invoices), Decimal(0))
    audit.record(db, action="request.closed", summary=f"{actor.name} closed {req.ref}" + (f": {note}" if note else ""), entity_type="request", entity_id=req.ref, actor=actor, request=req, data={"note": note, "invoiced_usd": str(invoiced)}, client=client)
    notify(db, req.requester, kind="closed", title=f"Closed: {req.title}", body="Finance has closed this request. No further invoices will be paid against it.", request=req, email=False)
    return req


def record_invoice(
    db: Session,
    actor: User,
    req: SpendRequest,
    *,
    invoice_number: str,
    invoice_date: date,
    amount: Decimal,
    currency: str,
    supplier: str | None,
    notes: str | None,
    override_reason: str | None,
    file: tuple[str, bytes] | None,
    client: ClientInfo,
) -> Invoice:
    if not actor.has_role(Role.FINANCE, Role.FINANCE_ADMIN):
        raise NotAllowed("Only Finance can record invoices.")
    if req.approved_total_usd is None or req.status not in (RequestStatus.APPROVED, RequestStatus.PENDING):
        raise Conflict("Invoices can only be recorded against approved requests.")
    invoice_number = (invoice_number or "").strip()
    if not invoice_number:
        raise DomainError("Enter the invoice number.", "invoice_number_required")
    if amount is None or Decimal(amount) <= 0:
        raise DomainError("Enter the invoice amount.", "amount_invalid")
    supplier = (supplier or req.supplier or "").strip() or None
    dup = db.execute(
        select(Invoice).where(
            func.lower(Invoice.invoice_number) == invoice_number.lower(),
            or_(func.lower(Invoice.supplier) == (supplier or "").lower(), Invoice.request_id == req.id),
        )
    ).scalar()
    if dup is not None:
        raise Conflict(f"Invoice {invoice_number} from this supplier is already recorded on {dup.request.ref}. It may be a duplicate.")
    currency = currency.upper()
    rate = usd_per_unit(db, currency, invoice_date)
    amount = money(amount)
    amount_usd = to_usd(amount, rate)
    _, policy = current_policy(db)
    invoiced = sum((i.amount_usd for i in req.invoices), Decimal(0))
    ceiling = Decimal(req.approved_total_usd) * (1 + Decimal(policy.amendment_tolerance_pct) / 100)
    exceeds = invoiced + amount_usd > ceiling
    override_reason = (override_reason or "").strip() or None
    if exceeds and not override_reason:
        raise DomainError(
            f"This takes invoiced spend to {fmt_money(invoiced + amount_usd, 'USD')}, above the approved "
            f"{fmt_money(req.approved_total_usd, 'USD')}. Ask {req.requester.name} to submit a change, or record an override reason.",
            "exceeds_approval",
        )
    inv = Invoice(
        request=req,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        supplier=supplier,
        currency=currency,
        amount=amount,
        fx_rate=rate,
        amount_usd=amount_usd,
        exceeds_approval=exceeds,
        override_reason=override_reason if exceeds else None,
        notes=(notes or "").strip() or None,
        received_by_id=actor.id,
    )
    db.add(inv)
    db.flush()
    file_hash = None
    if file is not None:
        stored = validate_and_store(file[0], file[1], prefix=f"requests/{req.ref}")
        file_hash = stored.sha256
        db.add(
            Attachment(
                request=req,
                invoice_id=inv.id,
                kind=AttachmentKind.INVOICE,
                filename=stored.filename,
                content_type=stored.content_type,
                size_bytes=stored.size,
                sha256=stored.sha256,
                storage_key=stored.key,
                revision=req.revision,
                uploaded_by_id=actor.id,
            )
        )
    audit.record(
        db,
        action="invoice.recorded",
        summary=f"{actor.name} recorded invoice {invoice_number} for {fmt_money(amount, currency)} on {req.ref}"
        + (" (over the approved amount, override recorded)" if exceeds else ""),
        entity_type="invoice",
        entity_id=inv.id,
        actor=actor,
        request=req,
        data={"invoice_number": invoice_number, "amount": str(amount), "currency": currency, "amount_usd": str(amount_usd), "exceeds_approval": exceeds, "override_reason": inv.override_reason, "file_sha256": file_hash},
        client=client,
    )
    notify(db, req.requester, kind="invoice", title=f"Invoice received for {req.ref}", body=f"Finance recorded invoice {invoice_number} for {fmt_money(amount, currency)}.", request=req, email=False)
    return inv


def mark_paid(db: Session, actor: User, inv: Invoice, paid_on: date, reference: str | None, client: ClientInfo) -> Invoice:
    if not actor.has_role(Role.FINANCE, Role.FINANCE_ADMIN):
        raise NotAllowed("Only Finance can release payments.")
    if inv.status != InvoiceStatus.RECEIVED:
        raise Conflict("This invoice is already paid.")
    req = inv.request
    if req.requester_id == actor.id:
        raise NotAllowed("You can't release payment on your own request. Ask a colleague in Finance.")
    inv.status = InvoiceStatus.PAID
    inv.paid_on = paid_on
    inv.payment_reference = (reference or "").strip() or None
    inv.paid_by_id = actor.id
    inv.paid_at = utcnow()
    audit.record(
        db,
        action="invoice.paid",
        summary=f"{actor.name} marked invoice {inv.invoice_number} on {req.ref} as paid ({fmt_money(inv.amount, inv.currency)})",
        entity_type="invoice",
        entity_id=inv.id,
        actor=actor,
        request=req,
        data={"paid_on": paid_on.isoformat(), "reference": inv.payment_reference, "amount_usd": str(inv.amount_usd)},
        client=client,
    )
    notify(db, req.requester, kind="paid", title=f"Paid: invoice {inv.invoice_number}", body=f"Finance paid {fmt_money(inv.amount, inv.currency)} on {paid_on:%d %b %Y}.", request=req, email=False)
    return inv


# ---------------------------------------------------------------- attachments, comments, views


def add_attachment(db: Session, actor: User, req: SpendRequest, filename: str, data: bytes, kind: str) -> Attachment:
    if req.requester_id != actor.id:
        raise NotAllowed("Only the requester can add documents.")
    if req.status not in (RequestStatus.DRAFT, RequestStatus.RETURNED, RequestStatus.APPROVED):
        raise Conflict("Documents can't be added while the request is with an approver.")
    if kind not in (AttachmentKind.QUOTE, AttachmentKind.SUPPORTING):
        raise DomainError("Unknown document type.")
    stored = validate_and_store(filename, data, prefix=f"requests/{req.ref}")
    att = Attachment(
        request=req,
        kind=kind,
        filename=stored.filename,
        content_type=stored.content_type,
        size_bytes=stored.size,
        sha256=stored.sha256,
        storage_key=stored.key,
        revision=req.revision,
        uploaded_by_id=actor.id,
    )
    db.add(att)
    db.flush()
    return att


def remove_attachment(db: Session, actor: User, att: Attachment) -> None:
    req = att.request
    if req.requester_id != actor.id or req.status not in (RequestStatus.DRAFT, RequestStatus.RETURNED):
        raise NotAllowed("Documents can only be removed before the request is submitted.")
    submitted_ids = {a["id"] for r in req.revisions for a in r.data.get("attachments", [])}
    if att.id in submitted_ids:
        raise Conflict("This document was part of a submitted version, so it's kept for the record.")
    db.delete(att)


def add_comment(db: Session, actor: User, req: SpendRequest, body: str, client: ClientInfo) -> Comment:
    body = (body or "").strip()
    if not body:
        raise DomainError("Write a comment first.")
    if not request_permissions(db, actor, req).can_comment:
        raise NotAllowed("You can't comment on this request.")
    c = Comment(request=req, author=actor, body=body[:4000])
    db.add(c)
    db.flush()
    audit.record(db, action="comment.added", summary=f"{actor.name} commented on {req.ref}", entity_type="comment", entity_id=c.id, actor=actor, request=req, data={"body": c.body}, client=client)
    recipients = {req.requester_id}
    if req.pending_step:
        recipients.add(req.pending_step.approver_id)
    for uid in recipients - {actor.id}:
        user = db.get(User, uid)
        if user:
            notify(db, user, kind="comment", title=f"{actor.name} commented on {req.ref}", body=c.body[:300], request=req, email=False)
    return c


def mark_viewed(db: Session, actor: User, req: SpendRequest, client: ClientInfo) -> None:
    step = req.pending_step
    if req.status != RequestStatus.PENDING or step is None or step.first_viewed_at is not None or actor.id == req.requester_id:
        return
    allowed, principal = acting_principal(db, actor, step)
    if not allowed:
        return
    step.first_viewed_at = utcnow()
    audit.record(
        db,
        action="request.viewed",
        summary=f"{_actor_label(actor, principal)} opened {req.ref} while it was waiting for them",
        entity_type="approval_step",
        entity_id=step.id,
        actor=actor,
        on_behalf_of=principal,
        request=req,
        client=client,
    )


# ---------------------------------------------------------------- delegation (cover while away)


def create_delegation(db: Session, actor: User, principal: User, delegate: User, starts_on: date, ends_on: date, note: str | None, client: ClientInfo) -> Delegation:
    if actor.id != principal.id and not actor.has_role(Role.ADMIN):
        raise NotAllowed("You can only set up cover for yourself.")
    if ends_on < starts_on:
        raise DomainError("The end date is before the start date.", "dates_invalid")
    if ends_on < company_today():
        raise DomainError("Those dates are in the past.", "dates_invalid")
    if (ends_on - starts_on).days > MAX_DELEGATION_DAYS:
        raise DomainError("Cover can be set for up to three months at a time.", "dates_invalid")
    _, policy = current_policy(db)
    directory = Directory(db)
    problem = stand_in_problem(principal, delegate, policy, directory)
    if problem:
        raise DomainError(problem, "stand_in_not_allowed")
    overlap = db.execute(
        select(Delegation).where(
            Delegation.principal_id == principal.id,
            Delegation.revoked_at.is_(None),
            Delegation.starts_on <= ends_on,
            Delegation.ends_on >= starts_on,
        )
    ).scalar()
    if overlap is not None:
        raise Conflict(f"{principal.name} already has {overlap.delegate.name} covering some of those dates.")
    d = Delegation(principal=principal, delegate=delegate, starts_on=starts_on, ends_on=ends_on, note=(note or "").strip() or None, created_by_id=actor.id)
    db.add(d)
    db.flush()
    audit.record(
        db,
        action="delegation.created",
        summary=f"{delegate.name} will approve on behalf of {principal.name} from {starts_on:%d %b} to {ends_on:%d %b %Y}",
        entity_type="delegation",
        entity_id=d.id,
        actor=actor,
        data={"principal_id": principal.id, "delegate_id": delegate.id, "starts_on": starts_on.isoformat(), "ends_on": ends_on.isoformat(), "note": d.note},
        client=client,
    )
    notify(
        db,
        delegate,
        kind="delegation",
        title=f"You're covering approvals for {principal.name}",
        body=f"From {starts_on:%d %b} to {ends_on:%d %b %Y}, {principal.name}'s approvals will also come to you. Anything you approve is recorded as on their behalf.",
    )
    return d


def revoke_delegation(db: Session, actor: User, d: Delegation, client: ClientInfo) -> Delegation:
    if actor.id != d.principal_id and not actor.has_role(Role.ADMIN):
        raise NotAllowed("Only the person being covered can end this.")
    if d.revoked_at is not None:
        return d
    d.revoked_at = utcnow()
    d.revoked_by_id = actor.id
    audit.record(db, action="delegation.revoked", summary=f"{actor.name} ended {d.delegate.name}'s cover for {d.principal.name}", entity_type="delegation", entity_id=d.id, actor=actor, client=client)
    notify(db, d.delegate, kind="delegation", title=f"Cover for {d.principal.name} has ended", body="Their approvals no longer come to you.", email=False)
    return d


# ---------------------------------------------------------------- people changes


def deactivate_user(db: Session, actor: User, user: User, client: ClientInfo) -> dict[str, int]:
    """A leaver: block sign-in, hand their pending approvals and direct reports to their manager."""
    if not actor.has_role(Role.ADMIN):
        raise NotAllowed("Only administrators can deactivate people.")
    if user.id == actor.id:
        raise DomainError("You can't deactivate yourself.")
    if not user.is_active:
        return {"steps_reassigned": 0, "reports_moved": 0}
    _, policy = current_policy(db)
    directory = Directory(db)
    user.is_active = False
    user.deactivated_at = utcnow()
    for s in db.execute(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))).scalars():
        s.revoked_at = utcnow()
    successor = directory.user(user.manager_id)
    reports = list(db.execute(select(User).where(User.manager_id == user.id, User.is_active.is_(True))).scalars())
    for r in reports:
        r.manager_id = successor.id if successor else None
    db.flush()

    open_steps = list(
        db.execute(
            select(ApprovalStep)
            .join(SpendRequest)
            .where(
                ApprovalStep.approver_id == user.id,
                ApprovalStep.status.in_([StepStatus.PENDING, StepStatus.WAITING]),
                SpendRequest.status == RequestStatus.PENDING,
                ApprovalStep.revision == SpendRequest.revision,
            )
        ).scalars()
    )
    for step in open_steps:
        _reassign_step(db, actor, step, user, policy, directory, client)
    audit.record(
        db,
        action="user.deactivated",
        summary=f"{actor.name} deactivated {user.name}; {len(open_steps)} approvals and {len(reports)} direct reports moved to {successor.name if successor else 'nobody (no manager on record)'}",
        entity_type="user",
        entity_id=user.id,
        actor=actor,
        data={"steps_reassigned": len(open_steps), "reports_moved": len(reports), "successor_id": successor.id if successor else None},
        client=client,
    )
    return {"steps_reassigned": len(open_steps), "reports_moved": len(reports)}


def _reassign_step(db: Session, actor: User, step: ApprovalStep, leaver: User, policy: PolicyDocument, directory: Directory, client: ClientInfo) -> None:
    req = step.request
    if step.position_role:
        spec = RuleApprover(type="role", role=step.position_role)
    elif leaver.manager_id:
        spec = RuleApprover(type="user", user_id=leaver.manager_id)
    else:
        spec = RuleApprover(type="role", role=policy.fallback_approver_role)
    new_approver, notes = resolve_approver(spec, _route_input(req), directory, policy)
    if new_approver.id == leaver.id:
        raise DomainError("Couldn't find someone to take over this approval.")
    step.approver_id = new_approver.id
    step.approver = new_approver
    step.routing_note = "; ".join(filter(None, [step.routing_note, f"Reassigned from {leaver.name} (left)", *notes]))
    twin = next(
        (s for s in req.current_steps if s.id != step.id and s.approver_id == new_approver.id and s.status in (StepStatus.PENDING, StepStatus.WAITING)),
        None,
    )
    if twin is not None:
        keep, drop = sorted([step, twin], key=lambda s: s.sequence)
        keep.reasons = [*keep.reasons, *[r for r in drop.reasons if r not in keep.reasons]]
        keep.rule_keys = [*keep.rule_keys, *drop.rule_keys]
        if drop.status == StepStatus.PENDING:
            keep.status, keep.activated_at = StepStatus.PENDING, utcnow()
            req.current_step = keep.sequence
        drop.status = StepStatus.SKIPPED
        drop.routing_note = "; ".join(filter(None, [drop.routing_note, "Merged: same approver as an earlier step"]))
    audit.record(
        db,
        action="step.reassigned",
        summary=f"{req.ref}: approval moved from {leaver.name} to {new_approver.name}",
        entity_type="approval_step",
        entity_id=step.id,
        actor=actor,
        request=req,
        data={"from_id": leaver.id, "to_id": new_approver.id},
        client=client,
    )
    if req.pending_step is not None and req.pending_step.approver_id == new_approver.id:
        notify_approvers(db, req, req.pending_step)


# ---------------------------------------------------------------- scheduled jobs


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def contract_end(req: SpendRequest) -> date | None:
    if req.payment_type != PaymentType.RECURRING or not req.term_months or not req.start_date:
        return None
    return _add_months(req.start_date, req.term_months)


@dataclass
class JobResult:
    reminders: int = 0
    renewals: int = 0
    skipped_weekend: bool = False


def run_reminders(db: Session, now: datetime | None = None) -> JobResult:
    """Chase approvals that have waited too long, and flag contracts coming up for renewal."""
    now = now or utcnow()
    result = JobResult()
    _, policy = current_policy(db)
    today = company_today()
    if today.weekday() in (5, 6):  # UAE weekend
        result.skipped_weekend = True
    else:
        cutoff = now - timedelta(hours=policy.reminder_after_hours)
        steps = db.execute(
            select(ApprovalStep)
            .join(SpendRequest)
            .where(
                ApprovalStep.status == StepStatus.PENDING,
                SpendRequest.status == RequestStatus.PENDING,
                ApprovalStep.revision == SpendRequest.revision,
                ApprovalStep.activated_at <= cutoff,
                or_(ApprovalStep.last_reminded_at.is_(None), ApprovalStep.last_reminded_at <= now - timedelta(hours=20)),
            )
        ).scalars()
        for step in steps:
            req = step.request
            notify_approvers(db, req, step, reminder=True)
            step.reminder_count += 1
            step.last_reminded_at = now
            result.reminders += 1
            audit.record(db, action="step.reminder_sent", summary=f"Reminder {step.reminder_count} sent to {step.approver.name} for {req.ref}", entity_type="approval_step", entity_id=step.id, request=req)

    recurring = db.execute(
        select(SpendRequest).where(
            SpendRequest.status == RequestStatus.APPROVED,
            SpendRequest.payment_type == PaymentType.RECURRING,
            SpendRequest.renewal_reminded_at.is_(None),
        )
    ).scalars()
    for req in recurring:
        end = contract_end(req)
        if end is None or today < end - timedelta(days=policy.renewal_notice_days):
            continue
        req.renewal_reminded_at = now
        result.renewals += 1
        notify(
            db,
            req.requester,
            kind="renewal",
            title=f"Coming up for renewal: {req.title}",
            body=f"The contract ends on {end:%d %b %Y}. Raise a new request to renew it, or tell the supplier you're cancelling.",
            request=req,
        )
        notify_finance(db, req, title=f"Renewal due: {req.title}", body=f"{req.ref} ends on {end:%d %b %Y}.")
        audit.record(db, action="request.renewal_due", summary=f"Renewal reminder sent for {req.ref} (ends {end:%d %b %Y})", entity_type="request", entity_id=req.ref, request=req)
    db.commit()
    return result
