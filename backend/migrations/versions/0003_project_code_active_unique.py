"""Allow project codes to be reused after soft deletion."""

from alembic import op

revision = "0003_project_code_active_unique"
down_revision = "0002_s57_import_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_projects_code", table_name="projects", if_exists=True)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_code_active "
        "ON projects (code) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index("uq_projects_code_active", table_name="projects")
    op.create_index("ix_projects_code", "projects", ["code"], unique=True)
