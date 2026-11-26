"""Tamper-evident audit trail.

Each event stores the SHA-256 of (previous hash + canonical event content), so any
edit, deletion or re-ordering of history breaks the chain and is detected by
`verify_chain`. On top of that, a database trigger rejects UPDATE/DELETE/TRUNCATE.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditEvent, SpendRequest, User, utcnow

GENESIS_HASH = "0" * 64
_CHAIN_LOCK_KEY = 724_001


@dataclass(frozen=True)
class ClientInfo:
    ip: str | None = None
    user_agent: str | None = None


SYSTEM = ClientInfo()


def _canonical(
    *,
    occurred_at: datetime,
    actor_id: int | None,
    on_behalf_of_id: int | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    request_id: int | None,
    summary: str,
    data: dict[str, Any],
) -> str:
    payload = {
        "occurred_at": occurred_at.astimezone(UTC).isoformat(),
        "actor_id": actor_id,
        "on_behalf_of_id": on_behalf_of_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "request_id": request_id,
        "summary": summary,
        "data": data,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _hash(prev_hash: str, canonical: str) -> str:
    return hashlib.sha256((prev_hash + canonical).encode()).hexdigest()


def _jsonable(value: Any) -> Any:
    # Round-trip through JSON so what we hash is exactly what JSONB stores and returns.
    return json.loads(json.dumps(value, default=str))


def record(
    db: Session,
    *,
    action: str,
    summary: str,
    entity_type: str,
    entity_id: str | int | None = None,
    actor: User | None = None,
    on_behalf_of: User | None = None,
    request: SpendRequest | None = None,
    data: dict[str, Any] | None = None,
    client: ClientInfo = SYSTEM,
) -> AuditEvent:
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK_KEY})
    prev = db.execute(select(AuditEvent.hash).order_by(AuditEvent.id.desc()).limit(1)).scalar()
    prev_hash = prev or GENESIS_HASH
    occurred_at = utcnow()
    payload = _jsonable(data or {})
    fields = dict(
        occurred_at=occurred_at,
        actor_id=actor.id if actor else None,
        on_behalf_of_id=on_behalf_of.id if on_behalf_of else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        request_id=request.id if request else None,
        summary=summary,
        data=payload,
    )
    event = AuditEvent(
        **fields,
        ip=client.ip,
        user_agent=(client.user_agent or "")[:300] or None,
        prev_hash=prev_hash,
        hash=_hash(prev_hash, _canonical(**fields)),
    )
    db.add(event)
    db.flush()
    return event


@dataclass
class ChainReport:
    ok: bool
    events_checked: int
    first_bad_event_id: int | None = None
    problem: str | None = None


def verify_chain(db: Session) -> ChainReport:
    prev_hash = GENESIS_HASH
    count = 0
    rows = db.execute(select(AuditEvent).order_by(AuditEvent.id)).scalars()
    for ev in rows:
        count += 1
        if ev.prev_hash != prev_hash:
            return ChainReport(False, count, ev.id, "Event does not follow the previous event")
        expected = _hash(
            prev_hash,
            _canonical(
                occurred_at=ev.occurred_at,
                actor_id=ev.actor_id,
                on_behalf_of_id=ev.on_behalf_of_id,
                action=ev.action,
                entity_type=ev.entity_type,
                entity_id=ev.entity_id,
                request_id=ev.request_id,
                summary=ev.summary,
                data=ev.data,
            ),
        )
        if expected != ev.hash:
            return ChainReport(False, count, ev.id, "Event content does not match its hash")
        prev_hash = ev.hash
    return ChainReport(True, count)
