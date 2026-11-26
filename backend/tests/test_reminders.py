"""Chasing approvals that have waited too long (workflow.run_reminders)."""

from datetime import datetime

from app import workflow
from app.models import clock_at
from app.timeutil import COMPANY_TZ


def dubai(month, day, hour):
    return datetime(2026, month, day, hour, 0, tzinfo=COMPANY_TZ)


def test_approver_is_reminded_once_a_step_has_waited_over_24_hours_on_a_working_day(org, db):
    with clock_at(dubai(11, 30, 9)):  # Monday morning
        req = org.submit(org.engineer, org.office, 300)
    step = req.pending_step

    with clock_at(dubai(12, 1, 8)):  # 23 hours later
        assert workflow.run_reminders(db).reminders == 0

    with clock_at(dubai(12, 1, 10)):  # 25 hours later, Tuesday
        result = workflow.run_reminders(db)

    db.refresh(step)
    assert result.reminders == 1
    assert step.reminder_count == 1
    assert step.last_reminded_at == dubai(12, 1, 10)
    assert len(org.notifications_for(org.tech_lead, "approval_reminder")) == 1
    assert len(org.emails_for(org.tech_lead, "approval_reminder")) == 1


def test_reminders_repeat_at_most_once_a_day(org, db):
    with clock_at(dubai(11, 30, 9)):
        req = org.submit(org.engineer, org.office, 300)

    for moment in (dubai(12, 1, 10), dubai(12, 1, 16), dubai(12, 2, 10)):  # the 16:00 run is too soon after 10:00
        with clock_at(moment):
            workflow.run_reminders(db)

    assert req.pending_step.reminder_count == 2


def test_no_reminders_are_sent_at_the_weekend(org, db):
    with clock_at(dubai(12, 3, 9)):  # Thursday
        req = org.submit(org.engineer, org.office, 300)

    with clock_at(dubai(12, 5, 10)):  # Saturday, 49 hours later
        result = workflow.run_reminders(db)

    assert result.skipped_weekend is True
    assert result.reminders == 0
    assert req.pending_step.reminder_count == 0
