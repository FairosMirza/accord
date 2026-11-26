"""Cover while away: a stand-in approves on someone's behalf, but only within the dates set."""

from datetime import date, datetime

import pytest
from sqlalchemy import select

from app import reports, workflow
from app.audit import SYSTEM
from app.errors import DomainError, NotAllowed
from app.models import AuditEvent, RequestStatus, StepStatus, clock_at
from app.timeutil import COMPANY_TZ

MONDAY = datetime(2026, 11, 30, 9, 0, tzinfo=COMPANY_TZ)
COVER_STARTS, COVER_ENDS = date(2026, 12, 1), date(2026, 12, 10)


def cover(db, principal, stand_in):
    """The principal sets up cover for 1-10 December, on the Monday before."""
    with clock_at(MONDAY):
        return workflow.create_delegation(db, principal, principal, stand_in, COVER_STARTS, COVER_ENDS, "Annual leave", SYSTEM)


@pytest.fixture
def waiting_for_tech_lead(org, db):
    """The engineer's request waits for the tech lead, whom the Accra site manager covers 1-10 December."""
    cover(db, org.tech_lead, org.site_mgr)
    with clock_at(MONDAY):
        return org.submit(org.engineer, org.office, 800)


@pytest.mark.parametrize(
    "moment",
    [datetime(2026, 12, 1, 0, 5, tzinfo=COMPANY_TZ), datetime(2026, 12, 10, 23, 55, tzinfo=COMPANY_TZ)],
    ids=["first-day", "last-day"],
)
def test_stand_in_can_approve_during_cover_and_it_is_recorded_on_behalf_of_the_principal(org, db, waiting_for_tech_lead, moment):
    with clock_at(moment):
        workflow.approve(db, org.site_mgr, waiting_for_tech_lead, None, SYSTEM)

    [step] = waiting_for_tech_lead.current_steps
    assert step.status == StepStatus.APPROVED
    assert step.approver_id == org.tech_lead.id
    assert step.acted_by_id == org.site_mgr.id
    assert step.on_behalf_of_id == org.tech_lead.id
    event = db.scalars(select(AuditEvent).where(AuditEvent.action == "step.approved")).one()
    assert (event.actor_id, event.on_behalf_of_id) == (org.site_mgr.id, org.tech_lead.id)


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 11, 30, 23, 55, tzinfo=COMPANY_TZ),
        datetime(2026, 12, 11, 0, 5, tzinfo=COMPANY_TZ),  # still 10 December in UTC: cover follows Dubai dates
    ],
    ids=["day-before", "day-after"],
)
def test_stand_in_cannot_approve_outside_the_cover_dates(org, db, waiting_for_tech_lead, moment):
    with clock_at(moment), pytest.raises(NotAllowed, match="waiting for"):
        workflow.approve(db, org.site_mgr, waiting_for_tech_lead, None, SYSTEM)

    assert waiting_for_tech_lead.pending_step.status == StepStatus.PENDING


def test_stand_in_cannot_approve_their_own_request(org, db):
    cover(db, org.ceo, org.fin_head)

    with clock_at(datetime(2026, 12, 2, 10, 0, tzinfo=COMPANY_TZ)):
        req = org.submit(org.fin_head, org.office, 300)  # waits for the CEO, whom fin_head is covering
        with pytest.raises(NotAllowed, match="your own request"):
            workflow.approve(db, org.fin_head, req, None, SYSTEM)

    assert org.key_of(req.pending_step.approver) == "ceo"


@pytest.mark.parametrize("stand_in", ["ceo", "fin_head"])
def test_the_coo_can_be_covered_by_the_ceo_or_the_finance_lead(org, db, stand_in):
    delegation = cover(db, org.coo, org.users[stand_in])

    assert delegation.delegate_id == org.users[stand_in].id


@pytest.mark.parametrize("stand_in", ["tech_lead", "clerk", "people_head"])  # admin and people manager, finance, department head
def test_nobody_else_can_cover_the_coo(org, db, stand_in):
    with pytest.raises(DomainError, match="must be one of") as exc:
        cover(db, org.coo, org.users[stand_in])

    assert exc.value.code == "stand_in_not_allowed"


def test_a_managers_stand_in_must_manage_people_themselves(org, db):
    with pytest.raises(DomainError, match="people managers") as exc:
        cover(db, org.tech_lead, org.engineer)  # no direct reports
    assert exc.value.code == "stand_in_not_allowed"

    delegation = cover(db, org.tech_lead, org.site_mgr)  # manages the Accra site worker
    assert delegation.delegate_id == org.site_mgr.id


def test_stand_in_who_is_already_in_the_chain_cannot_add_a_second_approval(org, db):
    """One person, one approval. The CEO approves the Finance head's IT request as line manager,
    so covering for the COO doesn't let the CEO approve the COO step too: it stays with the COO."""
    cover(db, org.coo, org.ceo)
    with clock_at(datetime(2026, 12, 2, 10, 0, tzinfo=COMPANY_TZ)):
        req = org.submit(org.fin_head, org.software, 500)
        workflow.approve(db, org.ceo, req, None, SYSTEM)
        assert req.pending_step.approver_id == org.coo.id

        with pytest.raises(NotAllowed, match="already an approver"):
            workflow.approve(db, org.ceo, req, None, SYSTEM)
        assert req.id not in {r.id for r in reports.waiting_for(db, org.ceo)}

        workflow.approve(db, org.coo, req, None, SYSTEM)
    assert req.status == RequestStatus.APPROVED
    assert {s.acted_by_id for s in req.current_steps} == {org.ceo.id, org.coo.id}
