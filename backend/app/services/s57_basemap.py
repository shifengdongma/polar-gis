"""S-57 global overview chart basemap import — preflight and post-process."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    BaseMap,
    Dataset,
    DatasetVersion,
    JobStatus,
    Layer,
    LayerStatus,
    S57ImportBatch,
    S57ImportBatchFile,
    S57ImportBatchItem,
)
from app.services.s57 import GdalInspector, identify_s57_file

logger = logging.getLogger("polar_gis.s57_basemap")

S57_FILENAME_RE = re.compile(r"^[A-Za-z0-9]{8}\.\d{3}$")
PROFILE_DIR = Path(__file__).resolve().parent.parent / "resources" / "s57_basemap_profiles"

# ── error codes ──────────────────────────────────────────────────────
ERR_PROFILE_NOT_FOUND = "BASEMAP_PROFILE_NOT_FOUND"
ERR_SOURCE_NOT_CONFIGURED = "BASEMAP_SOURCE_NOT_CONFIGURED"
ERR_SOURCE_OUTSIDE_ROOT = "BASEMAP_SOURCE_OUTSIDE_ALLOWED_ROOT"
ERR_MANIFEST_CHANGED = "BASEMAP_MANIFEST_CHANGED"
ERR_REQUIRED_FILE_MISSING = "BASEMAP_REQUIRED_FILE_MISSING"
ERR_INVALID_FILENAME = "BASEMAP_INVALID_FILENAME"
ERR_INVALID_S57 = "BASEMAP_INVALID_S57_FILE"
ERR_USAGE_BAND_MISMATCH = "BASEMAP_USAGE_BAND_MISMATCH"
ERR_UPDATE_GAP = "BASEMAP_UPDATE_GAP"
ERR_EDITION_CONFLICT = "BASEMAP_EDITION_CONFLICT"
ERR_IMPORT_ALREADY_RUNNING = "BASEMAP_IMPORT_ALREADY_RUNNING"
ERR_NO_LOADABLE_CELL = "BASEMAP_NO_LOADABLE_CELL"
ERR_COVERAGE_INCOMPLETE = "BASEMAP_COVERAGE_INCOMPLETE"
ERR_LAYER_GROUP_FAILED = "BASEMAP_LAYER_GROUP_FAILED"
ERR_GRIDSET_FAILED = "BASEMAP_GRIDSET_FAILED"
ERR_WMTS_REGISTRATION_FAILED = "BASEMAP_WMTS_REGISTRATION_FAILED"
ERR_POSTPROCESS_FAILED = "BASEMAP_POSTPROCESS_FAILED"

LAYER_GROUP_NAME = "polar_global_enc_overview"
STABLE_LAYER_ORDER: tuple[str, ...] = (
    "SEAARE", "DEPARE", "ICEARE", "LNDARE", "COALNE", "DEPCNT",
    "SOUNDG", "UNSARE", "CTNARE", "UWTROC", "WRECKS", "OBSTRN",
)


# ── dataclasses ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class BasemapProfile:
    code: str
    name: str
    usage_band: int
    load_profile: str
    expected_cells: Mapping[str, int]
    description: str = ""


@dataclass(frozen=True)
class BasemapPreflightCell:
    cell_name: str
    expected_max_update: int
    discovered_updates: tuple[int, ...]
    edition_number: str | None = None
    usage_band: int | None = None
    compilation_scale: int | None = None
    extent: tuple[float, float, float, float] | None = None
    database_current_update: int | None = None
    action: str = "create"
    errors: tuple[str, ...] = ()


@dataclass
class PreflightResult:
    profile_code: str = ""
    profile_name: str = ""
    manifest_hash: str = ""
    expected_cell_count: int = 0
    expected_file_count: int = 0
    discovered_cell_count: int = 0
    selected_file_count: int = 0
    ignored_file_count: int = 0
    create_cell_count: int = 0
    update_cell_count: int = 0
    skip_cell_count: int = 0
    blocked_cell_count: int = 0
    total_size_bytes: int = 0
    coverage_extent: list[float] = field(default_factory=lambda: [-180, -90, 180, 90])
    coverage_verified: bool = False
    coverage_message: str = "当前数据包覆盖范围已计算，但未验证全球无缝覆盖"
    can_start: bool = False
    cells: list[dict[str, Any]] = field(default_factory=list)
    ignored_files: list[str] = field(default_factory=list)


# ── helpers ──────────────────────────────────────────────────────────

def _load_profile_json(profile_code: str) -> dict[str, Any]:
    path = PROFILE_DIR / f"{profile_code}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Basemap profile not found: {profile_code}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_profile(profile_code: str) -> BasemapProfile:
    raw = _load_profile_json(profile_code)
    return BasemapProfile(
        code=raw["code"],
        name=raw["name"],
        usage_band=raw["usage_band"],
        load_profile=raw.get("load_profile", "core_chart"),
        expected_cells=raw["expected_cells"],
        description=raw.get("description", ""),
    )


def list_available_profiles() -> list[BasemapProfile]:
    profiles: list[BasemapProfile] = []
    if not PROFILE_DIR.is_dir():
        return profiles
    for p in sorted(PROFILE_DIR.glob("*.json")):
        try:
            profiles.append(load_profile(p.stem))
        except Exception:
            logger.warning("Failed to load profile %s", p, exc_info=True)
    return profiles


def _compute_file_hash(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _compute_manifest_hash(profile: BasemapProfile, files: dict[str, dict[int, Path]]) -> str:
    """Stable hash from profile code + sorted (filename, size, sha256)."""
    hasher = hashlib.sha256()
    hasher.update(profile.code.encode())
    for cell_name in sorted(files):
        hasher.update(cell_name.encode())
        for upd in sorted(files[cell_name]):
            path = files[cell_name][upd]
            hasher.update(f"{upd}".encode())
            hasher.update(f"{path.stat().st_size}".encode())
            hasher.update(_compute_file_hash(path).encode())
    return hasher.hexdigest()


def _validate_source_path(source_root: str, target: Path) -> Path:
    """Ensure *target* is under *source_root* and not a symlink escape."""
    root = Path(source_root).resolve()
    resolved = target.resolve()
    if not str(resolved).startswith(str(root)):
        raise ValueError(f"Path {target} escapes allowed root {root}")
    if resolved != target and not str(resolved).startswith(str(root)):
        raise ValueError(f"Symlink {target} escapes allowed root {root}")
    return resolved


# ── DSID extraction ──────────────────────────────────────────────────

def _extract_dsid_metadata(inspection: dict[str, Any]) -> dict[str, Any]:
    """Pull DSID / DSPM fields from ogrinfo JSON output."""
    dsid: dict[str, Any] = {}
    dspm: dict[str, Any] = {}
    for layer in inspection.get("layers", []):
        name = str(layer.get("layerName", "")).strip().upper()
        props = layer.get("properties", {}) or {}
        if name == "DSID":
            dsid = {k: v for k, v in props.items()}
        elif name == "DSPM":
            dspm = {k: v for k, v in props.items()}
    return {
        "dsnm": dsid.get("DSID_DSNM"),
        "intu": _safe_int(dsid.get("DSID_INTU")),
        "edtn": dsid.get("DSID_EDTN"),
        "updn": _safe_int(dsid.get("DSID_UPDN")),
        "uadt": dsid.get("DSID_UADT"),
        "cscl": _safe_int(dspm.get("DSPM_CSCL")),
    }


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ── preflight service ────────────────────────────────────────────────

class BasemapPreflightService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.inspector = GdalInspector(settings)

    # -- source scanning -------------------------------------------------

    def scan_server_directory(
        self, profile: BasemapProfile
    ) -> tuple[dict[str, dict[int, Path]], list[str], list[str]]:
        """Scan S57_BASEMAP_SOURCE_ROOT for profile files.

        Returns (grouped_files, ignored_s57, non_s57).
        Returns empty grouped dict if root does not exist.
        """
        root = Path(self.settings.s57_basemap_source_root)
        grouped: dict[str, dict[int, Path]] = {}
        ignored_s57: list[str] = []
        non_s57: list[str] = []

        if not root.is_dir():
            return grouped, ignored_s57, non_s57
        expected = {c: n for c, n in profile.expected_cells.items()}

        for fpath in sorted(root.rglob("*")):
            if not fpath.is_file():
                continue
            fname = fpath.name
            if not S57_FILENAME_RE.match(fname):
                non_s57.append(fname)
                continue
            try:
                identity = identify_s57_file(fpath)
            except Exception:
                non_s57.append(fname)
                continue

            cell = identity.cell_name
            upd = identity.update_number

            # always record for ignored tracking
            if cell not in expected:
                ignored_s57.append(fname)
                continue
            if upd > expected[cell]:
                ignored_s57.append(fname)
                continue

            grouped.setdefault(cell, {})[upd] = fpath

        return grouped, ignored_s57, non_s57

    def scan_upload_directory(
        self, profile: BasemapProfile, dir_path: Path
    ) -> tuple[dict[str, dict[int, Path]], list[str], list[str]]:
        """Scan an uploaded/extracted directory for profile files."""
        grouped: dict[str, dict[int, Path]] = {}
        ignored_s57: list[str] = []
        non_s57: list[str] = []
        expected = {c: n for c, n in profile.expected_cells.items()}

        for fpath in sorted(dir_path.rglob("*")):
            if not fpath.is_file():
                continue
            fname = fpath.name
            if not S57_FILENAME_RE.match(fname):
                non_s57.append(fname)
                continue
            try:
                identity = identify_s57_file(fpath)
            except Exception:
                non_s57.append(fname)
                continue

            cell = identity.cell_name
            upd = identity.update_number

            if cell not in expected:
                ignored_s57.append(fname)
                continue
            if upd > expected[cell]:
                ignored_s57.append(fname)
                continue

            grouped.setdefault(cell, {})[upd] = fpath

        return grouped, ignored_s57, non_s57

    # -- DSID validation -------------------------------------------------

    def extract_dsid(self, path: Path) -> dict[str, Any]:
        inspection = self.inspector.inspect(path)
        return _extract_dsid_metadata(inspection)

    # -- update chain validation -----------------------------------------

    @staticmethod
    def validate_update_chain(
        cell_name: str,
        chain: dict[int, Path],
        expected_max: int,
    ) -> list[str]:
        errors: list[str] = []
        if 0 not in chain:
            errors.append(f"缺少 .000 基础文件")
            return errors

        updates = sorted(chain)
        for i in range(expected_max + 1):
            if i not in chain:
                errors.append(f"缺少更新号 {i:03d}")
        # ensure no gaps
        prev = -1
        for u in updates:
            if u != prev + 1:
                errors.append(f"更新链不连续: {prev} → {u}")
            prev = u
        return errors

    # -- database status -------------------------------------------------

    @staticmethod
    def check_database_cell(
        db: Session, cell_name: str
    ) -> tuple[int | None, UUID | None]:
        """Return (current_update_number, dataset_id) from existing Dataset."""
        dataset = db.scalar(
            select(Dataset).where(Dataset.code == cell_name, Dataset.deleted_at.is_(None))
        )
        if dataset is None:
            return None, None
        if dataset.current_version_id is None:
            return None, dataset.id
        version = db.get(DatasetVersion, dataset.current_version_id)
        if version is None:
            return None, dataset.id
        return version.version_no, dataset.id

    # -- full preflight --------------------------------------------------

    def preflight(
        self,
        db: Session,
        profile_code: str,
        source_type: str = "server_directory",
        upload_dir: Path | None = None,
    ) -> PreflightResult:
        profile = load_profile(profile_code)

        # 1. scan source
        if source_type == "upload" and upload_dir is not None:
            grouped, ignored_s57, non_s57 = self.scan_upload_directory(profile, upload_dir)
        else:
            if not self.settings.s57_basemap_allow_local_source:
                raise RuntimeError("Server directory source is not enabled")
            grouped, ignored_s57, non_s57 = self.scan_server_directory(profile)

        # 2. compute manifest
        manifest_hash = _compute_manifest_hash(profile, grouped)

        # 3. preflight each expected cell
        cells: list[dict[str, Any]] = []
        create_cnt = update_cnt = skip_cnt = blocked_cnt = 0
        selected_file_count = 0
        total_size = 0

        for cell_name, expected_max in profile.expected_cells.items():
            chain = grouped.get(cell_name, {})
            selected_file_count += len(chain)
            for p in chain.values():
                total_size += p.stat().st_size

            errors: list[str] = []

            # check .000 presence
            base_path = chain.get(0)
            if base_path is None:
                errors.append("缺少 .000 基础文件")
                blocked_cnt += 1
                cells.append(_cell_dict(cell_name, expected_max, chain, action="blocked", errors=errors))
                continue

            # DSID validation
            try:
                meta = self.extract_dsid(base_path)
            except Exception as exc:
                errors.append(f"无法读取 DSID 元数据: {exc}")
                blocked_cnt += 1
                cells.append(_cell_dict(cell_name, expected_max, chain, action="blocked", errors=errors))
                continue

            intu = meta.get("intu")
            if intu is not None and intu != profile.usage_band:
                errors.append(
                    f"DSID_INTU={intu} 与 profile 要求的用途等级 {profile.usage_band} 不一致"
                )

            # update chain validation
            chain_errors = self.validate_update_chain(cell_name, chain, expected_max)
            errors.extend(chain_errors)

            # database status
            db_update, ds_id = self.check_database_cell(db, cell_name)

            if errors:
                action = "blocked"
                blocked_cnt += 1
            elif db_update is not None and db_update >= expected_max:
                action = "skip_current"
                skip_cnt += 1
            elif db_update is not None and db_update < expected_max:
                action = "append_updates"
                update_cnt += 1
            else:
                action = "create"
                create_cnt += 1

            cells.append(
                _cell_dict(
                    cell_name,
                    expected_max,
                    chain,
                    action=action,
                    errors=tuple(errors),
                    edition_number=str(meta.get("edtn") or ""),
                    usage_band=meta.get("intu"),
                    compilation_scale=meta.get("cscl"),
                    database_current_update=db_update,
                )
            )

        # 4. build result
        result = PreflightResult(
            profile_code=profile.code,
            profile_name=profile.name,
            manifest_hash=manifest_hash,
            expected_cell_count=len(profile.expected_cells),
            expected_file_count=sum(profile.expected_cells.values()) + len(profile.expected_cells),
            discovered_cell_count=len(grouped),
            selected_file_count=selected_file_count,
            ignored_file_count=len(ignored_s57) + len(non_s57),
            create_cell_count=create_cnt,
            update_cell_count=update_cnt,
            skip_cell_count=skip_cnt,
            blocked_cell_count=blocked_cnt,
            total_size_bytes=total_size,
            can_start=blocked_cnt == 0 and selected_file_count > 0,
            cells=cells,
            ignored_files=(ignored_s57 + non_s57)[:100],
        )
        return result


def _cell_dict(
    cell_name: str,
    expected_max: int,
    chain: dict[int, Path],
    *,
    action: str = "create",
    errors: tuple[str, ...] = (),
    edition_number: str = "",
    usage_band: int | None = None,
    compilation_scale: int | None = None,
    database_current_update: int | None = None,
) -> dict[str, Any]:
    return {
        "cellName": cell_name,
        "expectedMaxUpdate": expected_max,
        "discoveredUpdates": sorted(chain),
        "editionNumber": edition_number,
        "usageBand": usage_band,
        "compilationScale": compilation_scale,
        "databaseCurrentUpdate": database_current_update,
        "action": action,
        "errors": list(errors),
    }


# ── post-process service ─────────────────────────────────────────────

class BasemapPostProcessor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def post_process(
        self,
        db: Session,
        batch: S57ImportBatch,
        geoserver_client,
    ) -> None:
        """Run after a basemap batch completes — creates layer group, GWC, base maps."""
        from app.services.s57_layer_catalog import classify_s57_layer
        from app.services.s57_styles import preset_for_object_class

        meta = dict(batch.metadata_json.get("basemap", {})) if batch.metadata_json else {}
        meta["postProcessStatus"] = "running"
        meta["warnings"] = meta.get("warnings", [])
        batch.metadata_json = {**batch.metadata_json, "basemap": meta}
        db.commit()

        try:
            # 1. collect layer names from successful cells
            layer_info = self._collect_basemap_layers(db, batch)
            meta["collectedLayerCount"] = len(layer_info)
        except Exception as exc:
            meta["postProcessStatus"] = "failed"
            meta["warnings"].append(f"收集图层失败: {exc}")
            batch.metadata_json = {**batch.metadata_json, "basemap": meta}
            db.commit()
            return

        # 2. create/update GeoServer layer group
        try:
            self._publish_layer_group(geoserver_client, layer_info)
            meta["layerGroupStatus"] = "published"
            meta["layerGroupName"] = LAYER_GROUP_NAME
        except Exception as exc:
            meta["layerGroupStatus"] = "failed"
            meta["warnings"].append(f"Layer group 发布失败: {exc}")
            batch.metadata_json = {**batch.metadata_json, "basemap": meta}
            db.commit()
            return

        # 3. register base maps
        base_map_ids: list[str] = []
        try:
            bm_3857 = self._upsert_base_map(db, "EPSG:3857", "全球海图概览底图")
            base_map_ids.append(str(bm_3857.id))
            meta["wmts3857BaseMapId"] = str(bm_3857.id)
            meta["wmts3857Status"] = "registered"
        except Exception as exc:
            meta["wmts3857Status"] = "failed"
            meta["warnings"].append(f"EPSG:3857 底图登记失败: {exc}")

        try:
            bm_3413 = self._upsert_base_map(db, "EPSG:3413", "全球海图概览底图（北极）")
            base_map_ids.append(str(bm_3413.id))
            meta["wmts3413BaseMapId"] = str(bm_3413.id)
            meta["wmts3413Status"] = "registered"
        except Exception as exc:
            meta["wmts3413Status"] = "failed"
            meta["warnings"].append(f"EPSG:3413 底图登记失败: {exc}")

        meta["baseMapIds"] = base_map_ids
        meta["postProcessStatus"] = "completed" if meta.get("wmts3857Status") == "registered" else "partial"
        batch.metadata_json = {**batch.metadata_json, "basemap": meta}
        db.commit()

    # -- internal helpers -------------------------------------------------

    def _collect_basemap_layers(self, db: Session, batch: S57ImportBatch) -> list[dict[str, Any]]:
        """Collect renderable core_chart layers from successful batch items."""
        from app.services.s57_layer_catalog import classify_s57_layer
        from app.services.s57_styles import preset_for_object_class

        items = db.scalars(
            select(S57ImportBatchItem).where(
                S57ImportBatchItem.batch_id == batch.id,
                S57ImportBatchItem.status == JobStatus.SUCCEEDED.value,
            )
        ).all()

        layers: list[dict[str, Any]] = []
        for item in items:
            if not item.dataset_id:
                continue
            dataset = db.get(Dataset, item.dataset_id)
            if dataset is None or dataset.current_version_id is None:
                continue
            version = db.get(DatasetVersion, dataset.current_version_id)
            if version is None:
                continue

            db_layers = db.scalars(
                select(Layer).where(
                    Layer.dataset_version_id == version.id,
                    Layer.status == LayerStatus.AVAILABLE.value,
                    Layer.deleted_at.is_(None),
                )
            ).all()

            for lyr in db_layers:
                obj_class = (lyr.metadata_json or {}).get("objectClass", "")
                if not obj_class:
                    continue
                rule = classify_s57_layer(obj_class, lyr.geometry_type, preset_for_object_class(obj_class) is not None)
                if not rule.renderable or rule.load_profile not in ("core_chart",):
                    continue
                if preset_for_object_class(obj_class) is None:
                    continue
                layers.append({
                    "geoserver_layer_name": lyr.geoserver_layer_name,
                    "code": lyr.code,
                    "object_class": obj_class,
                    "compilation_scale": (lyr.metadata_json or {}).get("compilationScale", 0) or 0,
                })

        # stable sort
        order_map = {cls: i for i, cls in enumerate(STABLE_LAYER_ORDER)}
        layers.sort(key=lambda l: (
            order_map.get(l["object_class"], 99),
            l.get("compilation_scale", 0),
            l["code"],
        ))
        return layers

    def _publish_layer_group(self, geoserver_client, layer_info: list[dict[str, Any]]) -> None:
        layer_names = [li["geoserver_layer_name"] for li in layer_info if li["geoserver_layer_name"]]
        if not layer_names:
            raise RuntimeError("没有可发布的图层")
        geoserver_client.create_or_update_layer_group(LAYER_GROUP_NAME, layer_names)

    def _upsert_base_map(self, db: Session, crs: str, name: str) -> BaseMap:
        """Find or create a BaseMap record for the given CRS."""
        from app.core.config import get_settings
        settings = get_settings()

        existing = db.scalar(
            select(BaseMap).where(
                BaseMap.name == name,
                BaseMap.crs == crs,
                BaseMap.deleted_at.is_(None),
            )
        )
        public_url = settings.geoserver_public_url.rstrip("/")
        url_template = f"{public_url}/gwc/service/wmts?REQUEST=GetCapabilities"

        if existing is not None:
            existing.url_template = url_template
            existing.map_type = "WMTS"
            existing.is_enabled = True
            existing.is_offline = True
            db.commit()
            return existing

        bm = BaseMap(
            name=name,
            map_type="WMTS",
            url_template=url_template,
            crs=crs,
            attribution="数据来源：多国水文机构 S-57 ENC | 非认证航海系统，不可用于实际导航",
            is_offline=True,
            is_enabled=True,
        )
        db.add(bm)
        db.commit()
        return bm
