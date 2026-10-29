"""Add purpose and metadata_json columns to s57_import_batches.

Idempotent because the initial migration builds from current ORM metadata on a
fresh database, which may already include these columns.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_s57_batch_purpose"
down_revision = "0003_project_code_active_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("s57_import_batches"):
        return
    columns = {column["name"] for column in inspector.get_columns("s57_import_batches")}
    if "purpose" not in columns:
        op.add_column(
            "s57_import_batches",
            sa.Column(
                "purpose",
                sa.String(32),
                nullable=False,
                server_default="standard",
            ),
        )
    if "metadata_json" not in columns:
        op.add_column(
            "s57_import_batches",
            sa.Column(
                "metadata_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )
    indexes = {index["name"] for index in inspector.get_indexes("s57_import_batches")}
    if "ix_s57_import_batches_purpose" not in indexes:
        op.create_index(
            "ix_s57_import_batches_purpose",
            "s57_import_batches",
            ["purpose"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("s57_import_batches"):
        return
    columns = {column["name"] for column in inspector.get_columns("s57_import_batches")}
    indexes = {index["name"] for index in inspector.get_indexes("s57_import_batches")}
    if "ix_s57_import_batches_purpose" in indexes:
        op.drop_index("ix_s57_import_batches_purpose", table_name="s57_import_batches")
    if "metadata_json" in columns:
        op.drop_column("s57_import_batches", "metadata_json")
    if "purpose" in columns:
        op.drop_column("s57_import_batches", "purpose")
