"""Finance: matching invoices to what was approved, and releasing payment."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app import workflow
from app.audit import SYSTEM
from app.errors import Conflict, DomainError, NotAllowed
from app.invoicing import excess, next_step
from app.models import FxRate, InvoiceStatus, clock_at
from app.serializers import finance_state


@pytest.fixture
def approved(org):
    """USD 1,000 of office supplies, approved by the tech lead."""
    return org.approve_all(org.submit(org.engineer, org.office, 1000))


def test_invoice_up_to_5pct_over_the_approved_amount_is_accepted(org, approved):
    invoice = org.record_invoice(org.clerk, approved, "INV-100", "1050.00")

    assert invoice.exceeds_approval is False


def test_invoice_more_than_5pct_over_the_approved_amount_needs_an_override_reason(org, approved):
    with pytest.raises(DomainError, match="more than the approved") as exc:
        org.record_invoice(org.clerk, approved, "INV-100", "1050.01")
    assert exc.value.code == "exceeds_approval"

    invoice = org.record_invoice(org.clerk, approved, "INV-100", "1050.01", override_reason="Fuel surcharge agreed with the COO")

    assert invoice.exceeds_approval is True
    assert invoice.override_reason == "Fuel surcharge agreed with the COO"


def test_invoices_on_the_same_request_count_together_against_the_approval(org, approved):
    org.record_invoice(org.clerk, approved, "INV-1", "600")

    with pytest.raises(DomainError) as exc:
        org.record_invoice(org.clerk, approved, "INV-2", "500")  # USD 1,100 in total
    assert exc.value.code == "exceeds_approval"


def test_the_same_invoice_number_cannot_be_recorded_twice_on_a_request(org, approved):
    org.record_invoice(org.clerk, approved, "INV-7", "400")

    with pytest.raises(Conflict, match="duplicate"):
        org.record_invoice(org.clerk, approved, "inv-7", "400")
    assert len(approved.invoices) == 1


def test_finance_cannot_release_payment_on_their_own_request(org, db):
    req = org.approve_all(org.submit(org.clerk, org.office, 500))  # the clerk's own spend
    invoice = org.record_invoice(org.fin_head, req, "INV-55", "500")

    with pytest.raises(NotAllowed, match="your own request"):
        workflow.mark_paid(db, org.clerk, invoice, date(2026, 11, 25), "PAY-1", SYSTEM)
    assert invoice.status == InvoiceStatus.RECEIVED

    workflow.mark_paid(db, org.fin_head, invoice, date(2026, 11, 25), "PAY-1", SYSTEM)
    assert (invoice.status, invoice.paid_by_id) == (InvoiceStatus.PAID, org.fin_head.id)


# ---------------------------------------------------------------- invoices above the approval


def invoice_over(org, req, number="INV-100", amount="1100"):
    return org.record_invoice(org.clerk, req, number, amount, override_reason="Warranty upgrade agreed by email")


def test_an_invoice_above_the_approval_shows_the_difference_and_asks_the_requester_to_review_it(org, approved):
    invoice_over(org, approved)

    finance = finance_state(approved)
    assert (finance["excess"]["over_usd"], finance["excess"]["note"]) == (100.0, "Warranty upgrade agreed by email")
    assert finance["next_step"]["kind"] == "requester"
    assert finance["next_step"]["owner"]["id"] == org.engineer.id
    assert finance["next_step"]["label"] == "Awaiting amendment from Leo Park"
    assert len(org.emails_for(org.engineer, "invoice_difference")) == 1


def test_the_difference_waits_for_the_approver_then_closes_once_the_revised_total_is_approved(org, db, approved):
    invoice_over(org, approved)
    workflow.amend(db, org.engineer, approved, {"amount": Decimal("1100")}, "Warranty upgrade on the invoice", SYSTEM)

    step = next_step(approved)
    assert (step.kind, step.owner.id) == ("approval", org.tech_lead.id)

    org.approve_all(approved)
    assert excess(approved) is None
    assert next_step(approved) is None


def test_if_the_revised_total_is_rejected_finance_owns_the_difference(org, db, approved):
    invoice_over(org, approved)
    workflow.amend(db, org.engineer, approved, {"amount": Decimal("1100")}, "Warranty upgrade on the invoice", SYSTEM)
    workflow.reject(db, org.tech_lead, approved, "Not agreed", None, SYSTEM)

    step = next_step(approved)
    assert (step.kind, step.owner.id) == ("finance", org.clerk.id)
    assert excess(approved).over_usd == Decimal("100.00")


def test_paying_an_invoice_above_the_approval_is_still_allowed_until_the_coo_decides(org, db, approved):
    invoice = invoice_over(org, approved)

    workflow.mark_paid(db, org.clerk, invoice, date(2026, 11, 25), "PAY-1", SYSTEM)

    assert invoice.status == InvoiceStatus.PAID
    assert next_step(approved).kind == "requester"  # the approval record still needs the revised total


def test_a_queried_invoice_cannot_be_paid_and_a_corrected_one_replaces_it(org, db, approved):
    wrong = invoice_over(org, approved)
    workflow.query_invoice(db, org.clerk, wrong, "Filter kit billed twice", SYSTEM)

    step = next_step(approved)
    assert (step.kind, step.owner.id) == ("corrected_invoice", org.clerk.id)
    with pytest.raises(Conflict, match="queried"):
        workflow.mark_paid(db, org.clerk, wrong, date(2026, 11, 25), "PAY-1", SYSTEM)

    corrected = org.record_invoice(org.clerk, approved, "INV-100", "1000", replaces=wrong)  # suppliers often reuse the number

    assert wrong.status == InvoiceStatus.VOID
    assert wrong.void_reason == "Replaced by corrected invoice INV-100"
    assert finance_state(approved)["invoiced_usd"] == 1000.0
    assert next_step(approved) is None
    workflow.mark_paid(db, org.clerk, corrected, date(2026, 11, 25), "PAY-1", SYSTEM)
    assert corrected.status == InvoiceStatus.PAID


def test_accepting_a_queried_invoice_as_billed_hands_the_difference_back_to_the_requester(org, db, approved):
    invoice = invoice_over(org, approved)
    workflow.query_invoice(db, org.clerk, invoice, "Checking the warranty line", SYSTEM)

    workflow.accept_invoice(db, org.clerk, invoice, "Dell confirmed the warranty upgrade", SYSTEM)

    assert (invoice.status, invoice.query_resolution) == (InvoiceStatus.RECEIVED, "Dell confirmed the warranty upgrade")
    assert next_step(approved).kind == "requester"
    assert len(org.emails_for(org.engineer, "invoice_difference")) == 2


def test_a_revised_total_in_local_currency_closes_the_difference_even_after_the_rate_moves(org, db):
    with clock_at(datetime(2026, 6, 1, 8, tzinfo=UTC)):
        req = org.approve_all(org.submit(org.site_worker, org.office, 10000, currency="GHS"))  # USD 890 at 0.0890
    db.add(FxRate(currency="GHS", usd_per_unit=Decimal("0.0950"), effective_date=date(2026, 10, 1)))
    db.flush()
    org.record_invoice(org.clerk, req, "MG-1", "12000", currency="GHS", override_reason="Extra parts")  # USD 1,140
    workflow.amend(db, org.site_worker, req, {"amount": Decimal("12000")}, "Extra parts were needed", SYSTEM)
    org.approve_all(req)

    assert req.approved_total_usd < req.invoices[0].amount_usd  # USD 1,068 at the request's rate...
    assert next_step(req) is None  # ...but GHS 12,000 is approved and GHS 12,000 invoiced
