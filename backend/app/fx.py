from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import DomainError
from app.models import FxRate

CENT = Decimal("0.01")


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def usd_per_unit(db: Session, currency: str, on: date) -> Decimal:
    """Finance-maintained rate in force on the given date (latest rate on or before it)."""
    currency = currency.upper()
    if currency == get_settings().base_currency:
        return Decimal(1)
    rate = db.execute(
        select(FxRate.usd_per_unit)
        .where(FxRate.currency == currency, FxRate.effective_date <= on)
        .order_by(FxRate.effective_date.desc())
        .limit(1)
    ).scalar()
    if rate is None:
        # Fall back to the earliest known rate rather than blocking a request dated before it.
        rate = db.execute(
            select(FxRate.usd_per_unit)
            .where(FxRate.currency == currency)
            .order_by(FxRate.effective_date)
            .limit(1)
        ).scalar()
    if rate is None:
        raise DomainError(
            f"There is no exchange rate for {currency} yet. Ask Finance to add one.", "fx_missing"
        )
    return Decimal(rate)


def to_usd(amount: Decimal, rate: Decimal) -> Decimal:
    return money(Decimal(amount) * Decimal(rate))


def supported_currencies(db: Session) -> list[str]:
    base = get_settings().base_currency
    others = db.execute(select(FxRate.currency).group_by(FxRate.currency).order_by(func.min(FxRate.currency))).scalars()
    return [base, *[c for c in others if c != base]]
