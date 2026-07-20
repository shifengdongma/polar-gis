"""Initial application schema."""

from alembic import op

from app.core.database import Base
from app import models


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        op.execute("CREATE SCHEMA IF NOT EXISTS geo")
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        table.drop(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        op.execute("DROP SCHEMA IF EXISTS geo CASCADE")

