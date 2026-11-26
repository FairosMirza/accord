"""Who approves what: the default authority matrix applied to submitted requests (policy.compute_route)."""

from decimal import Decimal

import pytest

from app.models import StepStatus


def test_small_general_spend_needs_only_the_line_manager(org):
    req = org.submit(org.engineer, org.office, 250)

    assert org.approvers(req) == ["tech_lead"]
    assert req.current_steps[0].reasons == ["Line manager"]


@pytest.mark.parametrize(("amount", "approvers"), [("4999.99", ["tech_lead"]), ("5000.00", ["tech_lead", "coo"])])
def test_general_spend_of_usd_5000_or_more_also_needs_the_coo(org, amount, approvers):
    req = org.submit(org.engineer, org.office, amount)

    assert org.approvers(req) == approvers


def test_it_spend_always_needs_the_coo_even_for_usd_10(org):
    req = org.submit(org.engineer, org.software, 10)

    assert org.approvers(req) == ["tech_lead", "coo"]
    assert req.current_steps[1].rule_keys == ["coo-it"]


@pytest.mark.parametrize(("amount", "approvers"), [("2999", ["tech_lead"]), ("3000", ["tech_lead", "coo"])])
def test_travel_of_usd_3000_or_more_also_needs_the_coo(org, amount, approvers):
    req = org.submit(org.engineer, org.flights, amount)

    assert org.approvers(req) == approvers


def test_coo_who_is_also_the_line_manager_approves_it_spend_once_for_both_reasons(org):
    req = org.submit(org.tech_lead, org.software, 1200)  # the tech lead reports to the COO

    [step] = req.current_steps
    assert org.key_of(step.approver) == "coo"
    assert step.reasons == ["Line manager", "COO: all IT spend"]
    assert step.rule_keys == ["line-manager", "coo-it"]
    assert step.status == StepStatus.PENDING


def test_coo_cannot_approve_their_own_large_request_so_it_goes_only_to_the_ceo(org):
    req = org.submit(org.coo, org.office, 12000)

    [step] = req.current_steps
    assert org.key_of(step.approver) == "ceo"
    assert step.rule_keys == ["line-manager", "coo-general"]
    assert "can't approve their own request" in step.routing_note


def test_ceo_own_request_goes_to_the_fallback_approver_the_coo(org):
    req = org.submit(org.ceo, org.office, 400)

    assert org.approvers(req) == ["coo"]
    assert "fallback approver" in req.current_steps[0].routing_note


@pytest.mark.parametrize(
    ("amount_ghs", "total_usd", "approvers"),
    [("56179", "4999.93", ["site_mgr"]), ("56180", "5000.02", ["site_mgr", "coo"])],
)
def test_local_currency_spend_is_routed_on_its_usd_value(org, amount_ghs, total_usd, approvers):
    req = org.submit(org.site_worker, org.office, amount_ghs, currency="GHS")  # 1 GHS = 0.0890 USD

    assert req.total_usd == Decimal(total_usd)
    assert org.approvers(req) == approvers


@pytest.mark.parametrize(
    ("term_months", "total_usd", "approvers"),
    [
        (36, "7200.00", ["tech_lead", "coo"]),  # USD 200 a month for three years
        (None, "2400.00", ["tech_lead"]),  # open-ended: judged on 12 months
    ],
)
def test_recurring_spend_is_routed_on_the_whole_commitment_not_one_payment(org, term_months, total_usd, approvers):
    req = org.submit(org.engineer, org.office, 200, payment_type="recurring", billing_period="monthly", term_months=term_months)

    assert req.total_usd == Decimal(total_usd)
    assert org.approvers(req) == approvers


def test_inactive_line_manager_is_skipped_in_favour_of_their_own_manager(org):
    org.tech_lead.is_active = False

    req = org.submit(org.engineer, org.office, 250)

    assert org.approvers(req) == ["coo"]
    assert "no longer active" in req.current_steps[0].routing_note
