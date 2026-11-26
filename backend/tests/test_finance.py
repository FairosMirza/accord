"""Finance: matching invoices to what was approved, and releasing payment."""

from datetime import date

import pytest

from app import workflow
from app.audit import SYSTEM
from app.errors import Conflict, DomainError, NotAllowed
from app.models import InvoiceStatus


@pytest.fixture
def approved(org):
    """USD 1,000 of office supplies, approved by the tech lead."""
    return org.approve_all(org.submit(org.engineer, org.office, 1000))


def test_invoice_up_to_5pct_over_the_approved_amount_is_accepted(org, approved):
    invoice = org.record_invoice(org.clerk, approved, "INV-100", "1050.00")

    assert invoice.exceeds_approval is False


def test_invoice_more_than_5pct_over_the_approved_amount_needs_an_override_reason(org, approved):
    with pytest.raises(DomainError, match="above the approved") as exc:
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
