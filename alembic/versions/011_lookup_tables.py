"""Global lookup tables for company size and industry, replacing hardcoded frontend arrays."""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_lookup_tables"
down_revision: Union[str, None] = "010_user_contact_preferences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COMPANY_SIZES = [
    "1-10",
    "11-50",
    "51-200",
    "201-500",
    "501-1000",
    "1000+",
]

INDUSTRIES = [
    "Technology & Software",
    "Healthcare",
    "Financial Services",
    "Retail & E-commerce",
    "Manufacturing",
    "Education",
    "Real Estate",
    "Professional Services",
    "Media & Entertainment",
    "Nonprofit",
    "Hospitality & Travel",
    "Construction",
    "Legal Services",
    "Government & Public Sector",
    "Telecommunications",
    "Energy & Utilities",
    "Automotive",
    "Insurance",
    "Consumer Goods",
    "Transportation & Logistics",
    "Agriculture",
    "Other",
]


def upgrade() -> None:
    company_sizes = op.create_table(
        "company_sizes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("label", sa.String(length=32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("label", name="uq_company_sizes_label"),
    )

    industries = op.create_table(
        "industries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_industries_name"),
    )

    op.bulk_insert(
        company_sizes,
        [{"id": uuid.uuid4(), "label": label, "sort_order": i} for i, label in enumerate(COMPANY_SIZES)],
    )
    op.bulk_insert(
        industries,
        [{"id": uuid.uuid4(), "name": name, "sort_order": i} for i, name in enumerate(INDUSTRIES)],
    )


def downgrade() -> None:
    op.drop_table("industries")
    op.drop_table("company_sizes")
