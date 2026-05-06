from __future__ import annotations

import json
import queue
import sys
import threading
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageDraw, ImageOps, ImageTk, UnidentifiedImageError

    PIL_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - depends on environment
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]
    ImageTk = None  # type: ignore[assignment]
    UnidentifiedImageError = OSError  # type: ignore[assignment]
    PIL_IMPORT_ERROR = exc

try:
    from rembg import new_session, remove

    REMBG_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - depends on environment
    new_session = None  # type: ignore[assignment]
    remove = None  # type: ignore[assignment]
    REMBG_IMPORT_ERROR = exc


APP_TITLE = "背景削除一括処理 GUI"
WINDOWS_NEWLINE = "\r\n"
SETTINGS_PATH = Path(__file__).with_name("background_remover_gui_settings.json")
RUN_LOG_NAME = "background_removal_log.txt"
PREVIEW_MAX_SIZE = (320, 320)
CHECKER_SIZE = 16
INVALID_FILE_NAME_CHARS = set('<>:"/\\|?*')
EXTENSION_ORDER = ["jpg", "jpeg", "png", "webp", "bmp"]
DEFAULT_EXTENSIONS = ["jpg", "jpeg", "png"]
MODEL_CHOICES = [
    "u2net_human_seg",
    "isnet-general-use",
    "u2net",
    "u2netp",
    "silueta",
    "birefnet-general",
]
OUTPUT_FORMATS = [
    ("transparent_png", "透過PNG"),
    ("white_png", "白背景PNG"),
    ("black_png", "黒背景PNG"),
    ("green_png", "グリーン背景PNG"),
    ("mask_only", "マスク画像のみ"),
]
OUTPUT_FORMAT_LABELS = {key: label for key, label in OUTPUT_FORMATS}
OUTPUT_FORMAT_KEYS = [key for key, _label in OUTPUT_FORMATS]
OUTPUT_COLOR_MAP = {
    "white_png": (255, 255, 255, 255),
    "black_png": (0, 0, 0, 255),
    "green_png": (0, 255, 0, 255),
}
PREVIEW_FILETYPES = [
    ("Image files", "*.jpg *.jpeg *.png *.webp *.bmp"),
    ("All files", "*.*"),
]
SUPPORTED_REMBG_PYTHON = "3.11 - 3.13"
DEFAULT_WINDOW_GEOMETRY = "1320x980"
SCORE_PREFIX_GLOB = "s[0-9][0-9][0-9][0-9]_"
ANALYSIS_MASK_MAX_SIDE = 128

if Image is not None:
    try:
        RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
    except AttributeError:  # pragma: no cover - Pillow compatibility fallback
        RESAMPLE_LANCZOS = Image.LANCZOS
else:  # pragma: no cover - depends on environment
    RESAMPLE_LANCZOS = None


@dataclass
class AppSettings:
    input_folder: str = ""
    output_folder: str = ""
    preview_image_path: str = ""
    target_extensions: list[str] = field(default_factory=lambda: list(DEFAULT_EXTENSIONS))
    recursive: bool = True
    preserve_structure: bool = True
    skip_existing: bool = True
    output_format: str = "transparent_png"
    filename_mode: str = "suffix"
    suffix: str = "_nobg"
    model_name: str = "u2net_human_seg"
    alpha_matting: bool = False
    alpha_foreground_threshold: int = 270
    alpha_background_threshold: int = 20
    alpha_erode_size: int = 11
    resize_enabled: bool = False
    resize_long_edge: int = 1600
    score_prefix_enabled: bool = False
    low_score_filter_enabled: bool = False
    low_score_threshold: int = 60
    window_geometry: str = DEFAULT_WINDOW_GEOMETRY

    @classmethod
    def from_dict(cls, raw: object) -> "AppSettings":
        data = raw if isinstance(raw, dict) else {}
        target_extensions = normalize_extensions(data.get("TargetExtensions"))
        return cls(
            input_folder=_safe_string(data.get("InputFolder", "")),
            output_folder=_safe_string(data.get("OutputFolder", "")),
            preview_image_path=_safe_string(data.get("PreviewImagePath", "")),
            target_extensions=target_extensions or list(DEFAULT_EXTENSIONS),
            recursive=_safe_bool(data.get("Recursive", True)),
            preserve_structure=_safe_bool(data.get("PreserveStructure", True)),
            skip_existing=_safe_bool(data.get("SkipExisting", True)),
            output_format=_safe_choice(data.get("OutputFormat", "transparent_png"), OUTPUT_FORMAT_KEYS, "transparent_png"),
            filename_mode=_safe_choice(data.get("FilenameMode", "suffix"), ["keep_name", "suffix"], "suffix"),
            suffix=_safe_string(data.get("Suffix", "_nobg")) or "_nobg",
            model_name=_safe_choice(data.get("ModelName", "u2net_human_seg"), MODEL_CHOICES, "u2net_human_seg"),
            alpha_matting=_safe_bool(data.get("AlphaMatting", False)),
            alpha_foreground_threshold=_safe_int(data.get("AlphaForegroundThreshold", 270), 270),
            alpha_background_threshold=_safe_int(data.get("AlphaBackgroundThreshold", 20), 20),
            alpha_erode_size=_safe_int(data.get("AlphaErodeSize", 11), 11),
            resize_enabled=_safe_bool(data.get("ResizeEnabled", False)),
            resize_long_edge=max(1, _safe_int(data.get("ResizeLongEdge", 1600), 1600)),
            score_prefix_enabled=_safe_bool(data.get("ScorePrefixEnabled", False)),
            low_score_filter_enabled=_safe_bool(data.get("LowScoreFilterEnabled", False)),
            low_score_threshold=_clamp(_safe_int(data.get("LowScoreThreshold", 60), 60), 0, 1000),
            window_geometry=_safe_string(data.get("WindowGeometry", DEFAULT_WINDOW_GEOMETRY)) or DEFAULT_WINDOW_GEOMETRY,
        )

    def to_dict(self) -> dict[str, object]:
        raw = asdict(self)
        return {
            "InputFolder": raw["input_folder"],
            "OutputFolder": raw["output_folder"],
            "PreviewImagePath": raw["preview_image_path"],
            "TargetExtensions": raw["target_extensions"],
            "Recursive": raw["recursive"],
            "PreserveStructure": raw["preserve_structure"],
            "SkipExisting": raw["skip_existing"],
            "OutputFormat": raw["output_format"],
            "FilenameMode": raw["filename_mode"],
            "Suffix": raw["suffix"],
            "ModelName": raw["model_name"],
            "AlphaMatting": raw["alpha_matting"],
            "AlphaForegroundThreshold": raw["alpha_foreground_threshold"],
            "AlphaBackgroundThreshold": raw["alpha_background_threshold"],
            "AlphaErodeSize": raw["alpha_erode_size"],
            "ResizeEnabled": raw["resize_enabled"],
            "ResizeLongEdge": raw["resize_long_edge"],
            "ScorePrefixEnabled": raw["score_prefix_enabled"],
            "LowScoreFilterEnabled": raw["low_score_filter_enabled"],
            "LowScoreThreshold": raw["low_score_threshold"],
            "WindowGeometry": raw["window_geometry"],
        }


@dataclass(frozen=True)
class FileTask:
    source_path: Path
    output_path: Path
    relative_path: str


@dataclass
class BatchSummary:
    started_at: datetime
    total_files: int
    success_count: int = 0
    skipped_count: int = 0
    low_score_skip_count: int = 0
    error_count: int = 0
    stopped: bool = False
    finished_at: datetime | None = None
    error_items: list[str] = field(default_factory=list)
    log_file_path: Path | None = None
    fatal_error: str = ""
    log_write_error: str = ""

    @property
    def processed_count(self) -> int:
        return self.success_count + self.skipped_count + self.error_count


@dataclass(frozen=True)
class SubjectScore:
    score: int
    alpha_mean_ratio: float
    coverage_ratio: float
    solid_ratio: float
    largest_component_ratio: float
    largest_component_share: float


@dataclass
class ImageProcessResult:
    rgba_image: Any
    output_image: Any
    subject_score: SubjectScore


def _safe_string(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _safe_choice(value: object, allowed: list[str], default: str) -> str:
    text = _safe_string(value)
    return text if text in allowed else default


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def normalize_extensions(value: object) -> list[str]:
    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for extension in EXTENSION_ORDER:
        for item in value:
            text = _safe_string(item).lower().lstrip(".")
            if text == extension and text not in seen:
                normalized.append(text)
                seen.add(text)
                break
    return normalized


def load_settings() -> AppSettings:
    if not SETTINGS_PATH.exists():
        return AppSettings()

    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return AppSettings()

    return AppSettings.from_dict(raw)


def save_settings(settings: AppSettings) -> None:
    SETTINGS_PATH.write_text(
        json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )


def get_dependency_messages() -> list[str]:
    messages: list[str] = []
    if sys.version_info >= (3, 14):
        messages.append(
            f"現在の Python は {sys.version.split()[0]} です。rembg 公式要件は {SUPPORTED_REMBG_PYTHON} です。"
        )
    if PIL_IMPORT_ERROR is not None:
        messages.append(f"Pillow の読み込みに失敗しました: {PIL_IMPORT_ERROR}")
    if REMBG_IMPORT_ERROR is not None:
        messages.append(f"rembg の読み込みに失敗しました: {REMBG_IMPORT_ERROR}")
    return messages


def ensure_processing_dependencies() -> None:
    dependency_messages = get_dependency_messages()
    if dependency_messages:
        install_hint = (
            '推奨: Python 3.11-3.13 環境で `pip install "rembg[cpu]" pillow` を実行してください。'
        )
        raise RuntimeError(WINDOWS_NEWLINE.join(dependency_messages + [install_hint]))


def is_same_or_child_path(candidate: Path, parent: Path) -> bool:
    candidate_resolved = candidate.resolve()
    parent_resolved = parent.resolve()
    try:
        candidate_resolved.relative_to(parent_resolved)
        return True
    except ValueError:
        return False


def build_filetypes_description(extensions: list[str]) -> str:
    patterns = [f"*.{extension}" for extension in extensions]
    return " ".join(patterns) if patterns else "*.jpg *.jpeg *.png"


def collect_source_files(input_folder: Path, extensions: list[str], recursive: bool) -> list[Path]:
    allowed = {f".{extension}" for extension in extensions}
    iterator = input_folder.rglob("*") if recursive else input_folder.glob("*")
    files = [
        path
        for path in iterator
        if path.is_file() and path.suffix.lower() in allowed
    ]
    return sorted(files, key=lambda item: str(item).lower())


def validate_settings(settings: AppSettings, *, require_output_folder: bool = True) -> None:
    if not settings.input_folder:
        raise ValueError("入力フォルダを指定してください。")
    input_folder = Path(settings.input_folder)
    if not input_folder.is_dir():
        raise ValueError("入力フォルダが存在しません。")

    if require_output_folder:
        if not settings.output_folder:
            raise ValueError("出力フォルダを指定してください。")
        output_folder = Path(settings.output_folder)
        if input_folder.resolve() == output_folder.resolve():
            raise ValueError("入力フォルダと出力フォルダに同じパスは指定できません。")
        if is_same_or_child_path(output_folder, input_folder):
            raise ValueError("出力フォルダを入力フォルダ配下には置けません。別フォルダを指定してください。")

    if not settings.target_extensions:
        raise ValueError("対象拡張子を1つ以上選択してください。")

    validate_runtime_options(settings)


def validate_runtime_options(settings: AppSettings) -> None:
    if settings.filename_mode == "suffix":
        if not settings.suffix:
            raise ValueError("suffix 付与を選んだ場合は suffix を入力してください。")
        if any(char in INVALID_FILE_NAME_CHARS for char in settings.suffix):
            raise ValueError('suffix に使用できない文字が含まれています。 <>:"/\\|?* は使えません。')

    if settings.alpha_matting:
        if settings.alpha_foreground_threshold <= settings.alpha_background_threshold:
            raise ValueError("Alpha matting の foreground threshold は background threshold より大きくしてください。")
        if settings.alpha_erode_size < 0:
            raise ValueError("Alpha matting の erode size は 0 以上にしてください。")

    if settings.resize_enabled and settings.resize_long_edge <= 0:
        raise ValueError("長辺リサイズを有効にした場合は 1 以上の値を指定してください。")

    settings.low_score_threshold = _clamp(settings.low_score_threshold, 0, 1000)


def validate_preview_settings(settings: AppSettings) -> None:
    if settings.alpha_matting:
        if settings.alpha_foreground_threshold <= settings.alpha_background_threshold:
            raise ValueError("Alpha matting の foreground threshold は background threshold より大きくしてください。")
        if settings.alpha_erode_size < 0:
            raise ValueError("Alpha matting の erode size は 0 以上にしてください。")

    if settings.resize_enabled and settings.resize_long_edge <= 0:
        raise ValueError("長辺リサイズを有効にした場合は 1 以上の値を指定してください。")

    settings.low_score_threshold = _clamp(settings.low_score_threshold, 0, 1000)


def build_output_stem(source_path: Path, settings: AppSettings) -> str:
    stem = source_path.stem
    if settings.filename_mode == "suffix":
        return f"{stem}{settings.suffix}"
    return stem


def path_key(path: Path) -> str:
    return str(path).lower()


def reserve_output_path(preferred_path: Path, used_targets: set[str]) -> Path:
    candidate = preferred_path
    suffix_index = 1
    while path_key(candidate) in used_targets:
        candidate = preferred_path.with_name(f"{preferred_path.stem}_{suffix_index:03d}{preferred_path.suffix}")
        suffix_index += 1
    used_targets.add(path_key(candidate))
    return candidate


def apply_score_prefix(output_path: Path, score: int) -> Path:
    return output_path.with_name(f"s{score:04d}_{output_path.name}")


def find_existing_output_candidates(output_path: Path, include_score_prefixed: bool) -> list[Path]:
    candidates: list[Path] = []
    if output_path.exists():
        candidates.append(output_path)
    if include_score_prefixed and output_path.parent.exists():
        pattern = f"{SCORE_PREFIX_GLOB}{output_path.name}"
        candidates.extend(sorted(output_path.parent.glob(pattern), key=lambda item: str(item).lower()))
    return candidates


def build_file_tasks(settings: AppSettings) -> list[FileTask]:
    validate_settings(settings)
    input_folder = Path(settings.input_folder)
    output_folder = Path(settings.output_folder)
    source_files = collect_source_files(input_folder, settings.target_extensions, settings.recursive)

    tasks: list[FileTask] = []
    used_targets: set[str] = set()
    for source_path in source_files:
        relative_path = source_path.relative_to(input_folder)
        output_stem = build_output_stem(source_path, settings)
        if settings.preserve_structure:
            preferred_path = output_folder / relative_path.parent / f"{output_stem}.png"
        else:
            preferred_path = output_folder / f"{output_stem}.png"
        final_output_path = reserve_output_path(preferred_path, used_targets)
        tasks.append(
            FileTask(
                source_path=source_path,
                output_path=final_output_path,
                relative_path=str(relative_path),
            )
        )
    return tasks


def format_exception_message(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def open_image_for_processing(path: Path) -> Any:
    if Image is None or ImageOps is None:
        raise RuntimeError("Pillow が利用できません。")

    with Image.open(path) as source_image:
        image = ImageOps.exif_transpose(source_image)
        image.load()
        return image.copy()


def resize_long_edge_if_needed(image: Any, enabled: bool, long_edge: int) -> Any:
    if not enabled or long_edge <= 0:
        return image
    width, height = image.size
    current_long_edge = max(width, height)
    if current_long_edge <= long_edge:
        return image

    scale = long_edge / current_long_edge
    resized = image.resize(
        (
            max(1, int(round(width * scale))),
            max(1, int(round(height * scale))),
        ),
        RESAMPLE_LANCZOS,
    )
    return resized


def ensure_pil_image(result: object) -> Any:
    if Image is None:
        raise RuntimeError("Pillow が利用できません。")

    if hasattr(Image, "Image") and isinstance(result, Image.Image):
        return result.copy()
    if isinstance(result, (bytes, bytearray)):
        with Image.open(BytesIO(result)) as image:
            image.load()
            return image.copy()
    raise TypeError(f"rembg の戻り値を画像として扱えませんでした: {type(result).__name__}")


def shrink_mask_for_analysis(alpha_image: Any) -> Any:
    width, height = alpha_image.size
    long_edge = max(width, height)
    if long_edge <= ANALYSIS_MASK_MAX_SIDE:
        return alpha_image

    scale = ANALYSIS_MASK_MAX_SIDE / long_edge
    return alpha_image.resize(
        (
            max(1, int(round(width * scale))),
            max(1, int(round(height * scale))),
        ),
        RESAMPLE_LANCZOS,
    )


def compute_largest_component_ratio(binary_mask: list[int], width: int, height: int, foreground_count: int) -> tuple[float, float]:
    if foreground_count <= 0:
        return 0.0, 0.0

    visited = [False] * len(binary_mask)
    largest = 0
    for index, value in enumerate(binary_mask):
        if value == 0 or visited[index]:
            continue

        stack = [index]
        visited[index] = True
        component_size = 0
        while stack:
            current = stack.pop()
            component_size += 1
            x = current % width
            y = current // width

            if x > 0:
                neighbor = current - 1
                if binary_mask[neighbor] and not visited[neighbor]:
                    visited[neighbor] = True
                    stack.append(neighbor)
            if x + 1 < width:
                neighbor = current + 1
                if binary_mask[neighbor] and not visited[neighbor]:
                    visited[neighbor] = True
                    stack.append(neighbor)
            if y > 0:
                neighbor = current - width
                if binary_mask[neighbor] and not visited[neighbor]:
                    visited[neighbor] = True
                    stack.append(neighbor)
            if y + 1 < height:
                neighbor = current + width
                if binary_mask[neighbor] and not visited[neighbor]:
                    visited[neighbor] = True
                    stack.append(neighbor)

        largest = max(largest, component_size)

    total_pixels = max(1, width * height)
    return largest / total_pixels, largest / foreground_count


def compute_subject_score(rgba_image: Any) -> SubjectScore:
    alpha_image = rgba_image.getchannel("A").convert("L")
    total_pixels = max(1, alpha_image.size[0] * alpha_image.size[1])
    histogram = alpha_image.histogram()
    weighted_alpha = sum(level * count for level, count in enumerate(histogram))
    alpha_mean_ratio = weighted_alpha / (255.0 * total_pixels)
    coverage_count = sum(histogram[24:])
    solid_count = sum(histogram[160:])
    coverage_ratio = coverage_count / total_pixels
    solid_ratio = solid_count / total_pixels

    reduced_alpha = shrink_mask_for_analysis(alpha_image)
    binary_mask = [1 if value >= 24 else 0 for value in reduced_alpha.getdata()]
    foreground_count = sum(binary_mask)
    largest_component_ratio, largest_component_share = compute_largest_component_ratio(
        binary_mask,
        reduced_alpha.size[0],
        reduced_alpha.size[1],
        foreground_count,
    )

    cohesion_bonus = largest_component_share * min(1.0, coverage_ratio * 3.0)
    raw_score = (
        alpha_mean_ratio * 0.55
        + coverage_ratio * 0.35
        + solid_ratio * 0.25
        + largest_component_ratio * 0.25
        + cohesion_bonus * 0.35
    ) * 2.2
    score = _clamp(int(round(min(1.0, raw_score) * 1000.0)), 0, 1000)
    return SubjectScore(
        score=score,
        alpha_mean_ratio=alpha_mean_ratio,
        coverage_ratio=coverage_ratio,
        solid_ratio=solid_ratio,
        largest_component_ratio=largest_component_ratio,
        largest_component_share=largest_component_share,
    )


def compose_output_image(rgba_image: Any, output_format: str) -> Any:
    if output_format == "transparent_png":
        return rgba_image
    if output_format == "mask_only":
        return rgba_image.getchannel("A")
    if output_format not in OUTPUT_COLOR_MAP:
        raise ValueError(f"未対応の出力形式です: {output_format}")

    background = Image.new("RGBA", rgba_image.size, OUTPUT_COLOR_MAP[output_format])
    composited = Image.alpha_composite(background, rgba_image)
    return composited.convert("RGB")


def save_output_image(image: Any, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")


def process_single_image(image_path: Path, settings: AppSettings, session: object) -> ImageProcessResult:
    if remove is None:
        raise RuntimeError("rembg が利用できません。")

    input_image = open_image_for_processing(image_path)
    if input_image.mode not in {"RGB", "RGBA"}:
        input_image = input_image.convert("RGBA")
    input_image = resize_long_edge_if_needed(input_image, settings.resize_enabled, settings.resize_long_edge)

    remove_kwargs: dict[str, object] = {
        "session": session,
        "alpha_matting": settings.alpha_matting,
        "alpha_matting_foreground_threshold": settings.alpha_foreground_threshold,
        "alpha_matting_background_threshold": settings.alpha_background_threshold,
        "alpha_matting_erode_size": settings.alpha_erode_size,
    }
    result = remove(input_image, **remove_kwargs)
    rgba_image = ensure_pil_image(result).convert("RGBA")
    return ImageProcessResult(
        rgba_image=rgba_image,
        output_image=compose_output_image(rgba_image, settings.output_format),
        subject_score=compute_subject_score(rgba_image),
    )


def write_run_log(settings: AppSettings, summary: BatchSummary) -> Path:
    output_folder = Path(settings.output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    log_path = output_folder / RUN_LOG_NAME

    finished_at = summary.finished_at or datetime.now()
    lines = [
        f"実行日時: {summary.started_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"終了日時: {finished_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"入力フォルダ: {settings.input_folder}",
        f"出力フォルダ: {settings.output_folder}",
        f"モデル: {settings.model_name}",
        f"出力形式: {OUTPUT_FORMAT_LABELS.get(settings.output_format, settings.output_format)}",
        f"対象拡張子: {', '.join(settings.target_extensions)}",
        f"再帰処理: {'ON' if settings.recursive else 'OFF'}",
        f"サブフォルダ構造維持: {'ON' if settings.preserve_structure else 'OFF'}",
        f"処理済みスキップ: {'ON' if settings.skip_existing else 'OFF'}",
        f"ファイル名モード: {'suffix' if settings.filename_mode == 'suffix' else 'keep_name'}",
        f"suffix: {settings.suffix}",
        f"Alpha matting: {'ON' if settings.alpha_matting else 'OFF'}",
        (
            "Alpha matting thresholds: "
            f"fg={settings.alpha_foreground_threshold}, "
            f"bg={settings.alpha_background_threshold}, "
            f"erode={settings.alpha_erode_size}"
        ),
        (
            f"リサイズ: {'ON' if settings.resize_enabled else 'OFF'}"
            + (f" / 長辺 {settings.resize_long_edge}px" if settings.resize_enabled else "")
        ),
        f"簡易人物スコア接頭辞: {'ON' if settings.score_prefix_enabled else 'OFF'}",
        f"低スコア除外: {'ON' if settings.low_score_filter_enabled else 'OFF'}",
        f"低スコアしきい値: {settings.low_score_threshold}",
        f"処理対象数: {summary.total_files}",
        f"成功数: {summary.success_count}",
        f"スキップ数: {summary.skipped_count}",
        f"低スコア除外数: {summary.low_score_skip_count}",
        f"エラー数: {summary.error_count}",
        f"中断: {'YES' if summary.stopped else 'NO'}",
    ]

    if summary.fatal_error:
        lines.extend(["", "致命的エラー:", summary.fatal_error])

    lines.extend(["", "エラー一覧:"])
    if summary.error_items:
        lines.extend(summary.error_items)
    else:
        lines.append("(なし)")

    if summary.log_write_error:
        lines.extend(["", "ログ書き込みエラー:", summary.log_write_error])

    log_path.write_text(WINDOWS_NEWLINE.join(lines) + WINDOWS_NEWLINE, encoding="utf-8-sig")
    return log_path


def append_time_prefix(message: str) -> str:
    return f"[{datetime.now().strftime('%H:%M:%S')}] {message}"


def make_checkerboard(size: tuple[int, int]) -> Any:
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow が利用できません。")

    image = Image.new("RGBA", size, (232, 232, 232, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], CHECKER_SIZE):
        for x in range(0, size[0], CHECKER_SIZE):
            if ((x // CHECKER_SIZE) + (y // CHECKER_SIZE)) % 2 == 0:
                draw.rectangle(
                    (x, y, x + CHECKER_SIZE - 1, y + CHECKER_SIZE - 1),
                    fill=(200, 200, 200, 255),
                )
    return image


def fit_preview_image(image: Any, max_size: tuple[int, int]) -> Any:
    preview = image.copy()
    preview.thumbnail(max_size, RESAMPLE_LANCZOS)
    return preview


def build_preview_bitmap(image: Any, *, transparent_background: bool) -> Any:
    preview = fit_preview_image(image, PREVIEW_MAX_SIZE)
    if transparent_background and preview.mode == "RGBA":
        background = make_checkerboard(preview.size)
        return Image.alpha_composite(background, preview)
    if preview.mode == "RGBA":
        return preview.convert("RGB")
    return preview


def create_preview_filetypes() -> list[tuple[str, str]]:
    return PREVIEW_FILETYPES


def batch_worker(
    settings: AppSettings,
    tasks: list[FileTask],
    stop_event: threading.Event,
    event_queue: "queue.Queue[dict[str, object]]",
) -> None:
    summary = BatchSummary(started_at=datetime.now(), total_files=len(tasks))
    event_queue.put({"type": "log", "message": "rembg セッションを準備しています。初回はモデルダウンロードで時間がかかる場合があります。"})

    try:
        ensure_processing_dependencies()
        if new_session is None:
            raise RuntimeError("rembg の new_session を利用できません。")
        session = new_session(settings.model_name)
        event_queue.put({"type": "log", "message": f"モデル {settings.model_name} のセッションを準備しました。"})
    except Exception as exc:
        summary.fatal_error = format_exception_message(exc)
        summary.error_items.append(f"[SESSION] {summary.fatal_error}")
        summary.finished_at = datetime.now()
        try:
            summary.log_file_path = write_run_log(settings, summary)
        except Exception as log_exc:
            summary.log_write_error = format_exception_message(log_exc)
        event_queue.put({"type": "done", "summary": summary})
        return

    for task in tasks:
        if stop_event.is_set():
            summary.stopped = True
            break

        event_queue.put({"type": "current_file", "path": task.relative_path})

        existing_outputs = find_existing_output_candidates(task.output_path, settings.score_prefix_enabled)
        if settings.skip_existing and existing_outputs:
            summary.skipped_count += 1
            event_queue.put(
                {
                    "type": "item_result",
                    "result": "skip",
                    "message": f"SKIP: {task.relative_path} -> {existing_outputs[0].name} (既存出力あり)",
                    "processed": summary.processed_count,
                    "total": summary.total_files,
                    "success": summary.success_count,
                    "skipped": summary.skipped_count,
                    "low_score_skipped": summary.low_score_skip_count,
                    "errors": summary.error_count,
                }
            )
            continue

        try:
            process_result = process_single_image(task.source_path, settings, session)
            score = process_result.subject_score.score

            if settings.low_score_filter_enabled and score < settings.low_score_threshold:
                removed_outputs = find_existing_output_candidates(task.output_path, True)
                for old_output in removed_outputs:
                    try:
                        old_output.unlink()
                    except FileNotFoundError:
                        pass
                summary.skipped_count += 1
                summary.low_score_skip_count += 1
                removal_note = " / 既存出力削除" if removed_outputs else ""
                event_queue.put(
                    {
                        "type": "item_result",
                        "result": "skip_low_score",
                        "message": (
                            f"LOW SCORE SKIP: {task.relative_path} "
                            f"(score={score:04d} < {settings.low_score_threshold:04d}{removal_note})"
                        ),
                        "processed": summary.processed_count,
                        "total": summary.total_files,
                        "success": summary.success_count,
                        "skipped": summary.skipped_count,
                        "low_score_skipped": summary.low_score_skip_count,
                        "errors": summary.error_count,
                    }
                )
                continue

            final_output_path = apply_score_prefix(task.output_path, score) if settings.score_prefix_enabled else task.output_path
            save_output_image(process_result.output_image, final_output_path)
            summary.success_count += 1
            event_queue.put(
                {
                    "type": "item_result",
                    "result": "success",
                    "message": f"OK: {task.relative_path} -> {final_output_path.name} (score={score:04d})",
                    "processed": summary.processed_count,
                    "total": summary.total_files,
                    "success": summary.success_count,
                    "skipped": summary.skipped_count,
                    "low_score_skipped": summary.low_score_skip_count,
                    "errors": summary.error_count,
                }
            )
        except Exception as exc:
            summary.error_count += 1
            details = f"{task.source_path} => {format_exception_message(exc)}"
            summary.error_items.append(details)
            event_queue.put(
                {
                    "type": "item_result",
                    "result": "error",
                    "message": f"ERROR: {task.relative_path} -> {format_exception_message(exc)}",
                    "processed": summary.processed_count,
                    "total": summary.total_files,
                    "success": summary.success_count,
                    "skipped": summary.skipped_count,
                    "low_score_skipped": summary.low_score_skip_count,
                    "errors": summary.error_count,
                }
            )

    if stop_event.is_set():
        summary.stopped = True

    summary.finished_at = datetime.now()
    try:
        summary.log_file_path = write_run_log(settings, summary)
    except Exception as exc:
        summary.log_write_error = format_exception_message(exc)

    event_queue.put({"type": "done", "summary": summary})


def preview_worker(
    image_path: Path,
    settings: AppSettings,
    event_queue: "queue.Queue[dict[str, object]]",
) -> None:
    try:
        ensure_processing_dependencies()
        if new_session is None:
            raise RuntimeError("rembg の new_session を利用できません。")

        original_image = open_image_for_processing(image_path)
        session = new_session(settings.model_name)
        process_result = process_single_image(image_path, settings, session)
        input_bitmap = build_preview_bitmap(original_image.convert("RGBA"), transparent_background=False)
        preview_transparent = settings.output_format == "transparent_png"
        if process_result.output_image.mode == "L":
            output_bitmap = build_preview_bitmap(process_result.output_image.convert("RGB"), transparent_background=False)
        else:
            output_bitmap = build_preview_bitmap(process_result.output_image.convert("RGBA"), transparent_background=preview_transparent)
        score = process_result.subject_score.score
        threshold_note = ""
        if settings.low_score_filter_enabled:
            threshold_note = (
                " / 出力対象"
                if score >= settings.low_score_threshold
                else " / 低スコア除外対象"
            )
        event_queue.put(
            {
                "type": "preview_done",
                "input_image": input_bitmap,
                "output_image": output_bitmap,
                "message": f"プレビュー完了: {image_path.name} / 簡易人物スコア {score:04d}{threshold_note}",
            }
        )
    except Exception as exc:
        event_queue.put({"type": "preview_failed", "message": format_exception_message(exc)})


class BackgroundRemoverGui:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry(DEFAULT_WINDOW_GEOMETRY)
        self.root.minsize(1160, 860)

        self.input_folder_var = tk.StringVar()
        self.output_folder_var = tk.StringVar()
        self.preview_image_path_var = tk.StringVar()
        self.recursive_var = tk.BooleanVar(value=True)
        self.preserve_structure_var = tk.BooleanVar(value=True)
        self.skip_existing_var = tk.BooleanVar(value=True)
        self.output_format_var = tk.StringVar(value="transparent_png")
        self.filename_mode_var = tk.StringVar(value="suffix")
        self.suffix_var = tk.StringVar(value="_nobg")
        self.model_name_var = tk.StringVar(value="u2net_human_seg")
        self.alpha_matting_var = tk.BooleanVar(value=False)
        self.alpha_foreground_threshold_var = tk.StringVar(value="270")
        self.alpha_background_threshold_var = tk.StringVar(value="20")
        self.alpha_erode_size_var = tk.StringVar(value="11")
        self.resize_enabled_var = tk.BooleanVar(value=False)
        self.resize_long_edge_var = tk.StringVar(value="1600")
        self.score_prefix_enabled_var = tk.BooleanVar(value=False)
        self.low_score_filter_enabled_var = tk.BooleanVar(value=False)
        self.low_score_threshold_var = tk.StringVar(value="60")
        self.status_var = tk.StringVar(value="待機中")
        self.current_file_var = tk.StringVar(value="-")
        self.counts_var = tk.StringVar(value="処理済み 0 / 0  |  成功 0  |  スキップ 0  |  低スコア除外 0  |  エラー 0")
        self.dependency_var = tk.StringVar(value="")
        self.preview_status_var = tk.StringVar(value="プレビュー未実行")

        self.extension_vars: dict[str, tk.BooleanVar] = {
            extension: tk.BooleanVar(value=extension in DEFAULT_EXTENSIONS)
            for extension in EXTENSION_ORDER
        }

        self.log_text: tk.Text
        self.progress_bar: ttk.Progressbar
        self.output_format_combo: ttk.Combobox
        self.model_combo: ttk.Combobox
        self.suffix_entry: ttk.Entry
        self.alpha_foreground_spin: ttk.Spinbox
        self.alpha_background_spin: ttk.Spinbox
        self.alpha_erode_spin: ttk.Spinbox
        self.resize_spin: ttk.Spinbox
        self.low_score_threshold_spin: ttk.Spinbox
        self.start_button: ttk.Button
        self.stop_button: ttk.Button
        self.count_button: ttk.Button
        self.save_settings_button: ttk.Button
        self.load_settings_button: ttk.Button
        self.close_button: ttk.Button
        self.preview_button: ttk.Button
        self.preview_input_label: ttk.Label
        self.preview_output_label: ttk.Label

        self.preview_input_photo: Any | None = None
        self.preview_output_photo: Any | None = None

        self.event_queue: "queue.Queue[dict[str, object]]" = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.preview_thread: threading.Thread | None = None
        self.pending_close = False
        self.active_total = 0

        self._build_layout()
        self._bind_events()
        self._load_settings_into_ui(show_message=False)
        self._update_control_states()
        self._update_dependency_banner()
        self._clear_preview_panels()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(120, self._poll_queue)

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)

        settings_frame = ttk.LabelFrame(self.root, text="処理設定", padding=10)
        settings_frame.grid(row=0, column=0, padx=10, pady=(10, 6), sticky="nsew")
        settings_frame.columnconfigure(1, weight=1)
        settings_frame.columnconfigure(4, weight=1)

        ttk.Label(settings_frame, text="入力フォルダ").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(settings_frame, textvariable=self.input_folder_var).grid(row=0, column=1, columnspan=3, sticky="ew", padx=(8, 8), pady=4)
        ttk.Button(settings_frame, text="参照...", command=self.choose_input_folder).grid(row=0, column=4, sticky="ew", pady=4)

        ttk.Label(settings_frame, text="出力フォルダ").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(settings_frame, textvariable=self.output_folder_var).grid(row=1, column=1, columnspan=3, sticky="ew", padx=(8, 8), pady=4)
        ttk.Button(settings_frame, text="参照...", command=self.choose_output_folder).grid(row=1, column=4, sticky="ew", pady=4)

        extensions_frame = ttk.Frame(settings_frame)
        extensions_frame.grid(row=2, column=1, columnspan=4, sticky="w", padx=(8, 0), pady=4)
        ttk.Label(settings_frame, text="対象拡張子").grid(row=2, column=0, sticky="nw", pady=4)
        for index, extension in enumerate(EXTENSION_ORDER):
            ttk.Checkbutton(extensions_frame, text=extension, variable=self.extension_vars[extension]).grid(
                row=0,
                column=index,
                sticky="w",
                padx=(0, 12),
            )

        option_flags_frame = ttk.Frame(settings_frame)
        option_flags_frame.grid(row=3, column=1, columnspan=4, sticky="w", padx=(8, 0), pady=4)
        ttk.Label(settings_frame, text="基本オプション").grid(row=3, column=0, sticky="nw", pady=4)
        ttk.Checkbutton(option_flags_frame, text="サブフォルダも処理する", variable=self.recursive_var).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(option_flags_frame, text="入力側の相対パスを出力側にも維持する", variable=self.preserve_structure_var).grid(row=0, column=1, sticky="w", padx=(18, 0))
        ttk.Checkbutton(option_flags_frame, text="出力済みファイルはスキップする", variable=self.skip_existing_var).grid(row=0, column=2, sticky="w", padx=(18, 0))

        ttk.Label(settings_frame, text="出力形式").grid(row=4, column=0, sticky="w", pady=4)
        self.output_format_combo = ttk.Combobox(
            settings_frame,
            state="readonly",
            values=[label for _key, label in OUTPUT_FORMATS],
            textvariable=self.output_format_var,
            width=18,
        )
        self.output_format_combo.grid(row=4, column=1, sticky="w", padx=(8, 8), pady=4)
        self.output_format_var.set(OUTPUT_FORMAT_LABELS["transparent_png"])
        ttk.Label(settings_frame, text="PNG で保存します。マスク画像のみは白黒 PNG です。").grid(
            row=4,
            column=2,
            columnspan=3,
            sticky="w",
            pady=4,
        )

        ttk.Label(settings_frame, text="出力ファイル名").grid(row=5, column=0, sticky="nw", pady=4)
        filename_frame = ttk.Frame(settings_frame)
        filename_frame.grid(row=5, column=1, columnspan=4, sticky="w", padx=(8, 0), pady=4)
        ttk.Radiobutton(
            filename_frame,
            text="元ファイル名のまま拡張子だけ png",
            variable=self.filename_mode_var,
            value="keep_name",
        ).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            filename_frame,
            text="suffix を付ける",
            variable=self.filename_mode_var,
            value="suffix",
        ).grid(row=0, column=1, sticky="w", padx=(18, 0))
        ttk.Label(filename_frame, text="suffix").grid(row=0, column=2, sticky="w", padx=(18, 6))
        self.suffix_entry = ttk.Entry(filename_frame, width=18, textvariable=self.suffix_var)
        self.suffix_entry.grid(row=0, column=3, sticky="w")
        ttk.Label(filename_frame, text="例: frame_000001_nobg.png").grid(row=0, column=4, sticky="w", padx=(10, 0))

        ttk.Label(settings_frame, text="rembg モデル").grid(row=6, column=0, sticky="w", pady=4)
        self.model_combo = ttk.Combobox(
            settings_frame,
            state="readonly",
            values=MODEL_CHOICES,
            textvariable=self.model_name_var,
            width=24,
        )
        self.model_combo.grid(row=6, column=1, sticky="w", padx=(8, 8), pady=4)
        ttk.Label(
            settings_frame,
            text="人物フレーム用途は u2net_human_seg を既定にしています。初回はモデルダウンロードが入る場合があります。",
        ).grid(row=6, column=2, columnspan=3, sticky="w", pady=4)

        ttk.Label(settings_frame, text="Alpha matting").grid(row=7, column=0, sticky="nw", pady=4)
        alpha_frame = ttk.Frame(settings_frame)
        alpha_frame.grid(row=7, column=1, columnspan=4, sticky="w", padx=(8, 0), pady=4)
        ttk.Checkbutton(alpha_frame, text="有効にする", variable=self.alpha_matting_var).grid(row=0, column=0, sticky="w")
        ttk.Label(alpha_frame, text="foreground").grid(row=0, column=1, sticky="w", padx=(18, 6))
        self.alpha_foreground_spin = ttk.Spinbox(alpha_frame, from_=0, to=1000, width=8, textvariable=self.alpha_foreground_threshold_var)
        self.alpha_foreground_spin.grid(row=0, column=2, sticky="w")
        ttk.Label(alpha_frame, text="background").grid(row=0, column=3, sticky="w", padx=(12, 6))
        self.alpha_background_spin = ttk.Spinbox(alpha_frame, from_=0, to=1000, width=8, textvariable=self.alpha_background_threshold_var)
        self.alpha_background_spin.grid(row=0, column=4, sticky="w")
        ttk.Label(alpha_frame, text="erode").grid(row=0, column=5, sticky="w", padx=(12, 6))
        self.alpha_erode_spin = ttk.Spinbox(alpha_frame, from_=0, to=100, width=8, textvariable=self.alpha_erode_size_var)
        self.alpha_erode_spin.grid(row=0, column=6, sticky="w")
        ttk.Label(alpha_frame, text="髪や境界を改善できる場合がありますが遅くなります。").grid(row=0, column=7, sticky="w", padx=(12, 0))

        ttk.Label(settings_frame, text="前処理リサイズ").grid(row=8, column=0, sticky="nw", pady=4)
        resize_frame = ttk.Frame(settings_frame)
        resize_frame.grid(row=8, column=1, columnspan=4, sticky="w", padx=(8, 0), pady=4)
        ttk.Checkbutton(resize_frame, text="処理前に長辺を指定ピクセルへ縮小する", variable=self.resize_enabled_var).grid(row=0, column=0, sticky="w")
        ttk.Label(resize_frame, text="長辺").grid(row=0, column=1, sticky="w", padx=(18, 6))
        self.resize_spin = ttk.Spinbox(resize_frame, from_=1, to=10000, width=8, textvariable=self.resize_long_edge_var)
        self.resize_spin.grid(row=0, column=2, sticky="w")
        ttk.Label(resize_frame, text="px").grid(row=0, column=3, sticky="w", padx=(6, 0))

        ttk.Label(settings_frame, text="簡易人物スコア").grid(row=9, column=0, sticky="nw", pady=4)
        score_frame = ttk.Frame(settings_frame)
        score_frame.grid(row=9, column=1, columnspan=4, sticky="w", padx=(8, 0), pady=4)
        ttk.Checkbutton(
            score_frame,
            text="ファイル名の先頭に score を付ける",
            variable=self.score_prefix_enabled_var,
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            score_frame,
            text="score がしきい値未満なら出力しない",
            variable=self.low_score_filter_enabled_var,
        ).grid(row=0, column=1, sticky="w", padx=(18, 0))
        ttk.Label(score_frame, text="しきい値").grid(row=0, column=2, sticky="w", padx=(18, 6))
        self.low_score_threshold_spin = ttk.Spinbox(
            score_frame,
            from_=0,
            to=1000,
            width=8,
            textvariable=self.low_score_threshold_var,
        )
        self.low_score_threshold_spin.grid(row=0, column=3, sticky="w")
        ttk.Label(score_frame, text="0-1000 / rembg の生スコアではなく、マスクから作る簡易値です。").grid(
            row=0,
            column=4,
            sticky="w",
            padx=(12, 0),
        )

        dependency_label = ttk.Label(
            settings_frame,
            textvariable=self.dependency_var,
            foreground="#9c3d00",
            justify="left",
        )
        dependency_label.grid(row=10, column=0, columnspan=5, sticky="w", pady=(8, 0))

        preview_frame = ttk.LabelFrame(self.root, text="プレビュー", padding=10)
        preview_frame.grid(row=1, column=0, padx=10, pady=6, sticky="nsew")
        preview_frame.columnconfigure(1, weight=1)
        preview_frame.columnconfigure(2, weight=1)

        ttk.Label(preview_frame, text="プレビュー画像").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(preview_frame, textvariable=self.preview_image_path_var).grid(row=0, column=1, sticky="ew", padx=(8, 8), pady=4)
        preview_button_row = ttk.Frame(preview_frame)
        preview_button_row.grid(row=0, column=2, sticky="e", pady=4)
        ttk.Button(preview_button_row, text="参照...", command=self.choose_preview_image).pack(side="left")
        self.preview_button = ttk.Button(preview_button_row, text="現在設定でプレビュー", command=self.start_preview)
        self.preview_button.pack(side="left", padx=(8, 0))

        preview_images_frame = ttk.Frame(preview_frame)
        preview_images_frame.grid(row=1, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        preview_images_frame.columnconfigure(0, weight=1)
        preview_images_frame.columnconfigure(1, weight=1)

        input_preview_group = ttk.LabelFrame(preview_images_frame, text="入力画像", padding=8)
        input_preview_group.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        input_preview_group.columnconfigure(0, weight=1)
        self.preview_input_label = ttk.Label(input_preview_group, anchor="center")
        self.preview_input_label.grid(row=0, column=0, sticky="nsew")

        output_preview_group = ttk.LabelFrame(preview_images_frame, text="背景削除結果", padding=8)
        output_preview_group.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        output_preview_group.columnconfigure(0, weight=1)
        self.preview_output_label = ttk.Label(output_preview_group, anchor="center")
        self.preview_output_label.grid(row=0, column=0, sticky="nsew")

        ttk.Label(preview_frame, textvariable=self.preview_status_var).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))

        progress_frame = ttk.LabelFrame(self.root, text="進捗", padding=10)
        progress_frame.grid(row=2, column=0, padx=10, pady=6, sticky="ew")
        progress_frame.columnconfigure(0, weight=1)
        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate", maximum=100, value=0)
        self.progress_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(progress_frame, textvariable=self.status_var).grid(row=1, column=0, sticky="w")
        ttk.Label(progress_frame, textvariable=self.current_file_var).grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Label(progress_frame, textvariable=self.counts_var).grid(row=3, column=0, sticky="w", pady=(4, 0))

        log_frame = ttk.LabelFrame(self.root, text="ログ", padding=10)
        log_frame.grid(row=3, column=0, padx=10, pady=6, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, wrap="word", height=16, font=("Consolas", 10))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        button_frame = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        button_frame.grid(row=4, column=0, sticky="ew")
        button_frame.columnconfigure(0, weight=1)
        left_buttons = ttk.Frame(button_frame)
        left_buttons.grid(row=0, column=0, sticky="w")
        self.count_button = ttk.Button(left_buttons, text="対象ファイル数を確認", command=self.count_files)
        self.count_button.pack(side="left")
        self.start_button = ttk.Button(left_buttons, text="開始", command=self.start_processing)
        self.start_button.pack(side="left", padx=(8, 0))
        self.stop_button = ttk.Button(left_buttons, text="中断", command=self.stop_processing)
        self.stop_button.pack(side="left", padx=(8, 0))

        right_buttons = ttk.Frame(button_frame)
        right_buttons.grid(row=0, column=1, sticky="e")
        self.save_settings_button = ttk.Button(right_buttons, text="設定保存", command=self.save_settings_button_clicked)
        self.save_settings_button.pack(side="left")
        self.load_settings_button = ttk.Button(right_buttons, text="設定読込", command=self.load_settings_button_clicked)
        self.load_settings_button.pack(side="left", padx=(8, 0))
        self.close_button = ttk.Button(right_buttons, text="閉じる", command=self.on_close)
        self.close_button.pack(side="left", padx=(8, 0))

    def _bind_events(self) -> None:
        tracked_vars = [
            self.filename_mode_var,
            self.alpha_matting_var,
            self.resize_enabled_var,
            self.low_score_filter_enabled_var,
            self.model_name_var,
            self.output_format_var,
        ]
        for variable in tracked_vars:
            variable.trace_add("write", self._on_settings_changed)

    def _on_settings_changed(self, *_args: object) -> None:
        self._update_control_states()

    def _update_control_states(self) -> None:
        suffix_state = "normal" if self.filename_mode_var.get() == "suffix" else "disabled"
        alpha_state = "normal" if self.alpha_matting_var.get() else "disabled"
        resize_state = "normal" if self.resize_enabled_var.get() else "disabled"
        low_score_state = "normal" if self.low_score_filter_enabled_var.get() else "disabled"
        is_busy = self.is_processing()
        preview_busy = self.is_preview_running()

        self.suffix_entry.configure(state=suffix_state)
        self.alpha_foreground_spin.configure(state=alpha_state)
        self.alpha_background_spin.configure(state=alpha_state)
        self.alpha_erode_spin.configure(state=alpha_state)
        self.resize_spin.configure(state=resize_state)
        self.low_score_threshold_spin.configure(state=low_score_state)

        self.start_button.configure(state="disabled" if is_busy else "normal")
        self.count_button.configure(state="disabled" if is_busy else "normal")
        self.stop_button.configure(state="normal" if is_busy else "disabled")
        self.preview_button.configure(state="disabled" if is_busy or preview_busy else "normal")

    def _update_dependency_banner(self) -> None:
        dependency_messages = get_dependency_messages()
        if dependency_messages:
            self.dependency_var.set(WINDOWS_NEWLINE.join(dependency_messages))
        else:
            self.dependency_var.set("依存関係 OK: Pillow / rembg を利用できます。")

    def _load_settings_into_ui(self, *, show_message: bool) -> None:
        settings = load_settings()
        self.input_folder_var.set(settings.input_folder)
        self.output_folder_var.set(settings.output_folder)
        self.preview_image_path_var.set(settings.preview_image_path)
        self.recursive_var.set(settings.recursive)
        self.preserve_structure_var.set(settings.preserve_structure)
        self.skip_existing_var.set(settings.skip_existing)
        self.output_format_var.set(OUTPUT_FORMAT_LABELS.get(settings.output_format, OUTPUT_FORMAT_LABELS["transparent_png"]))
        self.filename_mode_var.set(settings.filename_mode)
        self.suffix_var.set(settings.suffix)
        self.model_name_var.set(settings.model_name)
        self.alpha_matting_var.set(settings.alpha_matting)
        self.alpha_foreground_threshold_var.set(str(settings.alpha_foreground_threshold))
        self.alpha_background_threshold_var.set(str(settings.alpha_background_threshold))
        self.alpha_erode_size_var.set(str(settings.alpha_erode_size))
        self.resize_enabled_var.set(settings.resize_enabled)
        self.resize_long_edge_var.set(str(settings.resize_long_edge))
        self.score_prefix_enabled_var.set(settings.score_prefix_enabled)
        self.low_score_filter_enabled_var.set(settings.low_score_filter_enabled)
        self.low_score_threshold_var.set(str(settings.low_score_threshold))

        for extension, variable in self.extension_vars.items():
            variable.set(extension in settings.target_extensions)

        label_values = [label for _key, label in OUTPUT_FORMATS]
        label_map = {key: label for key, label in OUTPUT_FORMATS}
        self.output_format_combo.configure(values=label_values)
        self.output_format_combo.set(label_map.get(settings.output_format, label_values[0]))
        self.model_combo.set(settings.model_name)

        geometry = settings.window_geometry.strip()
        if geometry:
            self.root.geometry(geometry)

        if show_message:
            messagebox.showinfo("設定読込", f"設定を読み込みました。\n{SETTINGS_PATH}")
        self._update_control_states()

    def collect_settings(self) -> AppSettings:
        output_format_label = self.output_format_var.get().strip() or self.output_format_combo.get().strip()
        label_to_key = {label: key for key, label in OUTPUT_FORMATS}
        output_format_key = label_to_key.get(output_format_label, "transparent_png")

        target_extensions = [
            extension
            for extension in EXTENSION_ORDER
            if self.extension_vars[extension].get()
        ]

        return AppSettings(
            input_folder=self.input_folder_var.get().strip(),
            output_folder=self.output_folder_var.get().strip(),
            preview_image_path=self.preview_image_path_var.get().strip(),
            target_extensions=target_extensions,
            recursive=self.recursive_var.get(),
            preserve_structure=self.preserve_structure_var.get(),
            skip_existing=self.skip_existing_var.get(),
            output_format=output_format_key,
            filename_mode=self.filename_mode_var.get(),
            suffix=self.suffix_var.get().strip(),
            model_name=self.model_name_var.get().strip() or "u2net_human_seg",
            alpha_matting=self.alpha_matting_var.get(),
            alpha_foreground_threshold=_safe_int(self.alpha_foreground_threshold_var.get(), 270),
            alpha_background_threshold=_safe_int(self.alpha_background_threshold_var.get(), 20),
            alpha_erode_size=_safe_int(self.alpha_erode_size_var.get(), 11),
            resize_enabled=self.resize_enabled_var.get(),
            resize_long_edge=max(1, _safe_int(self.resize_long_edge_var.get(), 1600)),
            score_prefix_enabled=self.score_prefix_enabled_var.get(),
            low_score_filter_enabled=self.low_score_filter_enabled_var.get(),
            low_score_threshold=_clamp(_safe_int(self.low_score_threshold_var.get(), 60), 0, 1000),
            window_geometry=self.root.geometry(),
        )

    def save_settings_button_clicked(self) -> None:
        self._save_settings(show_message=True)

    def load_settings_button_clicked(self) -> None:
        if not SETTINGS_PATH.exists():
            messagebox.showwarning("設定読込", f"設定ファイルが見つかりません。\n{SETTINGS_PATH}")
            return
        self._load_settings_into_ui(show_message=True)
        self.append_log("設定ファイルを読み込みました。")

    def _save_settings(self, *, show_message: bool, log_message: bool = True) -> None:
        settings = self.collect_settings()
        save_settings(settings)
        if show_message:
            messagebox.showinfo("設定保存", f"設定を保存しました。\n{SETTINGS_PATH}")
        if log_message:
            self.append_log("設定ファイルを保存しました。")

    def choose_input_folder(self) -> None:
        initial_dir = self._existing_directory(self.input_folder_var.get()) or self._existing_directory(self.output_folder_var.get())
        selected = filedialog.askdirectory(parent=self.root, title="入力フォルダを選択", initialdir=initial_dir)
        if selected:
            self.input_folder_var.set(selected)

    def choose_output_folder(self) -> None:
        initial_dir = self._existing_directory(self.output_folder_var.get()) or self._existing_directory(self.input_folder_var.get())
        selected = filedialog.askdirectory(parent=self.root, title="出力フォルダを選択", initialdir=initial_dir)
        if selected:
            self.output_folder_var.set(selected)

    def choose_preview_image(self) -> None:
        initial_dir = self._existing_parent_directory(self.preview_image_path_var.get()) or self._existing_directory(self.input_folder_var.get())
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="プレビュー画像を選択",
            filetypes=create_preview_filetypes(),
            initialdir=initial_dir,
        )
        if selected:
            self.preview_image_path_var.set(selected)

    def _existing_directory(self, value: str) -> str:
        candidate = Path(value.strip()) if value.strip() else None
        if candidate and candidate.is_dir():
            return str(candidate)
        return str(Path.home())

    def _existing_parent_directory(self, value: str) -> str:
        candidate = Path(value.strip()) if value.strip() else None
        if candidate and candidate.exists():
            return str(candidate.parent if candidate.is_file() else candidate)
        return str(Path.home())

    def append_log(self, message: str) -> None:
        self.log_text.insert("end", append_time_prefix(message) + WINDOWS_NEWLINE)
        self.log_text.see("end")

    def _replace_label_image(self, target: ttk.Label, pil_image: Any | None, *, store_name: str) -> None:
        if pil_image is None or ImageTk is None:
            setattr(self, store_name, None)
            target.configure(image="", text="プレビューなし")
            return

        photo = ImageTk.PhotoImage(pil_image)
        setattr(self, store_name, photo)
        target.configure(image=photo, text="")

    def _clear_preview_panels(self) -> None:
        self._replace_label_image(self.preview_input_label, None, store_name="preview_input_photo")
        self._replace_label_image(self.preview_output_label, None, store_name="preview_output_photo")

    def _set_progress(self, processed: int, total: int, success: int, skipped: int, low_score_skipped: int, errors: int) -> None:
        self.active_total = total
        ratio = (processed / total * 100.0) if total else 0.0
        self.progress_bar.configure(value=ratio)
        self.counts_var.set(
            f"処理済み {processed} / {total}  |  成功 {success}  |  スキップ {skipped}  |  低スコア除外 {low_score_skipped}  |  エラー {errors}"
        )

    def count_files(self) -> None:
        try:
            settings = self.collect_settings()
            tasks = build_file_tasks(settings)
        except Exception as exc:
            messagebox.showerror("対象ファイル数を確認", str(exc))
            return

        count = len(tasks)
        self.status_var.set(f"対象ファイル数: {count} 件")
        self.current_file_var.set("-")
        self._set_progress(0, count, 0, 0, 0, 0)
        self.append_log(f"対象ファイル数を確認しました: {count} 件")
        if count == 0:
            messagebox.showwarning("対象ファイル数を確認", "条件に一致する対象ファイルがありません。")

    def start_processing(self) -> None:
        if self.is_processing():
            return

        try:
            settings = self.collect_settings()
            tasks = build_file_tasks(settings)
            ensure_processing_dependencies()
        except Exception as exc:
            messagebox.showerror("開始", str(exc))
            return

        if not tasks:
            messagebox.showwarning("開始", "条件に一致する対象ファイルがありません。")
            return

        self._save_settings(show_message=False, log_message=False)
        self.stop_event = threading.Event()
        self.status_var.set("処理中")
        self.current_file_var.set("準備中...")
        self._set_progress(0, len(tasks), 0, 0, 0, 0)
        self.append_log(f"処理開始: 対象 {len(tasks)} 件 / モデル {settings.model_name} / 出力形式 {OUTPUT_FORMAT_LABELS[settings.output_format]}")
        self.append_log(f"入力: {settings.input_folder}")
        self.append_log(f"出力: {settings.output_folder}")
        if settings.score_prefix_enabled or settings.low_score_filter_enabled:
            self.append_log(
                "簡易人物スコア: "
                f"prefix={'ON' if settings.score_prefix_enabled else 'OFF'} / "
                f"低スコア除外={'ON' if settings.low_score_filter_enabled else 'OFF'} / "
                f"しきい値={settings.low_score_threshold:04d}"
            )

        self.worker_thread = threading.Thread(
            target=batch_worker,
            args=(settings, tasks, self.stop_event, self.event_queue),
            daemon=True,
        )
        self.worker_thread.start()
        self._update_control_states()

    def stop_processing(self) -> None:
        if not self.is_processing():
            return
        self.stop_event.set()
        self.status_var.set("中断要求を送信しました。現在のファイル処理が終わり次第停止します。")
        self.append_log("中断要求を受け付けました。")
        self._update_control_states()

    def start_preview(self) -> None:
        if self.is_processing() or self.is_preview_running():
            return

        preview_path_text = self.preview_image_path_var.get().strip()
        if not preview_path_text:
            messagebox.showerror("プレビュー", "プレビュー画像を指定してください。")
            return

        preview_path = Path(preview_path_text)
        if not preview_path.is_file():
            messagebox.showerror("プレビュー", "プレビュー画像が存在しません。")
            return

        try:
            settings = self.collect_settings()
            validate_preview_settings(settings)
            ensure_processing_dependencies()
        except Exception as exc:
            messagebox.showerror("プレビュー", str(exc))
            return

        self.preview_status_var.set("プレビュー実行中...")
        self.append_log(f"プレビュー開始: {preview_path}")
        self.preview_thread = threading.Thread(
            target=preview_worker,
            args=(preview_path, settings, self.event_queue),
            daemon=True,
        )
        self.preview_thread.start()
        self._update_control_states()

    def is_processing(self) -> bool:
        return self.worker_thread is not None and self.worker_thread.is_alive()

    def is_preview_running(self) -> bool:
        return self.preview_thread is not None and self.preview_thread.is_alive()

    def _poll_queue(self) -> None:
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_event(event)

        self._update_control_states()
        self.root.after(120, self._poll_queue)

    def _handle_event(self, event: dict[str, object]) -> None:
        event_type = str(event.get("type", ""))

        if event_type == "log":
            self.append_log(str(event.get("message", "")))
            return

        if event_type == "current_file":
            current_path = str(event.get("path", ""))
            self.current_file_var.set(f"現在処理中: {current_path}")
            return

        if event_type == "item_result":
            self._set_progress(
                _safe_int(event.get("processed"), 0),
                _safe_int(event.get("total"), self.active_total),
                _safe_int(event.get("success"), 0),
                _safe_int(event.get("skipped"), 0),
                _safe_int(event.get("low_score_skipped"), 0),
                _safe_int(event.get("errors"), 0),
            )
            self.append_log(str(event.get("message", "")))
            return

        if event_type == "done":
            summary = event.get("summary")
            if not isinstance(summary, BatchSummary):
                return
            self.worker_thread = None
            self._set_progress(
                summary.processed_count,
                summary.total_files,
                summary.success_count,
                summary.skipped_count,
                summary.low_score_skip_count,
                summary.error_count,
            )
            self.current_file_var.set("-")
            if summary.fatal_error:
                self.status_var.set("処理失敗")
                self.append_log(f"致命的エラー: {summary.fatal_error}")
            elif summary.stopped:
                self.status_var.set("中断完了")
                self.append_log("中断しました。")
            else:
                self.status_var.set("完了")
                self.append_log("全件処理が完了しました。")

            if summary.log_file_path is not None:
                self.append_log(f"実行ログを保存しました: {summary.log_file_path}")
            if summary.log_write_error:
                self.append_log(f"ログ保存エラー: {summary.log_write_error}")

            self.append_log(
                f"結果: 成功 {summary.success_count} / スキップ {summary.skipped_count} / 低スコア除外 {summary.low_score_skip_count} / エラー {summary.error_count}"
            )

            if self.pending_close:
                self._finalize_close()
            return

        if event_type == "preview_done":
            self.preview_thread = None
            input_image = event.get("input_image")
            output_image = event.get("output_image")
            self._replace_label_image(self.preview_input_label, input_image, store_name="preview_input_photo")
            self._replace_label_image(self.preview_output_label, output_image, store_name="preview_output_photo")
            message = str(event.get("message", "プレビュー完了"))
            self.preview_status_var.set(message)
            self.append_log(message)
            return

        if event_type == "preview_failed":
            self.preview_thread = None
            message = str(event.get("message", "プレビューに失敗しました。"))
            self.preview_status_var.set(message)
            self.append_log(f"プレビュー失敗: {message}")
            messagebox.showerror("プレビュー", message)
            return

    def on_close(self) -> None:
        if self.is_processing():
            if not messagebox.askyesno(
                "閉じる",
                "まだ処理中です。中断要求を出して処理終了後に閉じますか？",
                parent=self.root,
            ):
                return
            self.pending_close = True
            self.stop_processing()
            return

        self._finalize_close()

    def _finalize_close(self) -> None:
        try:
            self._save_settings(show_message=False, log_message=False)
        except Exception:
            pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    try:
        app = BackgroundRemoverGui()
    except Exception as exc:
        traceback.print_exc()
        try:
            messagebox.showerror(APP_TITLE, f"GUI の起動に失敗しました。\n\n{format_exception_message(exc)}")
        except Exception:
            pass
        raise
    app.run()


if __name__ == "__main__":
    main()
