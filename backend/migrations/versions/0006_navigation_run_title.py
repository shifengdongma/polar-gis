"""Add editable title to navigation planning runs."""

import sqlalchemy as sa
from alembic import op

revision = "0006_navigation_run_title"
down_revision = "0005_navigation_planning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("planning_runs"):
        return
    columns = {column["name"] for column in inspector.get_columns("planning_runs")}
    if "title" not in columns:
        op.add_column(
            "planning_runs",
            sa.Column(
                "title",
                sa.String(120),
                nullable=False,
                server_default="智能规划",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("planning_runs"):
        return
    columns = {column["name"] for column in inspector.get_columns("planning_runs")}
    if "title" in columns:
        op.drop_column("planning_runs", "title")
