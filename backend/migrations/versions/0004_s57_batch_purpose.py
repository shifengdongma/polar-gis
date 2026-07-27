"""Add purpose and metadata_json columns to s57_import_batches."""

from alembic import op
import sqlalchemy as sa

revision = "0004_s57_batch_purpose"
down_revision = "0003_project_code_active_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "s57_import_batches",
        sa.Column(
            "purpose",
            sa.String(32),
            nullable=False,
            server_default="standard",
        ),
    )
    op.add_column(
        "s57_import_batches",
        sa.Column(
            "metadata_json",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_index(
        "ix_s57_import_batches_purpose",
        "s57_import_batches",
        ["purpose"],
    )


def downgrade() -> None:
    op.drop_index("ix_s57_import_batches_purpose", table_name="s57_import_batches")
    op.drop_column("s57_import_batches", "metadata_json")
    op.drop_column("s57_import_batches", "purpose")
