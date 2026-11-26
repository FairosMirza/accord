from datetime import date
from zoneinfo import ZoneInfo

from app.models import utcnow

# Head office is in Dubai; "today" for delegations and reminders follows head office time.
COMPANY_TZ = ZoneInfo("Asia/Dubai")


def company_today() -> date:
    return utcnow().astimezone(COMPANY_TZ).date()
