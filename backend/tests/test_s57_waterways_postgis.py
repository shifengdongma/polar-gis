"""Optional real-PostGIS integration test for waterway SQL execution.

Skipped unless S57_WATERWAY_TEST_DATABASE_URL points at a PostGIS database.
Example:
  S57_WATERWAY_TEST_DATABASE_URL=postgresql+psycopg://polar_gis:...@localhost:5432/polar_gis
"""

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.s57_waterway_catalog import classify_waterway
from app.services.s57_waterways import (
    WaterwayLayerRef,
    build_waterway_search_sql,
)

URL = os.environ.get("S57_WATERWAY_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="PostGIS test database not configured")


def test_search_sql_executes_against_postgis():
    engine = create_engine(URL)
    with Session(engine) as db:
        db.execute(text("CREATE SCHEMA IF NOT EXISTS geo"))
        db.execute(text("DROP TABLE IF EXISTS geo.s57_waterway_test"))
        db.execute(
            text(
                "CREATE TABLE geo.s57_waterway_test ("
                "ogc_fid serial PRIMARY KEY, objnam text, nobjnm text, inform text, "
                "status text, catfaw integer, geom geometry(LineString,4326))"
            )
        )
        db.execute(
            text(
                "INSERT INTO geo.s57_waterway_test "
                "(objnam,nobjnm,inform,status,catfaw,geom) VALUES "
                "('Test Fairway',NULL,'note','1',1,ST_GeomFromText('LINESTRING(10 70,11 71)',4326)),"
                "(NULL,'京杭运河',NULL,'1',2,ST_GeomFromText('LINESTRING(120 30,121 31)',4326)),"
                "(NULL,NULL,NULL,NULL,NULL,ST_GeomFromText('LINESTRING(-20 40,-19 41)',4326))"
            )
        )
        db.commit()

        layer = WaterwayLayerRef(
            layer_id=uuid4(),
            layer_code="s57_test_1_fairwy",
            layer_name="FAIRWY",
            dataset_id=uuid4(),
            dataset_code="s57_test",
            dataset_name="S-57 海图 TEST",
            version_no=1,
            source_cell="TEST",
            object_class="FAIRWY",
            rule=classify_waterway("FAIRWY"),
            source_table="geo.s57_waterway_test",
            geometry_type="MultiLineString",
            fields=("objnam", "nobjnm", "inform", "status", "catfaw"),
            key_column="ogc_fid",
            key_type="int",
            geometry_column="geom",
            feature_count=3,
            available=True,
            queryable=True,
            renderable=True,
            reason=None,
            updated_at=None,
        )

        payload = SimpleNamespace(
            keyword=None,
            bbox=None,
            page=1,
            page_size=20,
            object_classes=["FAIRWY"],
            include_auxiliary=False,
        )
        count_sql, rows_sql, params = build_waterway_search_sql([layer], payload)
        total = db.scalar(text(count_sql), params)
        rows = db.execute(text(rows_sql), params).mappings().all()
        assert total == 3
        assert len(rows) == 3
        assert {row["name"] for row in rows} == {"Test Fairway", "京杭运河", None}

        payload.keyword = "运河"
        count_sql, rows_sql, params = build_waterway_search_sql([layer], payload)
        rows = db.execute(text(rows_sql), params).mappings().all()
        assert len(rows) == 1
        assert rows[0]["name"] == "京杭运河"

        payload.keyword = None
        payload.bbox = (119.0, 29.0, 122.0, 32.0)
        count_sql, rows_sql, params = build_waterway_search_sql([layer], payload)
        rows = db.execute(text(rows_sql), params).mappings().all()
        assert len(rows) == 1
        assert rows[0]["name"] == "京杭运河"
        db.execute(text("DROP TABLE geo.s57_waterway_test"))
        db.commit()
