from datetime import date

from sqlalchemy import exists, literal, select
from sqlalchemy.orm import Session

from app.models import Delegation, Department, User


class Directory:
    """Org-chart lookups used by routing and visibility rules."""

    def __init__(self, db: Session):
        self.db = db

    def user(self, user_id: int | None) -> User | None:
        return self.db.get(User, user_id) if user_id else None

    def holder_of(self, role: str) -> User | None:
        return self.db.execute(
            select(User).where(User.is_active.is_(True), User.roles.contains([role])).order_by(User.id).limit(1)
        ).scalar()

    def holders_of(self, roles: list[str] | set[str]) -> list[User]:
        if not roles:
            return []
        return list(
            self.db.execute(
                select(User).where(User.is_active.is_(True), User.roles.overlap(list(roles))).order_by(User.name)
            ).scalars()
        )

    def department_head(self, department_id: int | None) -> User | None:
        if not department_id:
            return None
        dept = self.db.get(Department, department_id)
        return dept.head if dept else None

    def headed_department_ids(self, user_id: int) -> list[int]:
        return list(self.db.execute(select(Department.id).where(Department.head_id == user_id)).scalars())

    def report_ids(self, manager_id: int) -> list[int]:
        """Everyone below this person in the reporting line (direct and indirect)."""
        tree = (
            select(User.id.label("id"), literal(1).label("depth"))
            .where(User.manager_id == manager_id)
            .cte("tree", recursive=True)
        )
        tree = tree.union(
            select(User.id, tree.c.depth + 1).join(tree, User.manager_id == tree.c.id).where(tree.c.depth < 20)
        )
        return list(self.db.execute(select(tree.c.id).distinct()).scalars())

    def has_reports(self, user_id: int) -> bool:
        return bool(
            self.db.execute(
                select(exists().where(User.manager_id == user_id, User.is_active.is_(True)))
            ).scalar()
        )

    def active_delegation(self, principal_id: int, delegate_id: int, on: date) -> Delegation | None:
        return self.db.execute(
            select(Delegation).where(
                Delegation.principal_id == principal_id,
                Delegation.delegate_id == delegate_id,
                Delegation.revoked_at.is_(None),
                Delegation.starts_on <= on,
                Delegation.ends_on >= on,
            )
        ).scalar()

    def active_delegates_for(self, principal_id: int, on: date) -> list[User]:
        rows = self.db.execute(
            select(Delegation).where(
                Delegation.principal_id == principal_id,
                Delegation.revoked_at.is_(None),
                Delegation.starts_on <= on,
                Delegation.ends_on >= on,
            )
        ).scalars()
        return [d.delegate for d in rows if d.delegate.is_active]

    def principals_delegating_to(self, delegate_id: int, on: date) -> list[int]:
        return list(
            self.db.execute(
                select(Delegation.principal_id).where(
                    Delegation.delegate_id == delegate_id,
                    Delegation.revoked_at.is_(None),
                    Delegation.starts_on <= on,
                    Delegation.ends_on >= on,
                )
            ).scalars()
        )
