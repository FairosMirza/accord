"""Approval policy (the delegation-of-authority matrix) and the routing engine.

The policy is data, not code: Finance edits it in the app and every change is saved
as a new immutable version. Each request records the version that routed it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.directory import Directory
from app.errors import DomainError
from app.models import (
    PERIOD_MONTHS,
    POSITION_ROLES,
    BillingPeriod,
    Category,
    CategoryGroup,
    PaymentType,
    PolicyVersion,
    Role,
    User,
)

ROLE_LABELS: dict[str, str] = {
    Role.ADMIN: "System administrator",
    Role.FINANCE: "Finance team",
    Role.FINANCE_ADMIN: "Finance lead",
    Role.AUDITOR: "Auditor (read-only)",
    Role.EXECUTIVE: "Executive",
    Role.COO: "COO",
    Role.CEO: "CEO",
}


class RuleCondition(BaseModel):
    category_groups: list[CategoryGroup] = Field(default_factory=list)
    category_ids: list[int] = Field(default_factory=list)
    department_ids: list[int] = Field(default_factory=list)
    site_ids: list[int] = Field(default_factory=list)
    min_total_usd: Decimal | None = None


class RuleApprover(BaseModel):
    type: Literal["line_manager", "department_head", "role", "user"]
    role: str | None = None
    user_id: int | None = None


class ApprovalRule(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=120)
    active: bool = True
    approver: RuleApprover
    when: RuleCondition = Field(default_factory=RuleCondition)


class PolicyDocument(BaseModel):
    rules: list[ApprovalRule]
    # Increases above this % of the approved amount go back for approval.
    amendment_tolerance_pct: Decimal = Decimal("5")
    reminder_after_hours: int = Field(default=24, ge=1, le=24 * 14)
    # Open-ended subscriptions are measured on this many months of spend.
    rolling_term_months: int = Field(default=12, ge=1, le=120)
    # Who approves when the normal route has no eligible person (e.g. the CEO's own requests).
    fallback_approver_role: str = Role.COO
    # Who may stand in for position holders (COO, CEO) while they are away.
    stand_in_roles: list[str] = Field(default_factory=lambda: [Role.CEO, Role.FINANCE_ADMIN])
    renewal_notice_days: int = Field(default=30, ge=1, le=365)
    rejection_reasons: list[str] = Field(
        default_factory=lambda: [
            "Not in budget",
            "Not needed right now",
            "Get another quote",
            "Use an existing tool or supplier",
            "Missing information",
        ]
    )

    @field_validator("rules")
    @classmethod
    def _unique_keys(cls, rules: list[ApprovalRule]) -> list[ApprovalRule]:
        keys = [r.key for r in rules]
        if len(keys) != len(set(keys)):
            raise ValueError("Rule keys must be unique")
        if not any(r.active for r in rules):
            raise ValueError("At least one rule must be active")
        return rules


DEFAULT_POLICY = PolicyDocument(
    rules=[
        ApprovalRule(key="line-manager", label="Line manager", approver=RuleApprover(type="line_manager")),
        ApprovalRule(
            key="coo-it",
            label="COO: all IT spend",
            approver=RuleApprover(type="role", role=Role.COO),
            when=RuleCondition(category_groups=[CategoryGroup.IT]),
        ),
        ApprovalRule(
            key="coo-general",
            label="COO: USD 5,000 or more",
            approver=RuleApprover(type="role", role=Role.COO),
            when=RuleCondition(category_groups=[CategoryGroup.GENERAL], min_total_usd=Decimal(5000)),
        ),
        ApprovalRule(
            key="coo-travel",
            label="COO: travel USD 3,000 or more",
            approver=RuleApprover(type="role", role=Role.COO),
            when=RuleCondition(category_groups=[CategoryGroup.TRAVEL], min_total_usd=Decimal(3000)),
        ),
    ]
)


def current_policy(db: Session) -> tuple[PolicyVersion, PolicyDocument]:
    pv = db.execute(select(PolicyVersion).order_by(PolicyVersion.version.desc()).limit(1)).scalar()
    if pv is None:
        # Created at start-up by ensure_policy; never implicitly here, so history can't be pre-empted.
        raise DomainError("Approval rules aren't set up yet. Try again in a minute.", "policy_missing")
    return pv, PolicyDocument.model_validate(pv.document)


def ensure_policy(db: Session) -> PolicyVersion:
    pv = db.execute(select(PolicyVersion).order_by(PolicyVersion.version.desc()).limit(1)).scalar()
    if pv is None:
        pv = PolicyVersion(
            version=1,
            document=DEFAULT_POLICY.model_dump(mode="json"),
            change_note="Initial policy from kickoff call (draft authority matrix: 5,000 general, travel placeholder, all IT to COO)",
        )
        db.add(pv)
        db.flush()
    return pv


def commitment_total(
    amount: Decimal,
    payment_type: str,
    billing_period: str | None,
    term_months: int | None,
    rolling_term_months: int,
) -> tuple[Decimal, int]:
    """Total value committed, and the number of payments it covers.

    A three-year subscription is judged on three years of spend, not one month.
    """
    if payment_type != PaymentType.RECURRING:
        return Decimal(amount), 1
    if not billing_period:
        raise DomainError("Choose how often a recurring cost is paid.", "billing_period_required")
    months = term_months or rolling_term_months
    payments = max(1, math.ceil(months / PERIOD_MONTHS[BillingPeriod(billing_period)]))
    return Decimal(amount) * payments, payments


@dataclass
class RouteInput:
    requester: User
    category: Category
    department_id: int | None
    site_id: int | None
    total_usd: Decimal


@dataclass
class PlannedStep:
    approver: User
    reasons: list[str]
    rule_keys: list[str]
    position_role: str | None = None
    notes: list[str] = field(default_factory=list)


class RoutingError(DomainError):
    def __init__(self, message: str):
        super().__init__(message, "routing_failed")


def _matches(cond: RuleCondition, ri: RouteInput) -> bool:
    if cond.category_groups and ri.category.group not in cond.category_groups:
        return False
    if cond.category_ids and ri.category.id not in cond.category_ids:
        return False
    if cond.department_ids and ri.department_id not in cond.department_ids:
        return False
    if cond.site_ids and ri.site_id not in cond.site_ids:
        return False
    if cond.min_total_usd is not None and ri.total_usd < cond.min_total_usd:
        return False
    return True


def resolve_approver(spec: RuleApprover, ri: RouteInput, directory: Directory, policy: PolicyDocument) -> tuple[User, list[str]]:
    requester = ri.requester
    notes: list[str] = []
    candidate: User | None
    if spec.type == "line_manager":
        candidate = directory.user(requester.manager_id)
        if candidate is None:
            candidate = directory.department_head(ri.department_id)
            if candidate is not None and candidate.id != requester.id:
                notes.append("No line manager on record, so this goes to the department head")
    elif spec.type == "department_head":
        candidate = directory.department_head(ri.department_id)
    elif spec.type == "role":
        candidate = directory.holder_of(spec.role or "")
        if candidate is None:
            raise RoutingError(f"Nobody currently holds the {ROLE_LABELS.get(spec.role or '', spec.role)} position.")
    else:
        candidate = directory.user(spec.user_id)

    # Nobody approves their own spend, and leavers can't approve: walk up the reporting line.
    seen: set[int] = set()
    while candidate is not None and (candidate.id == requester.id or not candidate.is_active):
        if candidate.id in seen:
            candidate = None
            break
        seen.add(candidate.id)
        if candidate.id == requester.id:
            notes.append(f"{candidate.name} can't approve their own request, so it goes to their manager")
        else:
            notes.append(f"{candidate.name} is no longer active, so it goes to their manager")
        candidate = directory.user(candidate.manager_id)

    if candidate is None:
        fallback = directory.holder_of(policy.fallback_approver_role)
        if fallback is None or fallback.id == requester.id:
            raise RoutingError("No eligible approver could be found for this request. Ask an administrator.")
        notes.append(f"Routed to the fallback approver ({ROLE_LABELS.get(policy.fallback_approver_role, policy.fallback_approver_role)})")
        candidate = fallback
    return candidate, notes


def compute_route(policy: PolicyDocument, ri: RouteInput, directory: Directory) -> list[PlannedStep]:
    """Ordered, de-duplicated approval chain. The same person never approves twice."""
    steps: list[PlannedStep] = []
    for rule in policy.rules:
        if not rule.active or not _matches(rule.when, ri):
            continue
        approver, notes = resolve_approver(rule.approver, ri, directory, policy)
        role = rule.approver.role if rule.approver.type == "role" else None
        existing = next((s for s in steps if s.approver.id == approver.id), None)
        if existing:
            existing.reasons.append(rule.label)
            existing.rule_keys.append(rule.key)
            existing.position_role = existing.position_role or role
            existing.notes.extend(n for n in notes if n not in existing.notes)
            continue
        steps.append(PlannedStep(approver=approver, reasons=[rule.label], rule_keys=[rule.key], position_role=role, notes=notes))
    if not steps:
        approver, notes = resolve_approver(RuleApprover(type="line_manager"), ri, directory, policy)
        steps.append(PlannedStep(approver=approver, reasons=["Line manager"], rule_keys=["default"], notes=notes))
    return steps


@dataclass
class AmendmentDecision:
    needs_reapproval: bool
    explanation: str


def assess_amendment(
    policy: PolicyDocument,
    approved_total_usd: Decimal,
    new_total_usd: Decimal,
    approved_approver_ids: set[int],
    new_route: list[PlannedStep],
) -> AmendmentDecision:
    tolerance = Decimal(policy.amendment_tolerance_pct)
    limit = approved_total_usd * (1 + tolerance / 100)
    if new_total_usd > limit:
        increase = (new_total_usd - approved_total_usd) / approved_total_usd * 100 if approved_total_usd else Decimal(100)
        return AmendmentDecision(
            True, f"The total goes up {increase:.1f}%, which is more than the {tolerance.normalize()}% tolerance, so it needs approval again."
        )
    new_ids = {s.approver.id for s in new_route}
    if not new_ids <= approved_approver_ids:
        return AmendmentDecision(True, "The change brings in approvers who haven't seen it yet, so it needs approval again.")
    return AmendmentDecision(False, f"Within the {tolerance.normalize()}% tolerance, so the change is recorded and Finance is told.")


def stand_in_problem(principal: User, delegate: User, policy: PolicyDocument, directory: Directory) -> str | None:
    """Why `delegate` may not stand in for `principal`, or None if they may."""
    if delegate.id == principal.id:
        return "You can't choose yourself as your stand-in."
    if not delegate.is_active:
        return f"{delegate.name} is no longer active."
    holds_position = principal.has_role(*POSITION_ROLES)
    if holds_position:
        if not delegate.has_role(*policy.stand_in_roles):
            allowed = ", ".join(ROLE_LABELS.get(r, r) for r in policy.stand_in_roles)
            return f"Stand-ins for {principal.name} must be one of: {allowed}."
        return None
    if delegate.has_role(*policy.stand_in_roles, Role.EXECUTIVE) or directory.has_reports(delegate.id):
        return None
    return "Stand-ins must be people managers themselves, so approvals stay with someone who has authority."
