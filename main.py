from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import tempfile
import textwrap
import threading
import time
import traceback
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

try:
    import numpy as np

    NUMPY_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - depends on environment
    np = None  # type: ignore[assignment]
    NUMPY_IMPORT_ERROR = exc

try:
    import cv2

    CV2_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - depends on environment
    cv2 = None  # type: ignore[assignment]
    CV2_IMPORT_ERROR = exc

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

    PIL_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - depends on environment
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]
    UnidentifiedImageError = OSError  # type: ignore[assignment]
    PIL_IMPORT_ERROR = exc


APP_TITLE = "人物画像ZIP前処理 GUI"
WINDOWS_NEWLINE = "\r\n"
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
DEFAULT_WINDOW_GEOMETRY = "1240x900"
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
LOG_FOLDER_NAME = "logs"
REPORT_FILE_NAME = "selection_report.txt"
CONTACT_SHEET_ALL = "contact_sheet_all.jpg"
CONTACT_SHEET_SELECTED = "contact_sheet_selected_candidate.jpg"
CONTACT_SHEET_REVIEW = "contact_sheet_review.jpg"
RESULT_ZIP_SUFFIX = "_result.zip"
CATEGORY_SELECTED = "selected_candidate"
CATEGORY_REVIEW = "review"
CATEGORY_EXCLUDE = "exclude"
CATEGORY_ORDER = [CATEGORY_SELECTED, CATEGORY_REVIEW, CATEGORY_EXCLUDE]
CATEGORY_LABELS = {
    CATEGORY_SELECTED: "selected_candidate",
    CATEGORY_REVIEW: "review",
    CATEGORY_EXCLUDE: "exclude",
}
CATEGORY_BORDER_COLORS = {
    CATEGORY_SELECTED: (28, 135, 55),
    CATEGORY_REVIEW: (214, 151, 13),
    CATEGORY_EXCLUDE: (190, 45, 45),
}
INVALID_WINDOWS_NAME_CHARS = set('<>:"/\\|?*')
FONT_CANDIDATES = [
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "meiryo.ttc",
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msgothic.ttc",
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "YuGothM.ttc",
]
SHORT_REASON_LABELS = {
    "frontal_face_clear": "正面1顔 / 鮮明",
    "face_small_for_selected": "顔小さめ",
    "slight_blur": "ややブレ",
    "face_near_edge": "顔位置が端寄り",
    "brightness_extreme": "明暗差大",
    "profile_or_angle_face": "横顔・角度あり",
    "no_face": "顔なし",
    "multiple_faces": "複数顔",
    "face_too_small": "顔が小さすぎ",
    "strong_blur": "強いブレ",
    "broken_image": "破損画像",
    "profile_face_too_small": "横顔候補だが小さい",
    "profile_face_blurry": "横顔候補だがブレ大",
}
REASON_LABELS = {
    **SHORT_REASON_LABELS,
    "copy_failed": "分類後コピー失敗",
}
STOP_MESSAGE = "停止要求を受け付けました。現在のZIP処理完了後に安全停止します。"
HEADLESS_OK_MESSAGE = "gui_ok"

if Image is not None:
    try:
        RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
    except AttributeError:  # pragma: no cover - Pillow compatibility fallback
        RESAMPLE_LANCZOS = Image.LANCZOS
else:  # pragma: no cover - depends on environment
    RESAMPLE_LANCZOS = None


@dataclass
class AppConfig:
    input_zip_folder: str = ""
    output_folder: str = ""
    temp_folder: str = ""
    done_folder: str = ""
    selected_min_face_ratio: float = 0.05
    review_min_face_ratio: float = 0.018
    blur_threshold: float = 90.0
    contact_sheet_columns: int = 5
    thumbnail_width: int = 220
    move_done_zip: bool = True
    delete_temp_folder: bool = True
    overwrite_output: bool = False
    copy_exclude_images: bool = False
    window_geometry: str = DEFAULT_WINDOW_GEOMETRY

    @classmethod
    def from_dict(cls, raw: object) -> "AppConfig":
        data = raw if isinstance(raw, dict) else {}
        return cls(
            input_zip_folder=_safe_string(data.get("InputZipFolder", "")),
            output_folder=_safe_string(data.get("OutputFolder", "")),
            temp_folder=_safe_string(data.get("TempFolder", "")),
            done_folder=_safe_string(data.get("DoneFolder", "")),
            selected_min_face_ratio=_clamp(_safe_float(data.get("SelectedMinFaceRatio", 0.05), 0.05), 0.0001, 1.0),
            review_min_face_ratio=_clamp(_safe_float(data.get("ReviewMinFaceRatio", 0.018), 0.018), 0.0001, 1.0),
            blur_threshold=max(1.0, _safe_float(data.get("BlurThreshold", 90.0), 90.0)),
            contact_sheet_columns=max(1, _safe_int(data.get("ContactSheetColumns", 5), 5)),
            thumbnail_width=max(120, _safe_int(data.get("ThumbnailWidth", 220), 220)),
            move_done_zip=_safe_bool(data.get("MoveDoneZip", True)),
            delete_temp_folder=_safe_bool(data.get("DeleteTempFolder", True)),
            overwrite_output=_safe_bool(data.get("OverwriteOutput", False)),
            copy_exclude_images=_safe_bool(data.get("CopyExcludeImages", False)),
            window_geometry=_safe_string(data.get("WindowGeometry", DEFAULT_WINDOW_GEOMETRY)) or DEFAULT_WINDOW_GEOMETRY,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "InputZipFolder": self.input_zip_folder,
            "OutputFolder": self.output_folder,
            "TempFolder": self.temp_folder,
            "DoneFolder": self.done_folder,
            "SelectedMinFaceRatio": self.selected_min_face_ratio,
            "ReviewMinFaceRatio": self.review_min_face_ratio,
            "BlurThreshold": self.blur_threshold,
            "ContactSheetColumns": self.contact_sheet_columns,
            "ThumbnailWidth": self.thumbnail_width,
            "MoveDoneZip": self.move_done_zip,
            "DeleteTempFolder": self.delete_temp_folder,
            "OverwriteOutput": self.overwrite_output,
            "CopyExcludeImages": self.copy_exclude_images,
            "WindowGeometry": self.window_geometry,
        }


@dataclass
class ImageRecord:
    relative_path: str
    category: str
    reason_codes: list[str]
    face_count: int
    face_ratio: float
    blur_value: float
    face_mode: str
    brightness: float
    source_path: Path
    copied_path: Path | None = None

    @property
    def reason_text(self) -> str:
        return join_reason_labels(self.reason_codes)

    @property
    def short_reason_text(self) -> str:
        if not self.reason_codes:
            return "-"
        short_codes = self.reason_codes[:2]
        return join_reason_labels(short_codes)


@dataclass
class ZipProcessResult:
    zip_path: Path
    zip_name: str
    result_dir: Path
    temp_dir: Path
    started_at: datetime
    finished_at: datetime | None = None
    total_images: int = 0
    selected_count: int = 0
    review_count: int = 0
    exclude_count: int = 0
    success: bool = False
    skipped: bool = False
    records: list[ImageRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class BatchRunSummary:
    started_at: datetime
    finished_at: datetime | None = None
    total_zip_count: int = 0
    processed_zip_count: int = 0
    success_zip_count: int = 0
    failed_zip_count: int = 0
    skipped_zip_count: int = 0
    stopped: bool = False
    log_file_path: Path | None = None


class RunLogger:
    def __init__(self, log_path: Path, ui_sender: callable) -> None:
        self.log_path = log_path
        self._ui_sender = ui_sender
        self._lock = threading.Lock()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def info(self, message: str) -> None:
        self._write("INFO", message)

    def warning(self, message: str) -> None:
        self._write("WARN", message)

    def error(self, message: str) -> None:
        self._write("ERROR", message)

    def _write(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}"
        with self._lock:
            with self.log_path.open("a", encoding="utf-8", newline="") as handle:
                handle.write(line + WINDOWS_NEWLINE)
        self._ui_sender({"kind": "log", "line": line})


class ZipBatchProcessor:
    def __init__(
        self,
        config: AppConfig,
        stop_event: threading.Event,
        ui_sender: callable,
        logger: RunLogger,
    ) -> None:
        self.config = config
        self.stop_event = stop_event
        self.ui_sender = ui_sender
        self.logger = logger
        self.frontal_cascade: Any | None = None
        self.profile_cascade: Any | None = None

    def run(self) -> BatchRunSummary:
        self._ensure_dependencies()
        self._load_cascades()
        input_dir = Path(self.config.input_zip_folder)
        output_dir = Path(self.config.output_folder)
        temp_root = Path(self.config.temp_folder)
        done_dir = Path(self.config.done_folder)
        output_dir.mkdir(parents=True, exist_ok=True)
        temp_root.mkdir(parents=True, exist_ok=True)
        if self.config.move_done_zip:
            done_dir.mkdir(parents=True, exist_ok=True)

        zip_files = sorted((path for path in input_dir.glob("*.zip") if path.is_file()), key=lambda path: path.name.lower())
        summary = BatchRunSummary(
            started_at=datetime.now(),
            total_zip_count=len(zip_files),
            log_file_path=self.logger.log_path,
        )
        self.ui_sender({"kind": "progress", "value": 0.0, "maximum": max(1.0, float(len(zip_files))), "text": f"0 / {len(zip_files)} ZIP"})

        if not zip_files:
            self.logger.warning("入力フォルダに ZIP がありません。処理を終了します。")
            summary.finished_at = datetime.now()
            return summary

        for zip_index, zip_path in enumerate(zip_files):
            if self.stop_event.is_set():
                summary.stopped = True
                self.logger.info("停止要求により次のZIP開始前で停止します。")
                break

            self.ui_sender({"kind": "current_zip", "name": zip_path.name})
            result = self._process_single_zip(zip_path, zip_index, len(zip_files))
            summary.processed_zip_count += 1
            if result.skipped:
                summary.skipped_zip_count += 1
            elif result.success:
                summary.success_zip_count += 1
            else:
                summary.failed_zip_count += 1
            self.ui_sender(
                {
                    "kind": "progress",
                    "value": float(zip_index + 1),
                    "maximum": max(1.0, float(len(zip_files))),
                    "text": f"{zip_index + 1} / {len(zip_files)} ZIP",
                }
            )

        summary.finished_at = datetime.now()
        return summary

    def _ensure_dependencies(self) -> None:
        if PIL_IMPORT_ERROR is not None:
            raise RuntimeError(f"Pillow の読み込みに失敗しました: {PIL_IMPORT_ERROR}")
        if NUMPY_IMPORT_ERROR is not None:
            raise RuntimeError(f"numpy の読み込みに失敗しました: {NUMPY_IMPORT_ERROR}")
        if CV2_IMPORT_ERROR is not None:
            raise RuntimeError(f"OpenCV の読み込みに失敗しました: {CV2_IMPORT_ERROR}")
        if Image is None or np is None or cv2 is None:
            raise RuntimeError("Pillow / numpy / OpenCV の初期化に失敗しました。")

    def _load_cascades(self) -> None:
        assert cv2 is not None
        frontal_path = ensure_local_cascade_copy(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
        profile_path = ensure_local_cascade_copy(Path(cv2.data.haarcascades) / "haarcascade_profileface.xml")

        self.frontal_cascade = cv2.CascadeClassifier(str(frontal_path))
        if self.frontal_cascade.empty():
            raise RuntimeError(f"顔検出カスケードの読み込みに失敗しました: {frontal_path}")

        if profile_path.exists():
            profile = cv2.CascadeClassifier(str(profile_path))
            self.profile_cascade = None if profile.empty() else profile
        else:
            self.profile_cascade = None

    def _process_single_zip(self, zip_path: Path, zip_index: int, total_zip_count: int) -> ZipProcessResult:
        output_dir = Path(self.config.output_folder)
        temp_root = Path(self.config.temp_folder)
        result_dir = output_dir / sanitize_path_part(zip_path.stem)

        if result_dir.exists():
            if not self.config.overwrite_output:
                self.logger.warning(f"{zip_path.name}: 出力先 {result_dir.name} が既にあるためスキップしました。")
                return ZipProcessResult(
                    zip_path=zip_path,
                    zip_name=zip_path.name,
                    result_dir=result_dir,
                    temp_dir=temp_root,
                    started_at=datetime.now(),
                    finished_at=datetime.now(),
                    skipped=True,
                    errors=["既存出力があるためスキップしました。"],
                )
            shutil.rmtree(result_dir, ignore_errors=True)

        result_dir.mkdir(parents=True, exist_ok=True)
        for category in CATEGORY_ORDER:
            (result_dir / category).mkdir(parents=True, exist_ok=True)

        temp_dir = Path(tempfile.mkdtemp(prefix=f"{sanitize_path_part(zip_path.stem)}_", dir=str(temp_root)))
        result = ZipProcessResult(
            zip_path=zip_path,
            zip_name=zip_path.name,
            result_dir=result_dir,
            temp_dir=temp_dir,
            started_at=datetime.now(),
        )

        self.logger.info(f"{zip_path.name}: 処理を開始しました。")
        try:
            self._extract_zip(zip_path, temp_dir)
            image_files = sorted(
                (
                    path
                    for path in temp_dir.rglob("*")
                    if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
                ),
                key=lambda path: str(path.relative_to(temp_dir)).lower(),
            )
            result.total_images = len(image_files)
            self.logger.info(f"{zip_path.name}: 画像 {len(image_files)} 枚を検出しました。")

            for image_index, image_path in enumerate(image_files, start=1):
                record = self._classify_image(temp_dir, image_path)
                self._copy_record_if_needed(result_dir, record, result.errors)
                result.records.append(record)
                if record.category == CATEGORY_SELECTED:
                    result.selected_count += 1
                elif record.category == CATEGORY_REVIEW:
                    result.review_count += 1
                else:
                    result.exclude_count += 1

                progress_value = float(zip_index) + (image_index / max(1, len(image_files)))
                self.ui_sender(
                    {
                        "kind": "progress",
                        "value": progress_value,
                        "maximum": max(1.0, float(total_zip_count)),
                        "text": f"{zip_index + 1} / {total_zip_count} ZIP ({image_index} / {max(1, len(image_files))} 画像)",
                    }
                )

            self._create_contact_sheet(result_dir / CONTACT_SHEET_ALL, result.records, "全画像 contact sheet")
            self._create_contact_sheet(
                result_dir / CONTACT_SHEET_SELECTED,
                [record for record in result.records if record.category == CATEGORY_SELECTED],
                "selected_candidate contact sheet",
            )
            self._create_contact_sheet(
                result_dir / CONTACT_SHEET_REVIEW,
                [record for record in result.records if record.category == CATEGORY_REVIEW],
                "review contact sheet",
            )
            result.success = True

            if self.config.move_done_zip:
                try:
                    moved_path = self._move_to_done(zip_path)
                    self.logger.info(f"{zip_path.name}: 処理成功のため done へ移動しました。{moved_path.name}")
                except Exception as exc:
                    error_message = f"{zip_path.name}: done への移動に失敗しました。入力フォルダに残します。{exc}"
                    result.errors.append(error_message)
                    self.logger.error(error_message)
            else:
                self.logger.info(f"{zip_path.name}: done 移動は無効設定のため移動していません。")
            self._write_selection_report(result)
            archive_path = self._create_result_zip(result_dir, zip_path.stem)
            self.logger.info(f"{zip_path.name}: 結果ZIPを作成しました。{archive_path.name}")
        except zipfile.BadZipFile as exc:
            error_message = f"{zip_path.name}: ZIP の展開に失敗しました。破損ZIPの可能性があります。{exc}"
            result.errors.append(error_message)
            self.logger.error(error_message)
            self._write_selection_report(result)
        except Exception as exc:  # pragma: no cover - defensive path
            error_message = f"{zip_path.name}: ZIP 処理中に例外が発生しました。{exc}"
            result.errors.append(error_message)
            result.errors.append(traceback.format_exc())
            self.logger.error(error_message)
            self.logger.error(traceback.format_exc().rstrip())
            self._write_selection_report(result)
        finally:
            if self.config.delete_temp_folder:
                shutil.rmtree(temp_dir, ignore_errors=True)
            result.finished_at = datetime.now()
            if not result.success:
                self.logger.warning(f"{zip_path.name}: 処理は失敗扱いで完了しました。次のZIPへ進みます。")
            else:
                self.logger.info(f"{zip_path.name}: 処理完了。selected={result.selected_count}, review={result.review_count}, exclude={result.exclude_count}")
        return result

    def _extract_zip(self, zip_path: Path, destination_dir: Path) -> None:
        destination_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as archive:
            for info in archive.infolist():
                relative_path = normalize_zip_member_path(info)
                if relative_path is None:
                    continue
                target_path = destination_dir / relative_path
                if info.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target_path.open("wb") as target:
                    shutil.copyfileobj(source, target)

    def _classify_image(self, temp_root: Path, image_path: Path) -> ImageRecord:
        relative_path = str(image_path.relative_to(temp_root))
        try:
            image_rgb = load_rgb_image(image_path)
        except (OSError, ValueError, UnidentifiedImageError) as exc:
            return ImageRecord(
                relative_path=relative_path,
                category=CATEGORY_EXCLUDE,
                reason_codes=["broken_image"],
                face_count=0,
                face_ratio=0.0,
                blur_value=0.0,
                face_mode="none",
                brightness=0.0,
                source_path=image_path,
            )

        gray = cv2.cvtColor(np.array(image_rgb), cv2.COLOR_RGB2GRAY)
        blur_value = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        frontal_faces, profile_faces = self._detect_faces(gray)

        if frontal_faces:
            primary_faces = frontal_faces
            face_mode = "frontal"
        elif profile_faces:
            primary_faces = profile_faces
            face_mode = "profile"
        else:
            primary_faces = []
            face_mode = "none"

        face_count = len(primary_faces)
        face_ratio = 0.0
        face_near_edge = False
        if primary_faces:
            largest_face = max(primary_faces, key=lambda rect: rect[2] * rect[3])
            face_ratio = (largest_face[2] * largest_face[3]) / float(gray.shape[0] * gray.shape[1])
            face_near_edge = is_face_near_edge(largest_face, gray.shape[1], gray.shape[0])

        if face_count == 0:
            category = CATEGORY_EXCLUDE
            reason_codes = ["no_face"]
        elif face_count > 1:
            category = CATEGORY_EXCLUDE
            reason_codes = ["multiple_faces"]
        elif face_mode == "profile":
            if face_ratio < self.config.review_min_face_ratio:
                category = CATEGORY_EXCLUDE
                reason_codes = ["profile_face_too_small"]
            elif blur_value < self.config.blur_threshold * 0.65:
                category = CATEGORY_EXCLUDE
                reason_codes = ["profile_face_blurry"]
            else:
                category = CATEGORY_REVIEW
                reason_codes = ["profile_or_angle_face"]
        else:
            if face_ratio < self.config.review_min_face_ratio:
                category = CATEGORY_EXCLUDE
                reason_codes = ["face_too_small"]
            elif blur_value < self.config.blur_threshold * 0.55:
                category = CATEGORY_EXCLUDE
                reason_codes = ["strong_blur"]
            else:
                weak_reasons: list[str] = []
                if face_ratio < self.config.selected_min_face_ratio:
                    weak_reasons.append("face_small_for_selected")
                if blur_value < self.config.blur_threshold:
                    weak_reasons.append("slight_blur")
                if face_near_edge:
                    weak_reasons.append("face_near_edge")
                if brightness < 50.0 or brightness > 225.0:
                    weak_reasons.append("brightness_extreme")

                if weak_reasons:
                    category = CATEGORY_REVIEW
                    reason_codes = weak_reasons
                else:
                    category = CATEGORY_SELECTED
                    reason_codes = ["frontal_face_clear"]

        return ImageRecord(
            relative_path=relative_path,
            category=category,
            reason_codes=reason_codes,
            face_count=face_count,
            face_ratio=face_ratio,
            blur_value=blur_value,
            face_mode=face_mode,
            brightness=brightness,
            source_path=image_path,
        )

    def _detect_faces(self, gray: Any) -> tuple[list[tuple[int, int, int, int]], list[tuple[int, int, int, int]]]:
        assert cv2 is not None
        assert self.frontal_cascade is not None
        equalized = cv2.equalizeHist(gray)
        min_face_size = max(24, min(gray.shape[0], gray.shape[1]) // 20)
        frontal_raw = self.frontal_cascade.detectMultiScale(
            equalized,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(min_face_size, min_face_size),
        )
        frontal_faces = dedupe_rectangles(rectangles_to_list(frontal_raw))

        profile_faces: list[tuple[int, int, int, int]] = []
        if self.profile_cascade is not None:
            profile_raw = self.profile_cascade.detectMultiScale(
                equalized,
                scaleFactor=1.1,
                minNeighbors=4,
                minSize=(min_face_size, min_face_size),
            )
            profile_faces.extend(rectangles_to_list(profile_raw))

            flipped = cv2.flip(equalized, 1)
            profile_flipped_raw = self.profile_cascade.detectMultiScale(
                flipped,
                scaleFactor=1.1,
                minNeighbors=4,
                minSize=(min_face_size, min_face_size),
            )
            for x, y, w, h in rectangles_to_list(profile_flipped_raw):
                converted_x = gray.shape[1] - x - w
                profile_faces.append((converted_x, y, w, h))
            profile_faces = dedupe_rectangles(profile_faces)

        return frontal_faces, profile_faces

    def _copy_record_if_needed(self, result_dir: Path, record: ImageRecord, error_messages: list[str]) -> None:
        if record.category == CATEGORY_EXCLUDE and not self.config.copy_exclude_images:
            return

        category_dir = result_dir / record.category
        relative_path = Path(record.relative_path)
        destination_path = category_dir / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(record.source_path, destination_path)
            record.copied_path = destination_path
        except Exception as exc:
            record.reason_codes.append("copy_failed")
            error_message = f"{record.relative_path}: 分類先へのコピーに失敗しました。{exc}"
            error_messages.append(error_message)
            self.logger.error(error_message)

    def _create_contact_sheet(self, output_path: Path, records: list[ImageRecord], title: str) -> None:
        if Image is None or ImageDraw is None or ImageFont is None:
            return

        columns = max(1, self.config.contact_sheet_columns)
        thumb_width = max(120, self.config.thumbnail_width)
        thumb_height = max(100, int(thumb_width * 0.75))
        text_height = 64
        padding = 16
        header_height = 54
        tile_width = thumb_width + padding * 2
        tile_height = thumb_height + text_height + padding * 2

        title_font = load_contact_font(20)
        body_font = load_contact_font(14)

        if not records:
            canvas = Image.new("RGB", (tile_width, header_height + tile_height), color=(245, 245, 245))
            draw = ImageDraw.Draw(canvas)
            draw.text((padding, 14), title, fill=(32, 32, 32), font=title_font)
            draw.text((padding, header_height + 20), "対象画像はありません。", fill=(80, 80, 80), font=body_font)
            save_contact_sheet(canvas, output_path)
            return

        rows = (len(records) + columns - 1) // columns
        canvas_width = columns * tile_width
        canvas_height = header_height + rows * tile_height
        canvas = Image.new("RGB", (canvas_width, canvas_height), color=(245, 245, 245))
        draw = ImageDraw.Draw(canvas)
        draw.text((padding, 14), title, fill=(32, 32, 32), font=title_font)

        for index, record in enumerate(records):
            row = index // columns
            column = index % columns
            tile_left = column * tile_width
            tile_top = header_height + row * tile_height
            image_left = tile_left + padding
            image_top = tile_top + padding
            tile_box = (tile_left + 6, tile_top + 6, tile_left + tile_width - 6, tile_top + tile_height - 6)
            draw.rounded_rectangle(tile_box, radius=8, outline=CATEGORY_BORDER_COLORS.get(record.category, (130, 130, 130)), width=3, fill=(255, 255, 255))

            thumbnail = make_thumbnail_image(record.source_path, thumb_width, thumb_height)
            canvas.paste(thumbnail, (image_left, image_top))

            caption_path = trim_middle(Path(record.relative_path).name, 28)
            caption_reason = trim_middle(record.short_reason_text, 28)
            caption_text = f"{caption_path}\n{caption_reason}"
            wrapped_lines: list[str] = []
            for caption_line in caption_text.splitlines():
                wrapped_lines.extend(textwrap.wrap(caption_line, width=max(8, thumb_width // 11)) or [""])
            draw.multiline_text(
                (image_left, image_top + thumb_height + 8),
                "\n".join(wrapped_lines[:4]),
                fill=(40, 40, 40),
                font=body_font,
                spacing=2,
            )

        save_contact_sheet(canvas, output_path)

    def _write_selection_report(self, result: ZipProcessResult) -> None:
        report_path = result.result_dir / REPORT_FILE_NAME
        started = result.started_at.strftime("%Y-%m-%d %H:%M:%S")
        finished = (result.finished_at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
        config_lines = [
            f"InputZipFolder: {self.config.input_zip_folder}",
            f"OutputFolder: {self.config.output_folder}",
            f"TempFolder: {self.config.temp_folder}",
            f"DoneFolder: {self.config.done_folder}",
            f"SelectedMinFaceRatio: {self.config.selected_min_face_ratio:.4f}",
            f"ReviewMinFaceRatio: {self.config.review_min_face_ratio:.4f}",
            f"BlurThreshold: {self.config.blur_threshold:.2f}",
            f"ContactSheetColumns: {self.config.contact_sheet_columns}",
            f"ThumbnailWidth: {self.config.thumbnail_width}",
            f"MoveDoneZip: {self.config.move_done_zip}",
            f"DeleteTempFolder: {self.config.delete_temp_folder}",
            f"OverwriteOutput: {self.config.overwrite_output}",
            f"CopyExcludeImages: {self.config.copy_exclude_images}",
        ]

        lines = [
            "人物画像ZIP前処理レポート",
            "注意: selected_candidate は core確定ではありません。review も人間確認対象です。本人判定は自動確定しません。",
            "",
            f"元ZIP名: {result.zip_name}",
            f"開始時刻: {started}",
            f"終了時刻: {finished}",
            f"処理成功: {'はい' if result.success else 'いいえ'}",
            f"総画像数: {result.total_images}",
            f"selected_candidate数: {result.selected_count}",
            f"review数: {result.review_count}",
            f"exclude数: {result.exclude_count}",
            "",
            "使用設定:",
            *config_lines,
            "",
            "エラー内容:",
        ]

        if result.errors:
            for error in result.errors:
                lines.append(f"- {error}")
        else:
            lines.append("- なし")

        lines.extend(
            [
                "",
                "各画像の分類結果:",
            ]
        )

        if result.records:
            for record in result.records:
                lines.extend(
                    [
                        f"画像: {record.relative_path}",
                        f"  分類: {record.category}",
                        f"  分類理由: {record.reason_text}",
                        f"  顔数: {record.face_count}",
                        f"  顔検出モード: {record.face_mode}",
                        f"  顔比率: {record.face_ratio:.4f}",
                        f"  ブレ値: {record.blur_value:.2f}",
                        f"  明るさ平均: {record.brightness:.2f}",
                        "",
                    ]
                )
        else:
            lines.append("画像が見つからなかったため、画像別の分類結果はありません。")

        with report_path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(WINDOWS_NEWLINE.join(lines) + WINDOWS_NEWLINE)

    def _create_result_zip(self, result_dir: Path, original_stem: str) -> Path:
        archive_path = result_dir / f"{sanitize_path_part(original_stem)}{RESULT_ZIP_SUFFIX}"
        if archive_path.exists():
            archive_path.unlink()

        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(result_dir.rglob("*"), key=lambda item: str(item).lower()):
                if path == archive_path or not path.is_file():
                    continue
                archive.write(path, arcname=str(path.relative_to(result_dir)))
        return archive_path

    def _move_to_done(self, zip_path: Path) -> Path:
        destination_dir = Path(self.config.done_folder)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination_path = destination_dir / zip_path.name
        if destination_path.exists():
            if self.config.overwrite_output:
                destination_path.unlink()
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                destination_path = destination_dir / f"{zip_path.stem}_{timestamp}{zip_path.suffix}"
        last_error: Exception | None = None
        for _attempt in range(5):
            try:
                shutil.move(str(zip_path), str(destination_path))
                return destination_path
            except Exception as exc:
                last_error = exc
                time.sleep(0.4)
        if last_error is not None:
            raise last_error
        raise RuntimeError("done への移動に失敗しました。")


class ZipPreprocessorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(1040, 780)

        self.ui_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self.current_log_path: Path | None = None

        self.input_zip_folder_var = tk.StringVar()
        self.output_folder_var = tk.StringVar()
        self.temp_folder_var = tk.StringVar()
        self.done_folder_var = tk.StringVar()
        self.selected_min_face_ratio_var = tk.StringVar()
        self.review_min_face_ratio_var = tk.StringVar()
        self.blur_threshold_var = tk.StringVar()
        self.contact_sheet_columns_var = tk.StringVar()
        self.thumbnail_width_var = tk.StringVar()
        self.move_done_zip_var = tk.BooleanVar(value=True)
        self.delete_temp_folder_var = tk.BooleanVar(value=True)
        self.overwrite_output_var = tk.BooleanVar(value=False)
        self.copy_exclude_images_var = tk.BooleanVar(value=False)
        self.current_zip_var = tk.StringVar(value="待機中")
        self.progress_text_var = tk.StringVar(value="0 / 0 ZIP")
        self.status_var = tk.StringVar(value="待機中")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_max_var = tk.DoubleVar(value=1.0)

        self._build_ui()
        self._load_config_into_ui(silent=True)
        self._report_dependency_status()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._process_ui_queue)

    def _build_ui(self) -> None:
        root_frame = ttk.Frame(self, padding=12)
        root_frame.pack(fill="both", expand=True)
        root_frame.columnconfigure(0, weight=1)
        root_frame.rowconfigure(2, weight=1)

        path_group = ttk.LabelFrame(root_frame, text="フォルダ設定", padding=12)
        path_group.grid(row=0, column=0, sticky="ew")
        path_group.columnconfigure(1, weight=1)

        self._add_path_row(path_group, 0, "入力ZIPフォルダ", self.input_zip_folder_var)
        self._add_path_row(path_group, 1, "出力フォルダ", self.output_folder_var)
        self._add_path_row(path_group, 2, "一時フォルダ", self.temp_folder_var)
        self._add_path_row(path_group, 3, "処理済みZIP移動先", self.done_folder_var)

        settings_group = ttk.LabelFrame(root_frame, text="判定設定", padding=12)
        settings_group.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        for column in range(4):
            settings_group.columnconfigure(column, weight=1 if column % 2 == 1 else 0)

        self._add_entry_row(settings_group, 0, 0, "selected用 最小顔比率", self.selected_min_face_ratio_var)
        self._add_entry_row(settings_group, 0, 2, "review用 最小顔比率", self.review_min_face_ratio_var)
        self._add_entry_row(settings_group, 1, 0, "ブレ閾値", self.blur_threshold_var)
        self._add_entry_row(settings_group, 1, 2, "contact sheet列数", self.contact_sheet_columns_var)
        self._add_entry_row(settings_group, 2, 0, "サムネイル幅", self.thumbnail_width_var)

        check_frame = ttk.Frame(settings_group)
        check_frame.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        check_frame.columnconfigure(0, weight=1)
        check_frame.columnconfigure(1, weight=1)
        ttk.Checkbutton(check_frame, text="処理済みZIPをdoneへ移動", variable=self.move_done_zip_var).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(check_frame, text="一時フォルダを処理後削除", variable=self.delete_temp_folder_var).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(check_frame, text="既存出力を上書き", variable=self.overwrite_output_var).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Checkbutton(check_frame, text="exclude画像もコピーする", variable=self.copy_exclude_images_var).grid(row=1, column=1, sticky="w", pady=(4, 0))

        action_group = ttk.LabelFrame(root_frame, text="実行", padding=12)
        action_group.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        action_group.columnconfigure(0, weight=1)
        action_group.rowconfigure(4, weight=1)

        button_frame = ttk.Frame(action_group)
        button_frame.grid(row=0, column=0, sticky="ew")
        for index in range(4):
            button_frame.columnconfigure(index, weight=1)

        self.start_button = ttk.Button(button_frame, text="処理開始", command=self.start_processing)
        self.start_button.grid(row=0, column=0, sticky="ew")
        self.stop_button = ttk.Button(button_frame, text="停止要求", command=self.request_stop, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.save_button = ttk.Button(button_frame, text="設定保存", command=self.save_config)
        self.save_button.grid(row=0, column=2, sticky="ew", padx=(8, 0))
        self.load_button = ttk.Button(button_frame, text="設定読込", command=self.load_config)
        self.load_button.grid(row=0, column=3, sticky="ew", padx=(8, 0))

        status_frame = ttk.Frame(action_group)
        status_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        status_frame.columnconfigure(1, weight=1)
        ttk.Label(status_frame, text="現在処理中ZIP").grid(row=0, column=0, sticky="w")
        ttk.Label(status_frame, textvariable=self.current_zip_var).grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(status_frame, text="状態").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(status_frame, textvariable=self.status_var).grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(6, 0))

        progress_frame = ttk.Frame(action_group)
        progress_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        progress_frame.columnconfigure(0, weight=1)
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=1.0)
        self.progress_bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(progress_frame, textvariable=self.progress_text_var).grid(row=1, column=0, sticky="w", pady=(4, 0))

        ttk.Label(action_group, text="ログ").grid(row=3, column=0, sticky="w", pady=(12, 4))
        self.log_text = scrolledtext.ScrolledText(action_group, height=22, wrap="word")
        self.log_text.grid(row=4, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

    def _add_path_row(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=(10, 10), pady=4)
        ttk.Button(parent, text="選択...", command=lambda var=variable: self._choose_directory(var)).grid(row=row, column=2, sticky="ew", pady=4)

    def _add_entry_row(self, parent: ttk.Frame, row: int, column: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable, width=20).grid(row=row, column=column + 1, sticky="ew", padx=(10, 18), pady=4)

    def _choose_directory(self, variable: tk.StringVar) -> None:
        initial_dir = variable.get().strip() or str(BASE_DIR)
        selected = filedialog.askdirectory(title="フォルダ選択", initialdir=initial_dir)
        if selected:
            variable.set(selected)

    def _report_dependency_status(self) -> None:
        if PIL_IMPORT_ERROR is not None:
            self.append_log(f"Pillow の読み込みに失敗しています: {PIL_IMPORT_ERROR}")
        if NUMPY_IMPORT_ERROR is not None:
            self.append_log(f"numpy の読み込みに失敗しています: {NUMPY_IMPORT_ERROR}")
        if CV2_IMPORT_ERROR is not None:
            self.append_log(f"OpenCV の読み込みに失敗しています: {CV2_IMPORT_ERROR}")

    def append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + WINDOWS_NEWLINE)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def save_config(self, silent: bool = False) -> bool:
        try:
            config = self._build_config_from_ui()
        except ValueError as exc:
            if not silent:
                messagebox.showerror(APP_TITLE, str(exc))
            return False

        try:
            CONFIG_PATH.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            if not silent:
                self.append_log(f"設定を保存しました: {CONFIG_PATH}")
                messagebox.showinfo(APP_TITLE, f"設定を保存しました。{CONFIG_PATH.name}")
            return True
        except OSError as exc:
            if not silent:
                messagebox.showerror(APP_TITLE, f"config.json の保存に失敗しました。{exc}")
            return False

    def load_config(self) -> None:
        self._load_config_into_ui(silent=False)

    def _load_config_into_ui(self, silent: bool) -> bool:
        if not CONFIG_PATH.exists():
            if not silent:
                messagebox.showwarning(APP_TITLE, "config.json が見つかりません。")
            defaults = AppConfig()
            self._apply_config_to_ui(defaults)
            return False

        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            config = AppConfig.from_dict(raw)
            self._apply_config_to_ui(config)
            geometry = config.window_geometry.strip()
            if geometry:
                self.geometry(geometry)
            if not silent:
                self.append_log(f"設定を読込しました: {CONFIG_PATH}")
                messagebox.showinfo(APP_TITLE, f"設定を読込しました。{CONFIG_PATH.name}")
            return True
        except Exception as exc:
            if not silent:
                messagebox.showerror(APP_TITLE, f"config.json の読込に失敗しました。{exc}")
            return False

    def _apply_config_to_ui(self, config: AppConfig) -> None:
        self.input_zip_folder_var.set(config.input_zip_folder)
        self.output_folder_var.set(config.output_folder)
        self.temp_folder_var.set(config.temp_folder)
        self.done_folder_var.set(config.done_folder)
        self.selected_min_face_ratio_var.set(f"{config.selected_min_face_ratio:.4f}")
        self.review_min_face_ratio_var.set(f"{config.review_min_face_ratio:.4f}")
        self.blur_threshold_var.set(f"{config.blur_threshold:.2f}")
        self.contact_sheet_columns_var.set(str(config.contact_sheet_columns))
        self.thumbnail_width_var.set(str(config.thumbnail_width))
        self.move_done_zip_var.set(config.move_done_zip)
        self.delete_temp_folder_var.set(config.delete_temp_folder)
        self.overwrite_output_var.set(config.overwrite_output)
        self.copy_exclude_images_var.set(config.copy_exclude_images)

    def _build_config_from_ui(self) -> AppConfig:
        input_zip_folder = self.input_zip_folder_var.get().strip()
        output_folder = self.output_folder_var.get().strip()
        temp_folder = self.temp_folder_var.get().strip()
        done_folder = self.done_folder_var.get().strip()

        if not input_zip_folder:
            raise ValueError("入力ZIPフォルダを指定してください。")
        if not output_folder:
            raise ValueError("出力フォルダを指定してください。")
        if not temp_folder:
            raise ValueError("一時フォルダを指定してください。")
        if self.move_done_zip_var.get() and not done_folder:
            raise ValueError("処理済みZIP移動先フォルダを指定してください。")

        input_path = Path(input_zip_folder)
        output_path = Path(output_folder)
        temp_path = Path(temp_folder)
        done_path = Path(done_folder) if done_folder else None

        if not input_path.exists() or not input_path.is_dir():
            raise ValueError("入力ZIPフォルダが存在しません。")
        if same_path(input_path, output_path):
            raise ValueError("入力ZIPフォルダと出力フォルダを同じパスにはできません。")
        if same_path(input_path, temp_path):
            raise ValueError("入力ZIPフォルダと一時フォルダは別にしてください。")
        if done_path is not None and same_path(input_path, done_path):
            raise ValueError("入力ZIPフォルダと done フォルダは別にしてください。")

        selected_min_face_ratio = _safe_float(self.selected_min_face_ratio_var.get(), -1.0)
        review_min_face_ratio = _safe_float(self.review_min_face_ratio_var.get(), -1.0)
        blur_threshold = _safe_float(self.blur_threshold_var.get(), -1.0)
        contact_sheet_columns = _safe_int(self.contact_sheet_columns_var.get(), -1)
        thumbnail_width = _safe_int(self.thumbnail_width_var.get(), -1)

        if not (0.0 < selected_min_face_ratio <= 1.0):
            raise ValueError("selected用 最小顔比率は 0 より大きく 1 以下で指定してください。")
        if not (0.0 < review_min_face_ratio <= 1.0):
            raise ValueError("review用 最小顔比率は 0 より大きく 1 以下で指定してください。")
        if selected_min_face_ratio < review_min_face_ratio:
            raise ValueError("selected用 最小顔比率は review用 以上にしてください。")
        if blur_threshold <= 0.0:
            raise ValueError("ブレ閾値は 0 より大きい値にしてください。")
        if contact_sheet_columns <= 0:
            raise ValueError("contact sheet列数は 1 以上にしてください。")
        if thumbnail_width < 120:
            raise ValueError("サムネイル幅は 120 以上にしてください。")

        geometry = self.geometry()
        return AppConfig(
            input_zip_folder=str(input_path),
            output_folder=str(output_path),
            temp_folder=str(temp_path),
            done_folder=str(done_path) if done_path is not None else "",
            selected_min_face_ratio=selected_min_face_ratio,
            review_min_face_ratio=review_min_face_ratio,
            blur_threshold=blur_threshold,
            contact_sheet_columns=contact_sheet_columns,
            thumbnail_width=thumbnail_width,
            move_done_zip=self.move_done_zip_var.get(),
            delete_temp_folder=self.delete_temp_folder_var.get(),
            overwrite_output=self.overwrite_output_var.get(),
            copy_exclude_images=self.copy_exclude_images_var.get(),
            window_geometry=geometry,
        )

    def start_processing(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning(APP_TITLE, "既に処理中です。")
            return
        try:
            config = self._build_config_from_ui()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        if PIL_IMPORT_ERROR is not None or NUMPY_IMPORT_ERROR is not None or CV2_IMPORT_ERROR is not None:
            dependency_errors = []
            if PIL_IMPORT_ERROR is not None:
                dependency_errors.append(f"Pillow: {PIL_IMPORT_ERROR}")
            if NUMPY_IMPORT_ERROR is not None:
                dependency_errors.append(f"numpy: {NUMPY_IMPORT_ERROR}")
            if CV2_IMPORT_ERROR is not None:
                dependency_errors.append(f"OpenCV: {CV2_IMPORT_ERROR}")
            messagebox.showerror(APP_TITLE, "依存関係が不足しています。" + WINDOWS_NEWLINE + WINDOWS_NEWLINE.join(dependency_errors))
            return

        self.save_config(silent=True)
        Path(config.output_folder).mkdir(parents=True, exist_ok=True)
        log_dir = Path(config.output_folder) / LOG_FOLDER_NAME
        log_name = f"zip_preprocess_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self.current_log_path = log_dir / log_name

        self.stop_event.clear()
        self.current_zip_var.set("開始準備中")
        self.status_var.set("処理中")
        self.progress_var.set(0.0)
        self.progress_bar.configure(maximum=1.0)
        self.progress_text_var.set("0 / 0 ZIP")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.save_button.configure(state="disabled")
        self.load_button.configure(state="disabled")
        self.append_log(f"処理を開始します。ログ: {self.current_log_path}")

        self.worker_thread = threading.Thread(target=self._run_processing_worker, args=(config,), daemon=True)
        self.worker_thread.start()

    def request_stop(self) -> None:
        if not self.worker_thread or not self.worker_thread.is_alive():
            return
        self.stop_event.set()
        self.status_var.set("停止要求済み")
        self.append_log(STOP_MESSAGE)
        self.stop_button.configure(state="disabled")

    def _run_processing_worker(self, config: AppConfig) -> None:
        assert self.current_log_path is not None
        logger = RunLogger(self.current_log_path, self._send_ui_message)
        logger.info("バッチ処理を開始しました。")
        summary: BatchRunSummary | None = None
        try:
            processor = ZipBatchProcessor(config=config, stop_event=self.stop_event, ui_sender=self._send_ui_message, logger=logger)
            summary = processor.run()
            logger.info(
                f"全体完了: processed={summary.processed_zip_count}, success={summary.success_zip_count}, failed={summary.failed_zip_count}, skipped={summary.skipped_zip_count}, stopped={summary.stopped}"
            )
            self._send_ui_message({"kind": "finish", "summary": summary})
        except Exception as exc:
            logger.error(f"全体処理で致命的な例外が発生しました。{exc}")
            logger.error(traceback.format_exc().rstrip())
            failed_summary = summary or BatchRunSummary(
                started_at=datetime.now(),
                finished_at=datetime.now(),
                total_zip_count=0,
                log_file_path=self.current_log_path,
            )
            self._send_ui_message({"kind": "finish", "summary": failed_summary, "fatal_error": str(exc)})

    def _send_ui_message(self, payload: dict[str, Any]) -> None:
        self.ui_queue.put(payload)

    def _process_ui_queue(self) -> None:
        try:
            while True:
                payload = self.ui_queue.get_nowait()
                kind = payload.get("kind")
                if kind == "log":
                    self.append_log(str(payload.get("line", "")))
                elif kind == "progress":
                    maximum = float(payload.get("maximum", 1.0))
                    value = float(payload.get("value", 0.0))
                    self.progress_bar.configure(maximum=max(1.0, maximum))
                    self.progress_var.set(value)
                    self.progress_text_var.set(str(payload.get("text", "")))
                elif kind == "current_zip":
                    self.current_zip_var.set(str(payload.get("name", "")))
                elif kind == "finish":
                    self._handle_finish(payload)
        except queue.Empty:
            pass
        finally:
            self.after(120, self._process_ui_queue)

    def _handle_finish(self, payload: dict[str, Any]) -> None:
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.save_button.configure(state="normal")
        self.load_button.configure(state="normal")

        summary = payload.get("summary")
        fatal_error = payload.get("fatal_error")
        if isinstance(summary, BatchRunSummary):
            if fatal_error:
                self.status_var.set("異常終了")
            elif summary.stopped:
                self.status_var.set("停止完了")
            else:
                self.status_var.set("完了")

            if fatal_error:
                messagebox.showerror(APP_TITLE, f"処理が致命的エラーで終了しました。{fatal_error}")
            else:
                message_lines = [
                    f"処理ZIP数: {summary.processed_zip_count} / {summary.total_zip_count}",
                    f"成功: {summary.success_zip_count}",
                    f"失敗: {summary.failed_zip_count}",
                    f"スキップ: {summary.skipped_zip_count}",
                ]
                if summary.stopped:
                    message_lines.append("停止要求により次のZIP開始前で停止しました。")
                if summary.log_file_path is not None:
                    message_lines.append(f"ログ: {summary.log_file_path}")
                messagebox.showinfo(APP_TITLE, WINDOWS_NEWLINE.join(message_lines))
        else:
            self.status_var.set("完了")

        self.current_zip_var.set("待機中")

    def _on_close(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning(APP_TITLE, "処理中です。停止要求で処理完了を待ってから閉じてください。")
            return
        self.save_config(silent=True)
        self.destroy()


def _safe_string(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _safe_int(value: object, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _safe_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(os.path.abspath(str(right)))


def sanitize_path_part(name: str) -> str:
    sanitized = "".join("_" if character in INVALID_WINDOWS_NAME_CHARS else character for character in name)
    sanitized = sanitized.strip().rstrip(".")
    return sanitized or "_"


def normalize_zip_member_path(info: zipfile.ZipInfo) -> Path | None:
    raw_name = info.filename
    if not (info.flag_bits & 0x800):
        try:
            raw_name = raw_name.encode("cp437").decode("cp932")
        except Exception:
            pass

    pure_path = PurePosixPath(raw_name)
    safe_parts: list[str] = []
    for part in pure_path.parts:
        if part in {"", ".", "/"}:
            continue
        if part == "..":
            continue
        drive, tail = os.path.splitdrive(part)
        if drive:
            part = tail
        part = sanitize_path_part(part)
        if part:
            safe_parts.append(part)

    if not safe_parts:
        return None
    return Path(*safe_parts)


def ensure_local_cascade_copy(source_path: Path) -> Path:
    if not source_path.exists():
        return source_path
    cache_dir = BASE_DIR / ".runtime_cache" / "cascades"
    cache_dir.mkdir(parents=True, exist_ok=True)
    target_path = cache_dir / source_path.name
    if not target_path.exists():
        target_path.write_bytes(source_path.read_bytes())
    return target_path


def load_rgb_image(image_path: Path) -> Any:
    assert Image is not None
    assert ImageOps is not None
    with Image.open(image_path) as image:
        image = ImageOps.exif_transpose(image)
        return image.convert("RGB")


def rectangles_to_list(rectangles: Any) -> list[tuple[int, int, int, int]]:
    if rectangles is None:
        return []
    return [tuple(int(value) for value in rect) for rect in rectangles]


def calculate_iou(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
    left_x1, left_y1, left_w, left_h = left
    right_x1, right_y1, right_w, right_h = right
    left_x2 = left_x1 + left_w
    left_y2 = left_y1 + left_h
    right_x2 = right_x1 + right_w
    right_y2 = right_y1 + right_h

    intersection_x1 = max(left_x1, right_x1)
    intersection_y1 = max(left_y1, right_y1)
    intersection_x2 = min(left_x2, right_x2)
    intersection_y2 = min(left_y2, right_y2)
    intersection_w = max(0, intersection_x2 - intersection_x1)
    intersection_h = max(0, intersection_y2 - intersection_y1)
    intersection_area = intersection_w * intersection_h
    if intersection_area <= 0:
        return 0.0
    left_area = left_w * left_h
    right_area = right_w * right_h
    union_area = left_area + right_area - intersection_area
    if union_area <= 0:
        return 0.0
    return intersection_area / union_area


def dedupe_rectangles(rectangles: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    unique: list[tuple[int, int, int, int]] = []
    for rect in rectangles:
        if not any(calculate_iou(rect, existing) >= 0.55 for existing in unique):
            unique.append(rect)
    return unique


def is_face_near_edge(face_rect: tuple[int, int, int, int], image_width: int, image_height: int) -> bool:
    x, y, width, height = face_rect
    margin_x = image_width * 0.06
    margin_y = image_height * 0.06
    return x < margin_x or y < margin_y or (x + width) > (image_width - margin_x) or (y + height) > (image_height - margin_y)


def join_reason_labels(reason_codes: list[str]) -> str:
    if not reason_codes:
        return "-"
    return " / ".join(REASON_LABELS.get(code, code) for code in reason_codes)


def load_contact_font(size: int) -> Any:
    assert ImageFont is not None
    for font_path in FONT_CANDIDATES:
        if font_path.exists():
            try:
                return ImageFont.truetype(str(font_path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def make_thumbnail_image(image_path: Path, thumb_width: int, thumb_height: int) -> Any:
    assert Image is not None
    assert ImageOps is not None
    placeholder = Image.new("RGB", (thumb_width, thumb_height), color=(236, 236, 236))
    if ImageDraw is not None and ImageFont is not None:
        draw = ImageDraw.Draw(placeholder)
        font = load_contact_font(14)
        draw.multiline_text((12, 14), "NO\nPREVIEW", fill=(120, 120, 120), font=font, spacing=2)

    try:
        image = load_rgb_image(image_path)
    except Exception:
        return placeholder

    image.thumbnail((thumb_width, thumb_height), RESAMPLE_LANCZOS)
    canvas = Image.new("RGB", (thumb_width, thumb_height), color=(236, 236, 236))
    offset_x = (thumb_width - image.width) // 2
    offset_y = (thumb_height - image.height) // 2
    canvas.paste(image, (offset_x, offset_y))
    return canvas


def save_contact_sheet(image: Any, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="JPEG", quality=92, subsampling=0)


def trim_middle(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    head = (max_length - 1) // 2
    tail = max_length - head - 1
    return f"{text[:head]}…{text[-tail:]}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--headless-smoke-test", action="store_true", help="GUI を生成してすぐ終了します。")
    return parser.parse_args(argv)


def run_headless_smoke_test() -> int:
    app = ZipPreprocessorApp()
    app.update_idletasks()
    app.destroy()
    print(HEADLESS_OK_MESSAGE)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.headless_smoke_test:
        return run_headless_smoke_test()

    app = ZipPreprocessorApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
