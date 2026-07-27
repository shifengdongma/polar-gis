import hashlib
import logging
import os
import re
import shutil
import socket
import tempfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import SessionLocal
from app.models import (
    Dataset,
    DatasetType,
    DatasetVersion,
    FileAsset,
    ImportJob,
    JobStatus,
    S57ImportBatch,
    S57ImportBatchFile,
    S57ImportBatchItem,
    VersionStatus,
)
from app.services.importer import ImportProcessor
from app.services.s57 import identify_s57_file
from app.services.storage import LocalStorage

code_pattern = re.compile(r"[^a-z0-9_-]+")
_missing_update_pattern = re.compile(r"\.(\d{3})")
logger = logging.getLogger("polar_gis.s57_batch")


def s57_error_details(error_code: str | None, error_message: str | None) -> dict:
    """Extract structured details from chain validation errors.

    Returns ``{"missingUpdates": [...]}`` when the error involves update-chain gaps.
    """
    if not error_code or not error_message:
        return {}
    if error_code not in ("S57_UPDATE_GAP", "S57_BASE_MISSING"):
        return {}
    matches = _missing_update_pattern.findall(error_message)
    if not matches:
        return {}
    missing = [int(m) for m in matches]
    return {"missingUpdates": sorted(set(missing))}



class BatchSourceUnavailableError(Exception):
    pass


class S57ChainValidationError(ValueError):
    def __init__(self, code: str, message: str, missing_updates: list[int]) -> None:
        super().__init__(message)
        self.code = code
        self.missing_updates = tuple(missing_updates)


def group_s57_files(paths: list[Path]) -> dict[str, dict[int, Path]]:
    groups, errors = scan_s57_files(paths)
    if errors:
        raise ValueError(errors[sorted(errors)[0]])
    return groups


def scan_s57_files(paths: list[Path]) -> tuple[dict[str, dict[int, Path]], dict[str, str]]:
    groups: dict[str, dict[int, Path]] = {}
    errors: dict[str, str] = {}
    for path in paths:
        suffix = path.suffix.lower()
        if len(suffix) != 4 or not suffix[1:].isdigit():
            continue
        identity = identify_s57_file(path)
        chain = groups.setdefault(identity.cell_name, {})
        if identity.update_number in chain:
            errors[identity.cell_name] = (
                f"{identity.cell_name} 存在重复更新号 {identity.update_number:03d}"
            )
            continue
        chain[identity.update_number] = path
    return groups, errors


def validate_s57_chain(cell_name: str, chain: dict[int, Path]) -> list[int]:
    max_update = max(chain)
    if 0 not in chain:
        full_expected = list(range(max_update + 1))
        missing = sorted(n for n in full_expected if n not in chain)
        formatted = ", ".join(f".{n:03d}" for n in missing)
        raise S57ChainValidationError(
            "S57_BASE_MISSING",
            f"{cell_name} 缺少 .000 基础单元，且更新链不连续，缺少 {formatted}"
            if missing != full_expected
            else f"{cell_name} 缺少 .000 基础单元",
            missing,
        )
    expected = list(range(max_update + 1))
    missing = [number for number in expected if number not in chain]
    if missing:
        formatted = ", ".join(f".{number:03d}" for number in missing)
        raise S57ChainValidationError(
            "S57_UPDATE_GAP",
            f"{cell_name} 更新链不连续，缺少 {formatted}",
            missing,
        )
    return expected


class S57BatchProcessor:
    def __init__(self, settings: Settings, session_factory=None) -> None:
        self.settings = settings
        self.storage = LocalStorage(settings)
        self.importer = ImportProcessor(settings)
        self._session_factory = session_factory or SessionLocal

    def process(self, db: Session, batch: S57ImportBatch) -> None:
        self.settings.temp_root.mkdir(parents=True, exist_ok=True)
        batch.status = JobStatus.RUNNING.value
        batch.stage = "scan"
        batch.started_at = batch.started_at or datetime.now(UTC)
        batch.heartbeat_at = datetime.now(UTC)
        db.commit()
        temp_dir = Path(
            tempfile.mkdtemp(prefix=f"s57-batch-{batch.id}-", dir=self.settings.temp_root)
        )
        try:
            paths = self._stage_sources(db, batch.id, temp_dir)
            groups, scan_errors = scan_s57_files(paths)
            if not groups:
                self._fail_batch(
                    db, batch, "S57_BATCH_EMPTY", "批次中没有可识别的 S-57 文件"
                )
                return
            batch.total_cells = len(groups)
            batch.stage = "import"
            db.commit()

            existing_items = {
                item.cell_name: item
                for item in db.scalars(
                    select(S57ImportBatchItem).where(
                        S57ImportBatchItem.batch_id == batch.id
                    )
                ).all()
            }

            cell_names = sorted(groups)
            for cell_name in cell_names:
                if cell_name not in existing_items:
                    item = S57ImportBatchItem(
                        batch_id=batch.id,
                        cell_name=cell_name,
                        update_count=max(groups[cell_name]),
                    )
                    db.add(item)
            db.commit()

            items_map = {
                item.cell_name: item
                for item in db.scalars(
                    select(S57ImportBatchItem).where(
                        S57ImportBatchItem.batch_id == batch.id
                    )
                ).all()
            }

            queued_cells = [
                (cell_name, groups[cell_name])
                for cell_name in cell_names
                if items_map.get(cell_name)
                and items_map[cell_name].status
                in (JobStatus.QUEUED.value,)
            ]

            if not queued_cells:
                self._finalize_batch(db, batch)
                return

            progress_lock = threading.Lock()
            workers = min(
                getattr(self.settings, "batch_parallel_workers", 8),
                max(1, os.cpu_count() or 4),
                len(queued_cells),
            )

            logger.info(
                "批量导入 %s: %d 单元, %d 待处理, %d 并行workers",
                batch.name,
                batch.total_cells,
                len(queued_cells),
                workers,
            )

            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_cell: dict = {}
                pending = list(queued_cells)
                stopped = False

                while pending or future_to_cell:
                    if not stopped:
                        batch_status = self._batch_status(db, batch.id)
                        if batch_status == JobStatus.CANCELLED.value:
                            for f in future_to_cell:
                                f.cancel()
                            break
                        if batch_status == JobStatus.PAUSED.value:
                            stopped = True

                    if not stopped:
                        while pending and len(future_to_cell) < workers:
                            cell_name, chain = pending.pop(0)
                            future = executor.submit(
                                self._process_cell_worker,
                                batch.id,
                                cell_name,
                                chain,
                                scan_errors.get(cell_name),
                            )
                            future_to_cell[future] = cell_name

                    done_futures = {
                        f
                        for f in future_to_cell
                        if f.done()
                    }

                    if not done_futures:
                        import time
                        time.sleep(0.5)
                        continue

                    for future in done_futures:
                        cell_name = future_to_cell.pop(future)
                        try:
                            future.result()
                        except Exception:
                            pass

                        with progress_lock:
                            progress_db = self._session_factory()
                            try:
                                progress_batch = progress_db.get(S57ImportBatch, batch.id)
                                if progress_batch is None:
                                    continue
                                progress_item = progress_db.scalar(
                                    select(S57ImportBatchItem).where(
                                        S57ImportBatchItem.batch_id == batch.id,
                                        S57ImportBatchItem.cell_name == cell_name,
                                    )
                                )
                                if progress_item is None:
                                    continue
                                progress_batch.processed_cells += 1
                                if progress_item.status == JobStatus.SUCCEEDED.value:
                                    progress_batch.succeeded_cells += 1
                                else:
                                    progress_batch.failed_cells += 1
                                progress_batch.progress = (
                                    int(progress_batch.processed_cells * 100 / progress_batch.total_cells)
                                    if progress_batch.total_cells
                                    else 0
                                )
                                progress_batch.heartbeat_at = datetime.now(UTC)
                                progress_db.commit()
                            finally:
                                progress_db.close()

                    if stopped and not future_to_cell:
                        break

            self._finalize_batch(db, batch)
        except BatchSourceUnavailableError as exc:
            self._fail_batch(
                db,
                batch,
                "S57_BATCH_SOURCE_UNAVAILABLE",
                str(exc),
            )
        except Exception as exc:
            self._fail_batch(db, batch, "S57_BATCH_FAILED", str(exc)[:2000])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _batch_status(self, db: Session, batch_id: UUID) -> str:
        batch = db.get(S57ImportBatch, batch_id)
        if batch is None:
            return JobStatus.FAILED.value
        return batch.status

    def _batch_is_active(self, db: Session, batch_id: UUID) -> bool:
        status = self._batch_status(db, batch_id)
        return status not in (
            JobStatus.CANCELLED.value,
            JobStatus.FAILED.value,
            JobStatus.PAUSED.value,
        )

    def _process_cell_worker(
        self,
        batch_id: UUID,
        cell_name: str,
        chain: dict[int, Path],
        scan_error: str | None,
    ) -> None:
        db = self._session_factory()
        try:
            batch = db.get(S57ImportBatch, batch_id)
            if batch is None:
                return
            if batch.status in (
                JobStatus.CANCELLED.value,
                JobStatus.PAUSED.value,
            ):
                logger.info(
                    "跳过单元 %s: 批次状态为 %s", cell_name, batch.status
                )
                return

            item = db.scalar(
                select(S57ImportBatchItem).where(
                    S57ImportBatchItem.batch_id == batch_id,
                    S57ImportBatchItem.cell_name == cell_name,
                )
            )
            if item is None:
                return
            if item.status not in (JobStatus.QUEUED.value,):
                return

            if scan_error:
                self._fail_item(
                    db, item, "S57_BATCH_DUPLICATE_FILE", scan_error
                )
                return

            self._process_cell(db, batch, item, chain)
        except Exception as exc:
            db.rollback()
            item = db.scalar(
                select(S57ImportBatchItem).where(
                    S57ImportBatchItem.batch_id == batch_id,
                    S57ImportBatchItem.cell_name == cell_name,
                )
            )
            if item is not None and item.status != JobStatus.SUCCEEDED.value:
                self._fail_item(
                    db,
                    item,
                    "S57_CELL_IMPORT_FAILED",
                    str(exc)[:2000],
                )
        finally:
            db.close()

    def _finalize_batch(self, db: Session, batch: S57ImportBatch) -> None:
        final_db = self._session_factory()
        try:
            final_batch = final_db.get(S57ImportBatch, batch.id)
            if final_batch is None:
                return
            if final_batch.status in (
                JobStatus.CANCELLED.value,
                JobStatus.PAUSED.value,
                JobStatus.FAILED.value,
            ):
                return
            final_batch.status = (
                JobStatus.SUCCEEDED.value
                if final_batch.failed_cells == 0
                else "partial_failed"
                if final_batch.succeeded_cells > 0
                else JobStatus.FAILED.value
            )
            final_batch.stage = "completed"
            final_batch.progress = 100
            final_batch.finished_at = datetime.now(UTC)
            final_db.commit()

            # basemap post-processing hook
            if final_batch.purpose == "basemap" and final_batch.status in (
                JobStatus.SUCCEEDED.value,
                "partial_failed",
            ):
                self._run_basemap_postprocess(final_db, final_batch)
        finally:
            final_db.close()

    def _run_basemap_postprocess(
        self, db: Session, batch: S57ImportBatch
    ) -> None:
        """Run GeoServer layer group + GWC + base map registration."""
        try:
            from app.services.s57_basemap import BasemapPostProcessor
            from app.services.geoserver import GeoServerClient

            geoserver = GeoServerClient(self.settings)
            post_proc = BasemapPostProcessor(self.settings)
            post_proc.post_process(db, batch, geoserver)
        except Exception:
            logger.exception(
                "Basemap post-process failed for batch %s", batch.id
            )
            # update metadata to reflect failure
            meta = dict(batch.metadata_json.get("basemap", {}))
            meta["postProcessStatus"] = "failed"
            meta["warnings"] = meta.get("warnings", [])
            meta["warnings"].append("后处理失败，请手动重试底图发布")
            batch.metadata_json = {**batch.metadata_json, "basemap": meta}
            db.commit()

    def _stage_sources(self, db: Session, batch_id: UUID, temp_dir: Path) -> list[Path]:
        records = db.scalars(
            select(S57ImportBatchFile).where(S57ImportBatchFile.batch_id == batch_id)
        ).all()
        staged: list[Path] = []
        for record_index, record in enumerate(records):
            source = self.storage.resolve(record.storage_key)
            if not source.is_file():
                raise BatchSourceUnavailableError(
                    "批次源文件不在当前 Worker 的共享存储中。"
                    "请通过与 Worker 同一部署环境的 API 重新上传后再导入。"
                )
            if source.suffix.lower() != ".zip":
                destination = temp_dir / f"source-{record_index}" / Path(record.original_name).name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                staged.append(destination)
                continue
            with zipfile.ZipFile(source) as archive:
                for member_index, member in enumerate(archive.infolist()):
                    pure_path = PurePosixPath(member.filename.replace("\\", "/"))
                    if member.is_dir() or pure_path.is_absolute() or ".." in pure_path.parts:
                        continue
                    name = Path(pure_path.name)
                    suffix = name.suffix.lower()
                    if len(suffix) != 4 or not suffix[1:].isdigit():
                        continue
                    destination = temp_dir / f"zip-{record_index}-{member_index}" / name.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source_file, destination.open("wb") as target:
                        shutil.copyfileobj(source_file, target)
                    staged.append(destination)
        return staged

    def _process_cell(
        self,
        db: Session,
        batch: S57ImportBatch,
        item: S57ImportBatchItem,
        chain: dict[int, Path],
    ) -> None:
        code = code_pattern.sub("_", f"s57_{item.cell_name.lower()}").strip("_")[:80]
        dataset = db.scalar(select(Dataset).where(Dataset.code == code))
        parent_id: UUID | None = None
        next_version_no = 1
        if dataset is None:
            try:
                updates = validate_s57_chain(item.cell_name, chain)
            except S57ChainValidationError as exc:
                self._fail_item(db, item, exc.code, str(exc))
                return
            except ValueError as exc:
                self._fail_item(db, item, "S57_UPDATE_GAP", str(exc))
                return
            dataset = Dataset(
                code=code,
                name=f"S-57 海图 {item.cell_name}",
                data_type=DatasetType.S57.value,
                description=f"由批次“{batch.name}”自动创建",
                created_by=batch.requested_by,
            )
            db.add(dataset)
            db.flush()
        else:
            item.dataset_id = dataset.id
            if dataset.data_type != DatasetType.S57.value:
                self._fail_item(
                    db,
                    item,
                    "DATASET_CODE_EXISTS",
                    f"数据集代码 {code} 已被非 S-57 数据集占用",
                )
                return
            current = (
                db.get(DatasetVersion, dataset.current_version_id)
                if dataset.current_version_id
                else None
            )
            latest_version_no = db.scalar(
                select(DatasetVersion.version_no)
                .where(DatasetVersion.dataset_id == dataset.id)
                .order_by(DatasetVersion.version_no.desc())
                .limit(1)
            )
            if current is None or current.status != VersionStatus.VALID.value:
                self._fail_item(
                    db,
                    item,
                    "S57_BATCH_EXISTING_VERSION_INVALID",
                    "现有数据集没有可自动追加的最新有效 S-57 版本",
                )
                return
            if db.scalar(
                select(DatasetVersion.id).where(
                    DatasetVersion.dataset_id == dataset.id,
                    DatasetVersion.status == VersionStatus.PROCESSING.value,
                )
            ):
                self._fail_item(
                    db,
                    item,
                    "S57_BATCH_EXISTING_VERSION_BUSY",
                    "现有数据集存在正在处理的版本，暂不能自动追加",
                )
                return
            current_cell = str(current.metadata_json.get("cellName", "")).upper()
            if current_cell and current_cell != item.cell_name:
                self._fail_item(
                    db,
                    item,
                    "S57_CELL_MISMATCH",
                    "现有数据集的海图单元与批次文件不匹配",
                )
                return
            try:
                current_update = int(
                    current.metadata_json.get("updateNumber", current.source_format)
                )
            except (TypeError, ValueError):
                self._fail_item(
                    db,
                    item,
                    "S57_BATCH_EXISTING_VERSION_INVALID",
                    "现有数据集缺少可识别的 S-57 更新号",
                )
                return
            updates = [number for number in sorted(chain) if number > current_update]
            if not updates:
                item.dataset_id = dataset.id
                item.current_update = current_update
                item.status = JobStatus.SUCCEEDED.value
                item.stage = "up_to_date"
                item.progress = 100
                item.finished_at = datetime.now(UTC)
                db.commit()
                return
            expected_updates = list(range(current_update + 1, updates[-1] + 1))
            missing = [number for number in expected_updates if number not in chain]
            if missing:
                formatted = ", ".join(f".{number:03d}" for number in missing)
                self._fail_item(
                    db,
                    item,
                    "S57_UPDATE_GAP",
                    f"{item.cell_name} 更新链不连续，缺少 {formatted}",
                )
                return
            if not self._restore_missing_history_sources(
                db, batch, dataset, current, item, chain
            ):
                return
            parent_id = current.id
            next_version_no = (latest_version_no or current.version_no) + 1

        item.dataset_id = dataset.id
        item.status = JobStatus.RUNNING.value
        item.stage = "append_updates" if parent_id else "import_base"
        db.commit()
        for index, update_number in enumerate(updates):
            source = chain[update_number]
            version = DatasetVersion(
                dataset_id=dataset.id,
                version_no=next_version_no + index,
                source_format=f"{update_number:03d}",
                status=VersionStatus.PROCESSING.value,
                content_hash=self._sha256(source),
                parent_version_id=parent_id,
                metadata_json={"cellName": item.cell_name, "updateNumber": update_number},
            )
            db.add(version)
            db.flush()
            storage_key = (
                f"s57-batches/{batch.id}/{dataset.id}/{version.id}/{item.cell_name}.{update_number:03d}"
            )
            destination = self.storage.resolve(storage_key)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            db.add(
                FileAsset(
                    dataset_version_id=version.id,
                    purpose="source",
                    original_name=f"{item.cell_name}.{update_number:03d}",
                    storage_key=storage_key,
                    size_bytes=destination.stat().st_size,
                    sha256=version.content_hash,
                    media_type="application/octet-stream",
                )
            )
            job = ImportJob(
                dataset_id=dataset.id,
                dataset_version_id=version.id,
                job_type="initial_import" if update_number == 0 else "s57_update",
                status=JobStatus.RUNNING.value,
                stage="queued",
                worker_id=f"batch:{socket.gethostname()}",
                attempt=1,
                requested_by=batch.requested_by,
            )
            db.add(job)
            db.commit()
            self.importer.process(db, job)
            db.refresh(job)
            if job.status != JobStatus.SUCCEEDED.value:
                self._fail_item(
                    db,
                    item,
                    job.error_code or "IMPORT_FAILED",
                    job.error_message or f"更新 .{update_number:03d} 导入失败",
                )
                return
            parent_id = version.id
            item.current_update = update_number
            item.progress = int((index + 1) * 100 / len(updates))
            item.stage = f"applied_{update_number:03d}"
            batch.heartbeat_at = datetime.now(UTC)
            db.commit()
        item.status = JobStatus.SUCCEEDED.value
        item.stage = "completed"
        item.progress = 100
        item.finished_at = datetime.now(UTC)
        db.commit()

    def _restore_missing_history_sources(
        self,
        db: Session,
        batch: S57ImportBatch,
        dataset: Dataset,
        current: DatasetVersion,
        item: S57ImportBatchItem,
        uploaded_chain: dict[int, Path],
    ) -> bool:
        versions: list[DatasetVersion] = []
        candidate: DatasetVersion | None = current
        seen_version_ids: set[UUID] = set()
        while candidate is not None:
            if candidate.id in seen_version_ids:
                self._fail_item(
                    db,
                    item,
                    "S57_VERSION_CHAIN_INVALID",
                    "现有 S-57 版本链存在循环",
                )
                return False
            seen_version_ids.add(candidate.id)
            versions.append(candidate)
            if candidate.parent_version_id is None:
                break
            candidate = db.get(DatasetVersion, candidate.parent_version_id)
            if candidate is None:
                self._fail_item(
                    db,
                    item,
                    "S57_VERSION_CHAIN_INVALID",
                    "现有 S-57 版本链缺少父版本",
                )
                return False
        for version in reversed(versions):
            try:
                update_number = int(
                    version.metadata_json.get("updateNumber", version.source_format)
                )
            except (TypeError, ValueError):
                self._fail_item(
                    db,
                    item,
                    "S57_BATCH_EXISTING_VERSION_INVALID",
                    "现有 S-57 版本缺少可识别的更新号",
                )
                return False
            asset = db.scalar(
                select(FileAsset).where(
                    FileAsset.dataset_version_id == version.id,
                    FileAsset.purpose == "source",
                )
            )
            if asset is not None and self.storage.resolve(asset.storage_key).exists():
                continue
            source = uploaded_chain.get(update_number)
            if source is None:
                self._fail_item(
                    db,
                    item,
                    "S57_HISTORICAL_SOURCE_MISSING",
                    f"现有版本 .{update_number:03d} 的源文件缺失，批次中也未提供该文件",
                )
                return False
            storage_key = (
                f"s57-batches/{batch.id}/{dataset.id}/{version.id}/"
                f"{item.cell_name}.{update_number:03d}"
            )
            destination = self.storage.resolve(storage_key)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            sha256 = self._sha256(source)
            if asset is None:
                db.add(
                    FileAsset(
                        dataset_version_id=version.id,
                        purpose="source",
                        original_name=f"{item.cell_name}.{update_number:03d}",
                        storage_key=storage_key,
                        size_bytes=destination.stat().st_size,
                        sha256=sha256,
                        media_type="application/octet-stream",
                    )
                )
            else:
                asset.storage_key = storage_key
                asset.original_name = f"{item.cell_name}.{update_number:03d}"
                asset.size_bytes = destination.stat().st_size
                asset.sha256 = sha256
                asset.media_type = "application/octet-stream"
        db.commit()
        return True

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _fail_item(
        db: Session, item: S57ImportBatchItem, code: str, message: str
    ) -> None:
        item.status = JobStatus.FAILED.value
        item.stage = "failed"
        item.error_code = code
        item.error_message = message
        item.finished_at = datetime.now(UTC)
        db.commit()

    @staticmethod
    def _fail_batch(
        db: Session, batch: S57ImportBatch, code: str, message: str
    ) -> None:
        batch_id = batch.id
        db.rollback()
        target = db.get(S57ImportBatch, batch_id)
        if target is None:
            return
        target.status = JobStatus.FAILED.value
        target.stage = "failed"
        target.failed_cells = max(target.failed_cells, 1)
        target.finished_at = datetime.now(UTC)
        if target.total_cells == 0:
            item = S57ImportBatchItem(
                batch_id=target.id,
                cell_name="BATCH",
                status=JobStatus.FAILED.value,
                stage="failed",
                error_code=code,
                error_message=message,
                finished_at=datetime.now(UTC),
            )
            db.add(item)
        db.commit()
