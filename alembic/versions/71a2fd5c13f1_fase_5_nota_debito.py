"""fase 5: nota de débito — agregado, ciclo na nota, dados fiscais

Revision ID: 71a2fd5c13f1
Revises: 7182652e04b5
Create Date: 2026-06-26 13:00:00.000000

O ciclo de reembolso migra do gasto para a NOTA. Cria `notas_debito`, liga o
gasto a uma nota (`nota_id`), reduz `expense_status_enum` a (pending_review,
confirmed) — mapeando os estados antigos de reembolso para 'confirmed' — e
move as colunas de decisão do gasto para a nota. Adiciona os dados fiscais.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "71a2fd5c13f1"
down_revision: Union[str, None] = "7182652e04b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOTA_STATUS = ("aberta", "fechada", "aprovada", "rejeitada", "paga")
_EXP_NEW = ("pending_review", "confirmed")
_EXP_OLD = ("pending_review", "submitted", "approved", "rejected", "reimbursed")


def upgrade() -> None:
    # 1) Nova tabela de notas (cria o enum nota_status_enum junto).
    op.create_table(
        "notas_debito",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=True),
        sa.Column("competencia", sa.Date(), nullable=False),
        sa.Column("status", sa.Enum(*_NOTA_STATUS, name="nota_status_enum"), nullable=False),
        sa.Column("vencimento", sa.Date(), nullable=True),
        sa.Column("outras_retencoes", sa.Float(), nullable=False, server_default="0"),
        sa.Column("observacoes", sa.String(length=1024), nullable=True),
        sa.Column("approver_id", sa.Integer(), nullable=True),
        sa.Column("decision_comment", sa.String(length=1024), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notas_debito_org_id", "notas_debito", ["org_id"])
    op.create_index("ix_notas_debito_user_id", "notas_debito", ["user_id"])
    op.create_index("ix_notas_debito_status", "notas_debito", ["status"])

    # 2) Gasto -> nota; remove as colunas de decisão (agora vivem na nota).
    op.add_column("expenses", sa.Column("nota_id", sa.Integer(), nullable=True))
    op.create_index("ix_expenses_nota_id", "expenses", ["nota_id"])
    op.create_foreign_key(
        "fk_expenses_nota_id", "expenses", "notas_debito", ["nota_id"], ["id"], ondelete="SET NULL"
    )
    op.drop_column("expenses", "approver_id")
    op.drop_column("expenses", "decision_comment")
    op.drop_column("expenses", "decided_at")

    # 3) Reduz o enum do gasto; estados de reembolso antigos viram 'confirmed'.
    op.execute("ALTER TYPE expense_status_enum RENAME TO expense_status_enum_old")
    sa.Enum(*_EXP_NEW, name="expense_status_enum").create(op.get_bind())
    op.execute(
        "ALTER TABLE expenses ALTER COLUMN status TYPE expense_status_enum "
        "USING (CASE status::text WHEN 'pending_review' THEN 'pending_review' "
        "ELSE 'confirmed' END)::expense_status_enum"
    )
    op.execute("DROP TYPE expense_status_enum_old")

    # 4) Dados fiscais.
    op.add_column("organizations", sa.Column("cnpj", sa.String(length=32), nullable=True))
    op.add_column("organizations", sa.Column("address", sa.String(length=512), nullable=True))
    op.add_column("organizations", sa.Column("cep", sa.String(length=16), nullable=True))
    op.add_column("users", sa.Column("cpf", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("bank_name", sa.String(length=128), nullable=True))
    op.add_column("users", sa.Column("bank_agency", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("bank_account", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("pix_key", sa.String(length=255), nullable=True))


def downgrade() -> None:
    for col in ("pix_key", "bank_account", "bank_agency", "bank_name", "cpf"):
        op.drop_column("users", col)
    for col in ("cep", "address", "cnpj"):
        op.drop_column("organizations", col)

    # Restaura o enum antigo do gasto ('confirmed' -> 'approved').
    op.execute("ALTER TYPE expense_status_enum RENAME TO expense_status_enum_new")
    sa.Enum(*_EXP_OLD, name="expense_status_enum").create(op.get_bind())
    op.execute(
        "ALTER TABLE expenses ALTER COLUMN status TYPE expense_status_enum "
        "USING (CASE status::text WHEN 'pending_review' THEN 'pending_review' "
        "ELSE 'approved' END)::expense_status_enum"
    )
    op.execute("DROP TYPE expense_status_enum_new")

    op.add_column("expenses", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("expenses", sa.Column("decision_comment", sa.String(length=1024), nullable=True))
    op.add_column("expenses", sa.Column("approver_id", sa.Integer(), nullable=True))
    op.drop_constraint("fk_expenses_nota_id", "expenses", type_="foreignkey")
    op.drop_index("ix_expenses_nota_id", table_name="expenses")
    op.drop_column("expenses", "nota_id")

    op.drop_table("notas_debito")
    sa.Enum(name="nota_status_enum").drop(op.get_bind())
