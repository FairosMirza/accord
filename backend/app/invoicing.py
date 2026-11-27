"""Where an approved request stands against its invoices, and who owns the next step.

An invoice beyond the approval (more than the tolerance when it was recorded) opens a
difference. It stays open until someone with authority approves a revised total that
covers it, or Finance replaces the invoice with a corrected one. Until then the request
says who has to act:
  * the requester, to review the difference and submit the revised total
  * the approver, while that revised total is waiting for them
  * Finance, while an invoice is queried with the supplier, or after the revised total was rejected
Payment itself is not blocked by an open difference (pending the COO's decision).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.models import Invoice, InvoiceStatus, RequestStatus, SpendRequest, User

OPEN_STATUSES = (RequestStatus.APPROVED, RequestStatus.PENDING)


def live_invoices(req: SpendRequest) -> list[Invoice]:
    return [i for i in req.invoices if i.is_live]


def approved_currency(req: SpendRequest) -> str:
    """Currency of the approved version. It differs from the request only while a change is pending."""
    if req.approved_revision is not None and req.approved_revision != req.revision:
        approved = next((r for r in req.revisions if r.number == req.approved_revision), None)
        if approved is not None:
            return approved.data.get("currency") or req.currency
    return req.currency


@dataclass
class Excess:
    over_usd: Decimal
    invoiced_usd: Decimal
    approved_usd: Decimal
    currency: str
    over_amount: Decimal | None  # in the approved currency, when every invoice is in it
    invoiced_amount: Decimal | None


def excess(req: SpendRequest) -> Excess | None:
    if req.approved_total_usd is None or req.status not in OPEN_STATUSES:
        return None
    invoices = live_invoices(req)
    if not any(i.exceeds_approval for i in invoices):
        return None
    invoiced_usd = sum((i.amount_usd for i in invoices), Decimal(0))
    approved_usd = Decimal(req.approved_total_usd)
    currency = approved_currency(req)
    if req.approved_total_amount is not None and all(i.currency == currency for i in invoices):
        # Compare like with like, so an approved revised total closes the difference whatever FX did.
        invoiced_amount = sum((i.amount for i in invoices), Decimal(0))
        over_amount = invoiced_amount - Decimal(req.approved_total_amount)
        if over_amount <= 0:
            return None
        over_usd = (over_amount * invoiced_usd / invoiced_amount).quantize(Decimal("0.01"))
        return Excess(over_usd, invoiced_usd, approved_usd, currency, over_amount, invoiced_amount)
    if invoiced_usd <= approved_usd:
        return None
    return Excess(invoiced_usd - approved_usd, invoiced_usd, approved_usd, currency, None, None)


@dataclass
class NextStep:
    kind: str  # requester | approval | finance | corrected_invoice
    owner: User | None
    label: str


def next_step(req: SpendRequest) -> NextStep | None:
    if req.approved_total_usd is None or req.status not in OPEN_STATUSES:
        return None
    queried = [i for i in req.invoices if i.status == InvoiceStatus.QUERIED]
    if queried:
        inv = queried[0]
        supplier = inv.supplier or req.supplier or "the supplier"
        return NextStep("corrected_invoice", inv.queried_by, f"Awaiting corrected invoice from {supplier}")
    if excess(req) is None:
        return None
    step = req.pending_step if req.is_amendment_in_progress else None
    if step is not None:
        return NextStep("approval", step.approver, f"Revised total awaiting approval from {step.approver.name}")
    flagged = [i for i in live_invoices(req) if i.exceeds_approval]
    since = max((t for i in flagged if (t := i.queried_at or i.received_at)), default=None)
    rejected = since is not None and any(
        r.kind == "amendment" and r.status == "rejected" and r.decided_at and r.decided_at >= since for r in req.revisions
    )
    if rejected:
        owner = flagged[-1].received_by
        return NextStep("finance", owner, f"Revised total rejected · {owner.name if owner else 'Finance'} to query the invoice")
    return NextStep("requester", req.requester, f"Awaiting amendment from {req.requester.name}")


def amendment_change(req: SpendRequest) -> dict | None:
    """Approved and requested totals for a change that is waiting for approval."""
    if not req.is_amendment_in_progress or req.approved_total_usd is None:
        return None
    current = next((r for r in req.revisions if r.number == req.revision), None)
    approved_usd = Decimal(req.approved_total_usd)
    pct = (Decimal(req.total_usd) - approved_usd) / approved_usd * 100 if approved_usd else None
    return {
        "approved_total_amount": float(req.approved_total_amount),
        "approved_currency": approved_currency(req),
        "approved_total_usd": float(approved_usd),
        "requested_total_amount": float(req.total_amount),
        "requested_currency": req.currency,
        "requested_total_usd": float(req.total_usd),
        "change_pct": round(float(pct), 1) if pct is not None else None,
        "reason": current.reason if current else None,
    }
