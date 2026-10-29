"""Add navigation planning runs and routes."""

import sqlalchemy as sa
from alembic import op

revision = "0005_navigation_planning"
down_revision = "0004_s57_batch_purpose"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("planning_runs"):
        return
    op.create_table(
        "planning_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("vessel_id", sa.String(80), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("environment_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("algorithm_version", sa.String(64), nullable=False),
        sa.Column("data_policy", sa.String(32), nullable=False),
        sa.Column("risk_model_version", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_summary_json", sa.JSON(), nullable=False),
        sa.Column("risk_grid_path", sa.String(500), nullable=True),
        sa.Column("worker_id", sa.String(120), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_planning_runs_project_id", "planning_runs", ["project_id"])
    op.create_index("ix_planning_runs_requested_by", "planning_runs", ["requested_by"])
    op.create_index("ix_planning_runs_status", "planning_runs", ["status"])
    op.create_index(
        "ix_planning_runs_status_queued_at", "planning_runs", ["status", "queued_at"]
    )
    op.create_index(
        "ix_planning_runs_project_created_at", "planning_runs", ["project_id", "created_at"]
    )
    op.create_table(
        "planning_routes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("route_index", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.String(64), nullable=False),
        sa.Column("is_recommended", sa.Boolean(), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("coordinates_json", sa.JSON(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("ice_risk", sa.Float(), nullable=True),
        sa.Column("depth_risk", sa.Float(), nullable=True),
        sa.Column("fog_risk", sa.Float(), nullable=True),
        sa.Column("wind_risk", sa.Float(), nullable=True),
        sa.Column("wave_risk", sa.Float(), nullable=True),
        sa.Column("energy_mwh", sa.Float(), nullable=False),
        sa.Column("time_hours", sa.Float(), nullable=False),
        sa.Column("distance_km", sa.Float(), nullable=False),
        sa.Column("quality", sa.String(16), nullable=False),
        sa.Column("algorithm_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["planning_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "route_index", name="uq_planning_route_index"),
    )
    op.create_index("ix_planning_routes_run_id", "planning_routes", ["run_id"])
    op.create_index("ix_planning_routes_route_id", "planning_routes", ["route_id"])


def downgrade() -> None:
    op.drop_index("ix_planning_routes_route_id", table_name="planning_routes")
    op.drop_index("ix_planning_routes_run_id", table_name="planning_routes")
    op.drop_table("planning_routes")
    op.drop_index("ix_planning_runs_project_created_at", table_name="planning_runs")
    op.drop_index("ix_planning_runs_status_queued_at", table_name="planning_runs")
    op.drop_index("ix_planning_runs_status", table_name="planning_runs")
    op.drop_index("ix_planning_runs_requested_by", table_name="planning_runs")
    op.drop_index("ix_planning_runs_project_id", table_name="planning_runs")
    op.drop_table("planning_runs")
