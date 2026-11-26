"""Leavers: deactivating someone hands their pending approvals to their manager (workflow.deactivate_user)."""

from app import workflow
from app.audit import SYSTEM
from app.models import RequestStatus, StepStatus


def test_leavers_pending_approval_moves_to_their_manager(org, db):
    req = org.submit(org.site_worker, org.office, 400)  # waits for the site manager

    result = workflow.deactivate_user(db, org.tech_lead, org.site_mgr, SYSTEM)  # the tech lead is the administrator

    assert result == {"steps_reassigned": 1, "reports_moved": 1}
    [step] = req.current_steps
    assert (org.key_of(step.approver), step.status) == ("coo", StepStatus.PENDING)
    assert f"Reassigned from {org.site_mgr.name} (left)" in step.routing_note
    assert org.site_worker.manager_id == org.coo.id
    assert len(org.notifications_for(org.coo, "approval_needed")) == 1

    workflow.approve(db, org.coo, req, None, SYSTEM)
    assert req.status == RequestStatus.APPROVED


def test_reassigned_approval_merges_with_a_later_step_for_the_same_person(org, db):
    req = org.submit(org.site_worker, org.office, 6000)  # site manager, then COO

    workflow.deactivate_user(db, org.tech_lead, org.site_mgr, SYSTEM)

    first, second = req.current_steps
    assert (org.key_of(first.approver), first.status) == ("coo", StepStatus.PENDING)
    assert first.reasons == ["Line manager", "COO: USD 5,000 or more"]
    assert second.status == StepStatus.SKIPPED

    workflow.approve(db, org.coo, req, None, SYSTEM)  # one approval covers both
    assert req.status == RequestStatus.APPROVED
