"""Add S-57 batch import tracking."""

from alembic import op
import sqlalchemy as sa


revision = "0002_s57_import_batches"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("s57_import_batches"):
        return
    op.create_table(
        "s57_import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("total_cells", sa.Integer(), nullable=False),
        sa.Column("processed_cells", sa.Integer(), nullable=False),
        sa.Column("succeeded_cells", sa.Integer(), nullable=False),
        sa.Column("failed_cells", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("worker_id", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_s57_import_batches_status", "s57_import_batches", ["status"])
    op.create_table(
        "s57_import_batch_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("original_name", sa.String(500), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["s57_import_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_s57_import_batch_files_batch_id", "s57_import_batch_files", ["batch_id"])
    op.create_table(
        "s57_import_batch_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("cell_name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("update_count", sa.Integer(), nullable=False),
        sa.Column("current_update", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["s57_import_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "cell_name"),
    )
    op.create_index("ix_s57_import_batch_items_batch_id", "s57_import_batch_items", ["batch_id"])
    op.create_index("ix_s57_import_batch_items_status", "s57_import_batch_items", ["status"])


def downgrade() -> None:
    op.drop_table("s57_import_batch_items")
    op.drop_table("s57_import_batch_files")
    op.drop_table("s57_import_batches")
