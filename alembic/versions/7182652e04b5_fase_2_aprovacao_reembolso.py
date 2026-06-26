"""fase 2: aprovacao/reembolso — status, decisão e enum expandido

Revision ID: 7182652e04b5
Revises: 55df6f3252eb
Create Date: 2026-06-26 12:00:00.000000

Expande `expense_status_enum` de (pending_review, registered) para
(pending_review, submitted, approved, rejected, reimbursed) e migra os gastos
'registered' existentes para 'approved'. Como o Postgres não remove valores de
um enum, recriamos o tipo e fazemos o cast da coluna com USING.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7182652e04b5'
down_revision: Union[str, None] = '55df6f3252eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_VALUES = ('pending_review', 'submitted', 'approved', 'rejected', 'reimbursed')
_OLD_VALUES = ('pending_review', 'registered')


def upgrade() -> None:
    # Recria o enum com o conjunto novo; 'registered' vira 'approved' no cast.
    op.execute("ALTER TYPE expense_status_enum RENAME TO expense_status_enum_old")
    sa.Enum(*_NEW_VALUES, name="expense_status_enum").create(op.get_bind())
    op.execute(
        "ALTER TABLE expenses ALTER COLUMN status TYPE expense_status_enum "
        "USING (CASE status::text WHEN 'registered' THEN 'approved' "
        "ELSE status::text END)::expense_status_enum"
    )
    op.execute("DROP TYPE expense_status_enum_old")

    op.add_column('expenses', sa.Column('approver_id', sa.Integer(), nullable=True))
    op.add_column('expenses', sa.Column('decision_comment', sa.String(length=1024), nullable=True))
    op.add_column(
        'expenses',
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('expenses', 'decided_at')
    op.drop_column('expenses', 'decision_comment')
    op.drop_column('expenses', 'approver_id')

    # Volta ao enum antigo; tudo que não for pending_review vira 'registered'.
    op.execute("ALTER TYPE expense_status_enum RENAME TO expense_status_enum_new")
    sa.Enum(*_OLD_VALUES, name="expense_status_enum").create(op.get_bind())
    op.execute(
        "ALTER TABLE expenses ALTER COLUMN status TYPE expense_status_enum "
        "USING (CASE status::text WHEN 'pending_review' THEN 'pending_review' "
        "ELSE 'registered' END)::expense_status_enum"
    )
    op.execute("DROP TYPE expense_status_enum_new")
