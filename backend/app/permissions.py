"""Who can see and do what.

Visibility (Nadia: "transparent, but not everyone everything"):
  * everyone sees their own requests and anything they approve
  * managers see their whole reporting line; department heads see their department
  * executives, Finance, auditors and administrators see everything
  * confidential requests are limited to the requester, the approvers and the see-all roles
  * drafts are private to the person writing them
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.directory import Directory
from app.models import (
    ApprovalStep,
    RequestStatus,
    Role,
    SpendRequest,
    StepStatus,
    User,
)
from app.timeutil import company_today


def visibility_clause(db: Session, user: User, today: date | None = None) -> ColumnElement[bool]:
    today = today or company_today()
    directory = Directory(db)
    not_draft = SpendRequest.status != RequestStatus.DRAFT
    own = SpendRequest.requester_id == user.id

    if user.sees_everything:
        return or_(own, not_draft)

    approver_of = SpendRequest.id.in_(
        select(ApprovalStep.request_id).where(
            or_(ApprovalStep.approver_id == user.id, ApprovalStep.acted_by_id == user.id)
        )
    )
    clauses = [own, and_(not_draft, approver_of)]

    principals = directory.principals_delegating_to(user.id, today)
    if principals:
        # A stand-in sees what is currently waiting for the person they cover.
        clauses.append(
            SpendRequest.id.in_(
                select(ApprovalStep.request_id).where(
                    ApprovalStep.approver_id.in_(principals), ApprovalStep.status == StepStatus.PENDING
                )
            )
        )

    team_ids = directory.report_ids(user.id)
    dept_ids = directory.headed_department_ids(user.id)
    scope = []
    if team_ids:
        scope.append(SpendRequest.requester_id.in_(team_ids))
    if dept_ids:
        scope.append(SpendRequest.department_id.in_(dept_ids))
    if scope:
        clauses.append(and_(not_draft, SpendRequest.is_confidential.is_(False), or_(*scope)))
    return or_(*clauses)


def can_view(db: Session, user: User, req: SpendRequest) -> bool:
    return bool(
        db.execute(select(SpendRequest.id).where(SpendRequest.id == req.id, visibility_clause(db, user))).first()
    )


def reporting_scope(db: Session, user: User) -> str:
    """Label for the widest view this person has, used on the dashboard."""
    if user.sees_everything:
        return "company"
    directory = Directory(db)
    if directory.headed_department_ids(user.id):
        return "department"
    if directory.report_ids(user.id):
        return "team"
    return "self"


def acting_principal(db: Session, user: User, step: ApprovalStep, today: date | None = None) -> tuple[bool, User | None]:
    """Can `user` act on this step? Returns (allowed, principal-if-acting-as-stand-in)."""
    if step.approver_id == user.id:
        return True, None
    delegation = Directory(db).active_delegation(step.approver_id, user.id, today or company_today())
    if delegation is None or stand_in_already_in_chain(user, step):
        return False, None
    return True, step.approver


def stand_in_already_in_chain(user: User, step: ApprovalStep) -> bool:
    """One person, one approval: a stand-in who approves this request in their own right can't add a second approval."""
    return any(
        s.id != step.id and s.status != StepStatus.SKIPPED and user.id in (s.approver_id, s.acted_by_id)
        for s in step.request.current_steps
    )


@dataclass
class RequestPermissions:
    can_edit: bool = False
    can_submit: bool = False
    can_withdraw: bool = False
    can_delete: bool = False
    can_decide: bool = False
    can_return: bool = False
    acting_for: str | None = None
    can_amend: bool = False
    can_cancel: bool = False
    can_record_invoice: bool = False
    can_close: bool = False
    can_comment: bool = False
    can_upload: bool = False


def request_permissions(db: Session, user: User, req: SpendRequest) -> RequestPermissions:
    p = RequestPermissions()
    is_requester = req.requester_id == user.id
    status = req.status
    is_finance = user.has_role(Role.FINANCE, Role.FINANCE_ADMIN)

    if is_requester and status in (RequestStatus.DRAFT, RequestStatus.RETURNED):
        p.can_edit = p.can_submit = True
    if is_requester and status in (RequestStatus.DRAFT, RequestStatus.RETURNED, RequestStatus.APPROVED):
        p.can_upload = True
    if is_requester and status == RequestStatus.DRAFT:
        p.can_delete = True
    if is_requester and status in (RequestStatus.PENDING, RequestStatus.RETURNED):
        p.can_withdraw = True

    step = req.pending_step
    if status == RequestStatus.PENDING and step is not None and not is_requester:
        allowed, principal = acting_principal(db, user, step)
        if allowed:
            p.can_decide = True
            p.can_return = not req.is_amendment_in_progress
            p.acting_for = principal.name if principal else None

    has_invoices = any(i.is_live for i in req.invoices)
    if is_requester and status == RequestStatus.APPROVED:
        p.can_amend = True
    if status == RequestStatus.APPROVED and not has_invoices and (is_requester or is_finance):
        p.can_cancel = True
    if is_finance and req.approved_total_usd is not None and status in (RequestStatus.APPROVED, RequestStatus.PENDING):
        p.can_record_invoice = True
    if is_finance and status == RequestStatus.APPROVED:
        p.can_close = True
    p.can_comment = status != RequestStatus.DRAFT and not (user.has_role(Role.AUDITOR) and not is_finance)
    return p
