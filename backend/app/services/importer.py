import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.models import (
    Dataset,
    DatasetType,
    DatasetVersion,
    FileAsset,
    ImportJob,
    JobStatus,
    Layer,
    LayerStatus,
    ProjectLayer,
    Style,
    VersionStatus,
)
from app.services.geoserver import GeoServerClient
from app.services.s57 import GdalInspector
from app.services.s57_styles import preset_for_object_class
from app.services.storage import LocalStorage

identifier_pattern = re.compile(r"[^a-z0-9_]+")


def safe_identifier(value: str, max_length: int = 50) -> str:
    normalized = identifier_pattern.sub("_", value.lower()).strip("_")[:max_length]
    return normalized or "layer"


class ImportProcessor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage = LocalStorage(settings)
        self.inspector = GdalInspector(settings)
        self.geoserver = GeoServerClient(settings)

    def process(self, db: Session, job: ImportJob) -> None:
        job.status = JobStatus.RUNNING.value
        job.stage = "inspect"
        job.progress = 5
        job.started_at = datetime.now(UTC)
        job.heartbeat_at = datetime.now(UTC)
        db.commit()
        staged_directory: Path | None = None
        try:
            version = db.get(DatasetVersion, job.dataset_version_id)
            dataset = db.get(Dataset, job.dataset_id)
            if not version or not dataset:
                raise AppError("IMPORT_SOURCE_MISSING", "导入任务缺少数据版本或数据集", 422)
            file_asset = db.scalar(
                select(FileAsset).where(
                    FileAsset.dataset_version_id == version.id,
                    FileAsset.purpose == "source",
                )
            )
            if file_asset is None:
                raise AppError("IMPORT_SOURCE_MISSING", "导入任务缺少源文件", 422)
            source_path = self.storage.resolve(file_asset.storage_key)
            if dataset.data_type == DatasetType.S57.value:
                staged_directory, source_path = self._stage_s57_chain(db, dataset, version)
                inspection = self.inspector.inspect(source_path)
                metadata = self.inspector.s57_metadata(source_path)
                metadata.update(version.metadata_json)
                version.metadata_json = metadata
            elif dataset.data_type == DatasetType.RASTER.value:
                inspection = self.inspector.inspect_raster(source_path)
                version.metadata_json = {
                    "driver": inspection.get("driverShortName", "GTiff"),
                    "size": inspection.get("size"),
                    "coordinateSystem": inspection.get("coordinateSystem"),
                }
            else:
                inspection = self.inspector.inspect(source_path)
                version.metadata_json = {
                    "driver": inspection.get("driverShortName"),
                    "layerCount": len(inspection.get("layers", [])),
                }
            job.stage = "import"
            job.progress = 25
            job.heartbeat_at = datetime.now(UTC)
            db.commit()
            if self._check_cancelled(db, job.id):
                return
            if dataset.data_type == DatasetType.RASTER.value:
                imported_layers = self._prepare_raster_layer(db, dataset, version, source_path)
            else:
                imported_layers = self._import_vector_layers(db, dataset, version, source_path, inspection)
            job.stage = "publish"
            job.progress = 75
            db.commit()
            if self._check_cancelled(db, job.id):
                return
            if dataset.data_type == DatasetType.RASTER.value:
                for layer in imported_layers:
                    self.geoserver.publish_geotiff(
                        str(source_path),
                        layer.geoserver_layer_name or layer.code,
                    )
                    layer.status = LayerStatus.AVAILABLE.value
            else:
                self.geoserver.publish_feature_types_batch([
                    {
                        "table_name": (layer.source_table or "").split(".")[-1],
                        "layer_name": layer.geoserver_layer_name or layer.code,
                        "title": layer.name,
                    }
                    for layer in imported_layers
                ])
                for layer in imported_layers:
                    if dataset.data_type == DatasetType.S57.value:
                        self._apply_s57_style(db, layer)
                    layer.status = LayerStatus.AVAILABLE.value
            self._switch_project_layer_versions(db, version, imported_layers)
            if version.parent_version_id:
                parent_version = db.get(DatasetVersion, version.parent_version_id)
                if parent_version:
                    parent_version.status = VersionStatus.RETIRED.value
            version.status = VersionStatus.VALID.value
            version.activated_at = datetime.now(UTC)
            dataset.current_version_id = version.id
            job.status = JobStatus.SUCCEEDED.value
            job.stage = "completed"
            job.progress = 100
            job.finished_at = datetime.now(UTC)
            db.commit()
        except AppError as exc:
            self._fail_job(db, job.id, exc.code, exc.message)
        except Exception as exc:
            self._fail_job(db, job.id, "IMPORT_FAILED", str(exc)[:2000])
        finally:
            if staged_directory:
                shutil.rmtree(staged_directory, ignore_errors=True)

    def _check_cancelled(self, db: Session, job_id) -> bool:
        job = db.get(ImportJob, job_id)
        return job is not None and job.status == JobStatus.CANCELLED.value

    def _fail_job(self, db: Session, job_id, code: str, message: str) -> None:
        db.rollback()
        job = db.get(ImportJob, job_id)
        if job is None:
            return
        version = db.get(DatasetVersion, job.dataset_version_id)
        if version:
            version.status = VersionStatus.FAILED.value
        job.status = JobStatus.FAILED.value
        job.stage = "failed"
        job.error_code = code
        job.error_message = message
        job.finished_at = datetime.now(UTC)
        db.commit()

    def _stage_s57_chain(
        self,
        db: Session,
        dataset: Dataset,
        version: DatasetVersion,
    ) -> tuple[Path, Path]:
        self.settings.temp_root.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix=f"s57-{dataset.id}-", dir=self.settings.temp_root))
        versions: list[DatasetVersion] = []
        current: DatasetVersion | None = version
        seen_version_ids: set = set()
        while current is not None:
            if current.id in seen_version_ids:
                raise AppError("S57_VERSION_CHAIN_INVALID", "S-57版本链存在循环", 422)
            seen_version_ids.add(current.id)
            versions.append(current)
            if current.parent_version_id is None:
                break
            current = db.get(DatasetVersion, current.parent_version_id)
            if current is None:
                raise AppError("S57_VERSION_CHAIN_INVALID", "S-57版本链缺少父版本", 422)
        versions.reverse()
        base_path: Path | None = None
        for item in versions:
            asset = db.scalar(
                select(FileAsset).where(
                    FileAsset.dataset_version_id == item.id,
                    FileAsset.purpose == "source",
                )
            )
            if asset is None:
                raise AppError("IMPORT_SOURCE_MISSING", "S-57更新链缺少源文件", 422)
            source = self.storage.resolve(asset.storage_key)
            destination = directory / asset.original_name
            shutil.copy2(source, destination)
            if destination.suffix == ".000":
                base_path = destination
        if base_path is None:
            raise AppError("S57_BASE_CELL_MISSING", "S-57更新链缺少.000基础单元", 422)
        return directory, base_path

    def _ogr_connection(self) -> str:
        parsed = urlparse(self.settings.database_url.replace("postgresql+psycopg", "postgresql"))
        values = {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 5432,
            "dbname": parsed.path.lstrip("/"),
            "user": parsed.username or "",
            "password": parsed.password or "",
        }
        return "PG:" + " ".join(f"{key}='{value}'" for key, value in values.items())

    def _prepare_raster_layer(
        self,
        db: Session,
        dataset: Dataset,
        version: DatasetVersion,
        source_path: Path,
    ) -> list[Layer]:
        code = safe_identifier(f"{dataset.code}_{version.version_no}_raster", 90)
        layer = Layer(
            dataset_version_id=version.id,
            code=code,
            name=dataset.name,
            geometry_type="Raster",
            source_table=None,
            source_crs=version.source_crs,
            status=LayerStatus.PROCESSING.value,
            geoserver_workspace=self.settings.geoserver_workspace,
            geoserver_layer_name=code,
            queryable=False,
            exportable=False,
            allowed_fields=[],
            metadata_json={"sourcePath": source_path.name, "sourceLayer": "raster"},
        )
        db.add(layer)
        db.flush()
        return [layer]

    def _import_vector_layers(
        self,
        db: Session,
        dataset: Dataset,
        version: DatasetVersion,
        source_path: Path,
        inspection: dict,
    ) -> list[Layer]:
        if shutil.which(self.settings.gdal_ogr2ogr_command) is None:
            raise AppError("GDAL_UNAVAILABLE", "未找到ogr2ogr，请安装并配置GDAL", 503)
        source_layers = inspection.get("layers", [])
        if not source_layers:
            raise AppError("IMPORT_NO_LAYERS", "上传数据不包含可导入图层", 422)

        short_id = str(dataset.id).replace("-", "")[:8]
        temp_schema = f"_imp_{short_id}_v{version.version_no}"
        conn_str = self._ogr_connection()

        try:
            db.execute(text(f"CREATE SCHEMA IF NOT EXISTS {temp_schema}"))
            db.commit()

            command = [
                self.settings.gdal_ogr2ogr_command,
                "-f",
                "PostgreSQL",
                conn_str,
                str(source_path),
                "-lco",
                f"SCHEMA={temp_schema}",
                "-lco",
                "GEOMETRY_NAME=geom",
                "-lco",
                "PRECISION=NO",
                "-nlt",
                "PROMOTE_TO_MULTI",
                "-overwrite",
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if result.returncode != 0:
                raise AppError(
                    "GDAL_IMPORT_FAILED",
                    "GDAL 批量导入失败",
                    422,
                    result.stderr[-2000:],
                )
        except Exception:
            db.rollback()
            db.execute(text(f"DROP SCHEMA IF EXISTS {temp_schema} CASCADE"))
            db.commit()
            raise

        imported = []
        try:
            for index, source_layer in enumerate(source_layers):
                source_name = str(source_layer.get("name") or f"layer_{index + 1}")
                code = safe_identifier(f"{dataset.code}_{version.version_no}_{source_name}", 90)
                table_name = safe_identifier(
                    f"ds_{short_id}_v{version.version_no}_{source_name}",
                    60,
                )
                escaped_source = source_name.replace('"', '""')
                db.execute(
                    text(
                        f'ALTER TABLE {temp_schema}."{escaped_source}" SET SCHEMA geo'
                    )
                )
                db.execute(
                    text(
                        f'ALTER TABLE geo."{escaped_source}" RENAME TO "{table_name}"'
                    )
                )
                geometry_fields = source_layer.get("geometryFields") or [{}]
                layer = Layer(
                    dataset_version_id=version.id,
                    code=code,
                    name=source_name,
                    geometry_type=str(geometry_fields[0].get("type", "Unknown")),
                    source_table=f"geo.{table_name}",
                    source_crs=version.source_crs,
                    status=LayerStatus.PROCESSING.value,
                    geoserver_workspace=self.settings.geoserver_workspace,
                    geoserver_layer_name=code,
                    allowed_fields=[
                        field.get("name")
                        for field in source_layer.get("fields", [])
                        if field.get("name")
                    ],
                    metadata_json={"sourceLayer": source_name},
                )
                db.add(layer)
                imported.append(layer)
            db.execute(text(f"DROP SCHEMA IF EXISTS {temp_schema} CASCADE"))
            db.flush()
            return imported
        except Exception:
            db.rollback()
            db.execute(text(f"DROP SCHEMA IF EXISTS {temp_schema} CASCADE"))
            db.commit()
            raise

    def _apply_s57_style(self, db: Session, layer: Layer) -> None:
        source_layer = str(layer.metadata_json.get("sourceLayer", ""))
        preset = preset_for_object_class(source_layer)
        if preset is None:
            layer.metadata_json = {**layer.metadata_json, "s57StyleStatus": "unmapped"}
            return
        style = db.scalar(select(Style).where(Style.code == preset.code))
        if style is None:
            style = Style(
                code=preset.code,
                name=preset.name,
                geoserver_style_name=preset.code,
                status="published",
            )
            db.add(style)
            db.flush()
        self.geoserver.publish_style(preset.code, preset.render_sld())
        self.geoserver.set_default_style(layer.geoserver_layer_name or layer.code, preset.code)
        layer.metadata_json = {
            **layer.metadata_json,
            "recommendedStyleCode": preset.code,
            "recommendedStyleId": str(style.id),
            "s57StyleStatus": "mapped",
        }

    def _switch_project_layer_versions(
        self,
        db: Session,
        version: DatasetVersion,
        new_layers: list[Layer],
    ) -> None:
        if version.parent_version_id is None:
            return
        previous_layers = db.scalars(
            select(Layer).where(Layer.dataset_version_id == version.parent_version_id)
        ).all()
        new_by_source = {
            layer.metadata_json.get("sourceLayer", "raster"): layer for layer in new_layers
        }
        for previous in previous_layers:
            replacement = new_by_source.get(previous.metadata_json.get("sourceLayer", "raster"))
            if replacement is None:
                continue
            links = db.scalars(select(ProjectLayer).where(ProjectLayer.layer_id == previous.id)).all()
            for link in links:
                link.layer_id = replacement.id
