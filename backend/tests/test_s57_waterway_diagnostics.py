from types import SimpleNamespace
from uuid import uuid4

from app.models import Project, User
from app.services import s57_waterway_diagnostics as diagnostics
from app.services.s57_project_layers import ProjectS57LayerRef, ProjectS57Resolution
from app.services.s57_waterway_catalog import classify_waterway
from app.services.s57_waterways import WaterwayLayerRef, WaterwayResolution


def project_layer(
    *,
    object_class: str,
    source_cell: str,
    feature_count: int = 1,
    extent=(60.0, 70.0, 80.0, 78.0),
) -> ProjectS57LayerRef:
    return ProjectS57LayerRef(
        layer_id=uuid4(),
        layer_code=f"s57_{source_cell.lower()}_{object_class.lower()}",
        layer_name=object_class,
        dataset_id=uuid4(),
        dataset_code=f"s57_{source_cell.lower()}",
        dataset_name=f"S-57 海图 {source_cell}",
        version_no=1,
        source_cell=source_cell,
        object_class=object_class,
        source_table=f"geo.ds_{source_cell.lower()}_{object_class.lower()}",
        geometry_type="MultiLineString",
        fields=("objnam", "inform"),
        key_column="ogc_fid",
        key_type="int",
        geometry_column="geom",
        feature_count=feature_count,
        available=True,
        queryable=True,
        renderable=True,
        reason=None,
        updated_at=None,
        extent=extent,
    )


def waterway_layer(
    *,
    object_class: str = "FAIRWY",
    source_cell: str = "NO1",
    feature_count: int = 10,
) -> WaterwayLayerRef:
    return WaterwayLayerRef(
        layer_id=uuid4(),
        layer_code=f"s57_{source_cell.lower()}_{object_class.lower()}",
        layer_name=object_class,
        dataset_id=uuid4(),
        dataset_code=f"s57_{source_cell.lower()}",
        dataset_name=f"S-57 海图 {source_cell}",
        version_no=1,
        source_cell=source_cell,
        object_class=object_class,
        rule=classify_waterway(object_class),
        source_table=f"geo.ds_{source_cell.lower()}_{object_class.lower()}",
        geometry_type="MultiLineString",
        fields=("objnam", "inform"),
        key_column="ogc_fid",
        key_type="int",
        geometry_column="geom",
        feature_count=feature_count,
        available=True,
        queryable=True,
        renderable=True,
        reason=None,
        updated_at=None,
    )


def test_diagnostics_reports_region_gap_without_internal_sql(monkeypatch):
    layer = waterway_layer()
    project_layers = (
        project_layer(object_class="FAIRWY", source_cell="NO1"),
        project_layer(object_class="M_COVR", source_cell="NO1"),
    )

    monkeypatch.setattr(
        diagnostics,
        "resolve_waterway_layers",
        lambda _db, _project_id: WaterwayResolution(layers=(layer,), warnings=()),
    )
    monkeypatch.setattr(
        diagnostics,
        "resolve_project_s57_layers",
        lambda _db, _project_id: ProjectS57Resolution(
            layers=project_layers,
            candidate_layer_count=2,
            resolved_layer_count=2,
        ),
    )

    def coverage(_db, _layers, cell):
        if cell == "NO1":
            return (60.0, 70.0, 80.0, 78.0), "m_covr", True
        return None, "unknown", False

    monkeypatch.setattr(diagnostics, "_coverage_bbox_for_cell", coverage)

    result = diagnostics.build_waterway_diagnostics(
        SimpleNamespace(rollback=lambda: None), uuid4()
    )
    assert result["totals"]["linkedCellCount"] == 1
    assert result["totals"]["waterwayLayerCount"] == 1
    assert result["totals"]["catalogTruncated"] is False
    assert result["cells"][0]["sourceCell"] == "NO1"
    assert result["cells"][0]["coverageSource"] == "m_covr"
    assert result["cells"][0]["coverageVerified"] is True
    assert result["northeastPassage"]["hasGap"] is True
    missing_codes = {
        item["code"] for item in result["northeastPassage"]["missingRegions"]
    }
    assert "kara" not in missing_codes
    assert {"laptev", "east_siberian", "chukchi_bering"} <= missing_codes
    assert any("USNIC" in item["title"] for item in result["references"])
    assert result["checkedAt"] == "2026-11-16"
    # Internal identifiers must not leak through the public payload.
    rendered = str(result)
    assert "sourceTable" not in rendered
    assert "geo.ds_" not in rendered


def test_diagnostics_marks_depth_only_region_as_auxiliary(monkeypatch):
    project_layers = (
        project_layer(object_class="DEPARE", source_cell="RU1"),
    )
    depth_layer = waterway_layer(object_class="DEPARE", source_cell="RU1")
    monkeypatch.setattr(
        diagnostics,
        "resolve_waterway_layers",
        lambda _db, _project_id: WaterwayResolution(layers=(depth_layer,), warnings=()),
    )
    monkeypatch.setattr(
        diagnostics,
        "resolve_project_s57_layers",
        lambda _db, _project_id: ProjectS57Resolution(
            layers=project_layers,
            candidate_layer_count=1,
            resolved_layer_count=1,
        ),
    )
    monkeypatch.setattr(
        diagnostics,
        "_coverage_bbox_for_cell",
        lambda _db, _layers, _cell: ((70.0, 70.0, 90.0, 78.0), "layer_extent", False),
    )
    result = diagnostics.build_waterway_diagnostics(
        SimpleNamespace(rollback=lambda: None), uuid4()
    )
    kara = next(item for item in result["regions"] if item["code"] == "kara")
    assert kara["status"] == "only_basemap_or_auxiliary"
    assert result["northeastPassage"]["hasGap"] is True


def test_diagnostics_api_is_project_scoped(client, db_session, user_headers, monkeypatch):
    user = db_session.query(User).first()
    project = Project(
        code=f"diag-{uuid4().hex[:8]}",
        name="Diagnostics Project",
        status="published",
        created_by=user.id,
        updated_by=user.id,
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)

    from app.api import s57_waterways as api

    monkeypatch.setattr(
        api.diagnostics_service,
        "build_waterway_diagnostics",
        lambda _db, project_id: {
            "projectId": str(project_id),
            "generatedAt": "2026-11-16T00:00:00Z",
            "totals": {},
            "cells": [],
            "classes": [],
            "regions": [],
            "northeastPassage": {},
            "references": [],
            "notes": [],
            "warnings": [],
            "checkedAt": "2026-11-16",
        },
    )
    response = client.get(
        f"/api/v1/projects/{project.id}/s57-waterways/diagnostics",
        headers=user_headers,
    )
    assert response.status_code == 200
    assert response.json()["projectId"] == str(project.id)
