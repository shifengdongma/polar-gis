"""Scope S-57 batch file storage keys to a batch.

Server-directory basemap imports store absolute source paths
(``/data/s57-basemaps/C110408A.000``). The original global unique constraint
prevented a second basemap import from referencing the same source files after
a cancelled/failed run.
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_s57_batch_file_key_scope"
down_revision = "0006_navigation_run_title"
branch_labels = None
depends_on = None

_TABLE = "s57_import_batch_files"
_OLD_UNIQUE = "s57_import_batch_files_storage_key_key"
_NEW_UNIQUE = "uq_s57_import_batch_files_batch_storage"


def _unique_names(inspector: sa.Inspector) -> set[str]:
    return {
        str(item.get("name"))
        for item in inspector.get_unique_constraints(_TABLE)
        if item.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    names = _unique_names(inspector)
    if _OLD_UNIQUE in names:
        op.drop_constraint(_OLD_UNIQUE, _TABLE, type_="unique")
    names = _unique_names(sa.inspect(bind))
    if _NEW_UNIQUE not in names:
        op.create_unique_constraint(
            _NEW_UNIQUE, _TABLE, ["batch_id", "storage_key"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(_TABLE):
        return
    names = _unique_names(inspector)
    if _NEW_UNIQUE in names:
        op.drop_constraint(_NEW_UNIQUE, _TABLE, type_="unique")
    names = _unique_names(sa.inspect(bind))
    if _OLD_UNIQUE not in names:
        op.create_unique_constraint(_OLD_UNIQUE, _TABLE, ["storage_key"])
