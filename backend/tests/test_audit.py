"""The audit trail is append-only and tamper-evident (audit.verify_chain and the database trigger)."""

from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app import workflow
from app.audit import SYSTEM, verify_chain
from app.models import AuditEvent


def stored_events(db):
    db.expire_all()  # read what is in the database, not what this session remembers
    return list(db.scalars(select(AuditEvent).order_by(AuditEvent.id)))


def test_audit_chain_verifies_after_a_complete_request_lifecycle(org, db):
    req = org.approve_all(org.submit(org.engineer, org.office, 6000))
    invoice = org.record_invoice(org.clerk, req, "INV-9", "6000")
    workflow.mark_paid(db, org.fin_head, invoice, date(2026, 11, 25), "PAY-9", SYSTEM)

    events = stored_events(db)
    report = verify_chain(db)

    assert [e.action for e in events] == [
        "request.submitted",
        "step.approved",
        "step.approved",
        "request.approved",
        "invoice.recorded",
        "invoice.paid",
    ]
    assert report.ok, report.problem
    assert report.events_checked == len(events)


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_events SET summary = 'Nothing happened'", "DELETE FROM audit_events", "TRUNCATE audit_events"],
    ids=["update", "delete", "truncate"],
)
def test_database_refuses_to_change_or_remove_audit_events(org, db, statement):
    org.submit(org.engineer, org.office, 300)  # one event: request.submitted

    with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
        db.execute(text(statement))

    assert db.scalar(select(func.count()).select_from(AuditEvent)) == 1


def test_editing_a_stored_event_is_detected_and_pinpointed(org, db):
    org.approve_all(org.submit(org.engineer, org.office, 6000))
    ids = [e.id for e in stored_events(db)]

    db.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update_delete"))  # undone by the rollback
    db.execute(text("UPDATE audit_events SET summary = 'Approved by the CEO' WHERE id = :id"), {"id": ids[1]})
    db.expire_all()
    report = verify_chain(db)

    assert not report.ok
    assert report.first_bad_event_id == ids[1]
    assert report.problem == "Event content does not match its hash"


def test_removing_an_event_breaks_the_chain_at_the_next_event(org, db):
    org.approve_all(org.submit(org.engineer, org.office, 6000))
    ids = [e.id for e in stored_events(db)]

    db.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update_delete"))
    db.execute(text("DELETE FROM audit_events WHERE id = :id"), {"id": ids[1]})
    db.expire_all()
    report = verify_chain(db)

    assert not report.ok
    assert report.first_bad_event_id == ids[2]
    assert report.problem == "Event does not follow the previous event"
