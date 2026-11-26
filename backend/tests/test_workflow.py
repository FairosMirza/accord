"""Request lifecycle: submitting, deciding, sending back, and changing a request after approval."""

from decimal import Decimal

import pytest

from app import workflow
from app.audit import SYSTEM
from app.errors import DomainError, NotAllowed
from app.models import RequestStatus, StepStatus


def test_submitting_needs_a_quote_or_a_reason_for_not_having_one(org, db):
    req = org.draft(org.engineer, org.office, 400, quote=False)

    with pytest.raises(DomainError, match="Attach a quote") as exc:
        workflow.submit(db, org.engineer, req, SYSTEM)
    assert exc.value.code == "incomplete"
    assert req.status == RequestStatus.DRAFT

    workflow.update_draft(db, org.engineer, req, {"no_quote_reason": "Catalogue price; the supplier doesn't issue quotes"})
    workflow.submit(db, org.engineer, req, SYSTEM)
    assert req.status == RequestStatus.PENDING


def test_visa_fees_can_be_submitted_without_a_quote(org):
    req = org.submit(org.engineer, org.visa, 120, quote=False)

    assert req.status == RequestStatus.PENDING


def test_request_is_approved_only_when_the_last_step_approves(org, db):
    req = org.submit(org.engineer, org.office, 6000)
    first, second = req.current_steps

    workflow.approve(db, org.tech_lead, req, "Budgeted for Q4", SYSTEM)
    assert (first.status, second.status) == (StepStatus.APPROVED, StepStatus.PENDING)
    assert req.status == RequestStatus.PENDING
    assert req.approved_total_usd is None

    workflow.approve(db, org.coo, req, None, SYSTEM)
    assert second.status == StepStatus.APPROVED
    assert req.status == RequestStatus.APPROVED
    assert req.approved_total_usd == Decimal("6000.00")
    assert req.approved_revision == 1
    # Each approval is tied to the exact content that was approved.
    assert first.approved_content_hash == second.approved_content_hash == req.revisions[0].content_hash


def test_requester_cannot_approve_their_own_request(org, db):
    req = org.submit(org.engineer, org.office, 300)

    with pytest.raises(NotAllowed, match="your own request"):
        workflow.approve(db, org.engineer, req, None, SYSTEM)


@pytest.mark.parametrize("someone_else", ["coo", "people_head", "clerk"])  # later approver, unrelated manager, finance
def test_only_the_approver_whose_turn_it_is_can_approve(org, db, someone_else):
    req = org.submit(org.engineer, org.office, 6000)  # tech lead, then COO

    with pytest.raises(NotAllowed, match="waiting for"):
        workflow.approve(db, org.users[someone_else], req, None, SYSTEM)
    assert org.key_of(req.pending_step.approver) == "tech_lead"


def test_rejecting_needs_a_reason_skips_later_steps_and_tells_the_requester(org, db):
    req = org.submit(org.engineer, org.office, 6000)

    with pytest.raises(DomainError) as exc:
        workflow.reject(db, org.tech_lead, req, "  ", None, SYSTEM)
    assert exc.value.code == "reason_required"

    workflow.reject(db, org.tech_lead, req, "Not in budget", "Try again in January", SYSTEM)

    first, second = req.current_steps
    assert req.status == RequestStatus.REJECTED
    assert (first.status, first.decision_reason) == (StepStatus.REJECTED, "Not in budget")
    assert second.status == StepStatus.SKIPPED
    [note] = org.notifications_for(org.engineer, "rejected")
    assert "Not in budget: Try again in January" in note.body
    assert len(org.emails_for(org.engineer, "rejected")) == 1


def test_resubmitting_after_a_return_starts_a_new_revision_with_fresh_steps(org, db):
    req = org.submit(org.engineer, org.office, 6000)
    workflow.return_to_requester(db, org.tech_lead, req, "Please get a second quote", SYSTEM)
    assert req.status == RequestStatus.RETURNED

    workflow.update_draft(db, org.engineer, req, {"amount": Decimal("5400"), "supplier": "Emirates Stationers"})
    workflow.submit(db, org.engineer, req, SYSTEM)

    assert req.status == RequestStatus.PENDING
    assert req.revision == 2
    assert [(r.number, r.kind, r.status) for r in req.revisions] == [(1, "submission", "returned"), (2, "resubmission", "pending")]
    assert [s.status for s in req.steps if s.revision == 1] == [StepStatus.RETURNED, StepStatus.SKIPPED]
    assert [(org.key_of(s.approver), s.status) for s in req.current_steps] == [
        ("tech_lead", StepStatus.PENDING),
        ("coo", StepStatus.WAITING),
    ]


# ---------------------------------------------------------------- changes after approval


@pytest.fixture
def approved(org):
    """USD 1,000 of office supplies, approved by the tech lead."""
    return org.approve_all(org.submit(org.engineer, org.office, 1000))


@pytest.mark.parametrize("new_amount", ["1040.00", "1050.00"])  # +4%, and exactly the 5% tolerance
def test_change_within_the_5pct_tolerance_applies_immediately_without_new_approval(org, db, approved, new_amount):
    _, _, needs_reapproval = workflow.amend(db, org.engineer, approved, {"amount": Decimal(new_amount)}, "Delivery charge added", SYSTEM)

    assert needs_reapproval is False
    assert approved.status == RequestStatus.APPROVED
    assert approved.approved_total_usd == Decimal(new_amount)
    assert (approved.revision, approved.approved_revision) == (2, 2)
    assert approved.current_steps == []
    assert approved.revisions[-1].status == "applied"


def test_change_above_tolerance_needs_approval_while_the_original_approval_stays_in_force(org, db, approved):
    _, _, needs_reapproval = workflow.amend(db, org.engineer, approved, {"amount": Decimal("1200")}, "Supplier raised prices", SYSTEM)

    assert needs_reapproval is True
    assert approved.status == RequestStatus.PENDING
    assert approved.is_amendment_in_progress
    assert [(org.key_of(s.approver), s.status) for s in approved.current_steps] == [("tech_lead", StepStatus.PENDING)]
    assert approved.total_usd == Decimal("1200.00")
    assert approved.approved_total_usd == Decimal("1000.00")
    assert approved.approved_revision == 1


def test_rejecting_a_change_restores_the_approved_request(org, db, approved):
    workflow.amend(db, org.engineer, approved, {"amount": Decimal("1200")}, "Supplier raised prices", SYSTEM)

    workflow.reject(db, org.tech_lead, approved, "Get another quote", None, SYSTEM)

    assert approved.status == RequestStatus.APPROVED
    assert approved.amount == approved.total_usd == approved.approved_total_usd == Decimal("1000.00")
    assert approved.approved_revision == 1
    assert approved.revisions[-1].status == "rejected"


def test_change_within_tolerance_still_needs_approval_if_it_brings_in_a_new_approver(org, db):
    req = org.approve_all(org.submit(org.engineer, org.office, 4900))  # tech lead only

    # +4.1% is within tolerance, but USD 5,100 now also needs the COO, who hasn't seen it.
    _, _, needs_reapproval = workflow.amend(db, org.engineer, req, {"amount": Decimal("5100")}, "Bigger order", SYSTEM)

    assert needs_reapproval is True
    assert org.approvers(req) == ["tech_lead", "coo"]
    assert req.approved_total_usd == Decimal("4900.00")
