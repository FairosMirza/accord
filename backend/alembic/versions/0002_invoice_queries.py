"""Invoice queries and corrected invoices

Finance can query an invoice with the supplier (it isn't payable meanwhile) and
replace it with the corrected one. Replaced invoices are kept, marked void.

Revision ID: 0002
Revises: 0001
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("query_reason", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("queried_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("invoices", sa.Column("queried_by_id", sa.Integer(), nullable=True))
    op.add_column("invoices", sa.Column("query_resolution", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("replaces_invoice_id", sa.Integer(), nullable=True))
    op.add_column("invoices", sa.Column("void_reason", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("invoices", sa.Column("voided_by_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_invoices_queried_by_id", "invoices", "users", ["queried_by_id"], ["id"])
    op.create_foreign_key("fk_invoices_voided_by_id", "invoices", "users", ["voided_by_id"], ["id"])
    op.create_foreign_key("fk_invoices_replaces_invoice_id", "invoices", "invoices", ["replaces_invoice_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_invoices_replaces_invoice_id", "invoices", type_="foreignkey")
    op.drop_constraint("fk_invoices_voided_by_id", "invoices", type_="foreignkey")
    op.drop_constraint("fk_invoices_queried_by_id", "invoices", type_="foreignkey")
    for column in ("voided_by_id", "voided_at", "void_reason", "replaces_invoice_id", "query_resolution", "queried_by_id", "queried_at", "query_reason"):
        op.drop_column("invoices", column)
