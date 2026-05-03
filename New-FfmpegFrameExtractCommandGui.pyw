from __future__ import annotations

import ctypes
import json
import math
import os
import queue
import re
import shutil
import subprocess
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any


APP_TITLE = "ffmpeg フレーム抽出コマンド作成 GUI"
WINDOWS_NEWLINE = "\r\n"
SETTINGS_PATH = Path(__file__).with_suffix(".settings.json")
LOGS_DIR = Path(__file__).with_name("logs")
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".m4v", ".ts", ".webm"}
VIDEO_FILETYPES = [
    ("動画ファイル", "*.mp4 *.mkv *.mov *.avi *.wmv *.m4v *.ts *.webm"),
    ("すべてのファイル", "*.*"),
]
FFMPEG_FILETYPES = [
    ("ffmpeg.exe", "ffmpeg.exe"),
    ("実行ファイル", "*.exe"),
    ("すべてのファイル", "*.*"),
]
JSON_FILETYPES = [
    ("JSON ファイル", "*.json"),
    ("すべてのファイル", "*.*"),
]

EXTRACT_MODES = [
    "10秒ごと",
    "5秒ごと",
    "1秒ごと",
    "指定秒ごと",
    "全フレーム",
]
IMAGE_FORMATS = ["jpg", "png"]
QUEUE_STATUSES = ["未処理", "実行中", "完了", "失敗", "スキップ", "キャンセル"]

DUPLICATE_SUBFOLDER_MODE_LABELS = {
    "create_numbered_folder": "新規連番フォルダを作る",
    "reuse_existing_folder": "既存フォルダを使う",
}
EXISTING_OUTPUT_MODE_LABELS = {
    "skip_existing": "既存出力があればスキップ",
    "create_numbered_folder": "既存出力があれば連番フォルダを作る",
    "recreate_output": "既存出力を消して作り直す",
}
AFTER_COMPLETE_ACTION_LABELS = {
    "none": "何もしない",
    "beep": "完了音を鳴らす",
    "open_output": "出力フォルダを開く",
    "shutdown": "PCをシャットダウン",
    "sleep": "PCをスリープ",
}

TREE_COLUMNS = (
    "enabled",
    "file_name",
    "full_path",
    "duration",
    "estimated",
    "status",
    "output_dir",
    "actual_count",
    "error_message",
)

DEFAULT_COLUMN_WIDTHS = {
    "enabled": 60,
    "file_name": 240,
    "full_path": 440,
    "duration": 110,
    "estimated": 120,
    "status": 90,
    "output_dir": 360,
    "actual_count": 100,
    "error_message": 320,
}

TREE_HEADINGS = {
    "enabled": "選択",
    "file_name": "動画ファイル名",
    "full_path": "フルパス",
    "duration": "長さ",
    "estimated": "推定出力枚数",
    "status": "状態",
    "output_dir": "出力先フォルダ",
    "actual_count": "出力枚数",
    "error_message": "エラーメッセージ",
}

INVALID_FILE_CHARS = re.compile(r'[<>:"/\\|?*]')
TIME_PROGRESS_RE = re.compile(r"^(\d+):(\d{2}):(\d{2}(?:\.\d+)?)$")
DURATION_LINE_RE = re.compile(r"Duration:\s*(\d+:\d+:\d+(?:\.\d+)?)")
FPS_LINE_RE = re.compile(r"[, ]([0-9]+(?:\.[0-9]+)?)\s+fps[, ]")

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


@dataclass
class AppSettings:
    input_path: str = ""
    output_folder: str = ""
    output_root: str = ""
    base_name: str = "frame"
    file_name_pattern: str = "{video_name}_{frame_no}"
    digits: int = 6
    image_format: str = "jpg"
    jpeg_quality: int = 2
    extract_mode: str = "10秒ごと"
    custom_seconds: float = 10.0
    start_position: str = ""
    end_position: str = ""
    duration: str = ""
    resize_enabled: bool = False
    resize_width: int = 0
    resize_height: int = 0
    keep_aspect: bool = True
    include_mkdir: bool = True
    overwrite: bool = False
    use_ffmpeg_path: bool = False
    ffmpeg_path: str = "ffmpeg"
    duplicate_subfolder_mode: str = "create_numbered_folder"
    existing_output_mode: str = "create_numbered_folder"
    prevent_sleep: bool = True
    after_complete_action: str = "none"
    input_video_history: list[str] = field(default_factory=list)
    window_width: int = 1440
    window_height: int = 1080
    column_widths: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_COLUMN_WIDTHS))

    @classmethod
    def from_dict(cls, raw: object) -> "AppSettings":
        data = raw if isinstance(raw, dict) else {}
        window_size = data.get("WindowSize", {}) if isinstance(data.get("WindowSize"), dict) else {}
        column_widths_raw = data.get("ColumnWidths", {})
        column_widths: dict[str, int] = dict(DEFAULT_COLUMN_WIDTHS)
        if isinstance(column_widths_raw, dict):
            for key in TREE_COLUMNS:
                if key in column_widths_raw:
                    column_widths[key] = _clamp(_safe_int(column_widths_raw.get(key), column_widths[key]), 40, 1200)

        history = data.get("InputVideoHistory", [])
        history_list = [str(item).strip() for item in history if str(item).strip()] if isinstance(history, list) else []

        return cls(
            input_path=_safe_string(data.get("InputPath", "")),
            output_folder=_safe_string(data.get("OutputFolder", "")),
            output_root=_safe_string(data.get("OutputRoot", "")),
            base_name=_safe_string(data.get("BaseName", "frame")) or "frame",
            file_name_pattern=_safe_string(data.get("FileNamePattern", "{video_name}_{frame_no}")) or "{video_name}_{frame_no}",
            digits=_clamp(_safe_int(data.get("Digits", 6), 6), 1, 10),
            image_format=_safe_choice(data.get("ImageFormat", "jpg"), IMAGE_FORMATS, "jpg"),
            jpeg_quality=_clamp(_safe_int(data.get("JpegQuality", 2), 2), 1, 31),
            extract_mode=_safe_choice(data.get("ExtractMode", "10秒ごと"), EXTRACT_MODES, "10秒ごと"),
            custom_seconds=max(_safe_float(data.get("CustomSeconds", 10.0), 10.0), 0.001),
            start_position=_safe_string(data.get("StartPosition", "")),
            end_position=_safe_string(data.get("EndPosition", "")),
            duration=_safe_string(data.get("Duration", "")),
            resize_enabled=_safe_bool(data.get("ResizeEnabled", False)),
            resize_width=max(0, _safe_int(data.get("ResizeWidth", 0), 0)),
            resize_height=max(0, _safe_int(data.get("ResizeHeight", 0), 0)),
            keep_aspect=_safe_bool(data.get("KeepAspect", True)),
            include_mkdir=_safe_bool(data.get("IncludeMkdir", True)),
            overwrite=_safe_bool(data.get("Overwrite", False)),
            use_ffmpeg_path=_safe_bool(data.get("UseFfmpegPath", False)),
            ffmpeg_path=_safe_string(data.get("FfmpegPath", "ffmpeg")) or "ffmpeg",
            duplicate_subfolder_mode=_safe_choice(
                data.get("DuplicateSubfolderMode", "create_numbered_folder"),
                list(DUPLICATE_SUBFOLDER_MODE_LABELS.keys()),
                "create_numbered_folder",
            ),
            existing_output_mode=_safe_choice(
                data.get("ExistingOutputMode", "create_numbered_folder"),
                list(EXISTING_OUTPUT_MODE_LABELS.keys()),
                "create_numbered_folder",
            ),
            prevent_sleep=_safe_bool(data.get("PreventSleep", True)),
            after_complete_action=_safe_choice(
                data.get("AfterCompleteAction", "none"),
                list(AFTER_COMPLETE_ACTION_LABELS.keys()),
                "none",
            ),
            input_video_history=_unique_strings(history_list),
            window_width=_clamp(_safe_int(window_size.get("Width", 1440), 1440), 1000, 2800),
            window_height=_clamp(_safe_int(window_size.get("Height", 1080), 1080), 760, 2000),
            column_widths=column_widths,
        )

    def to_dict(self) -> dict[str, object]:
        raw = asdict(self)
        return {
            "InputPath": raw["input_path"],
            "OutputFolder": raw["output_folder"],
            "OutputRoot": raw["output_root"],
            "BaseName": raw["base_name"],
            "FileNamePattern": raw["file_name_pattern"],
            "Digits": raw["digits"],
            "ImageFormat": raw["image_format"],
            "JpegQuality": raw["jpeg_quality"],
            "ExtractMode": raw["extract_mode"],
            "CustomSeconds": raw["custom_seconds"],
            "StartPosition": raw["start_position"],
            "EndPosition": raw["end_position"],
            "Duration": raw["duration"],
            "ResizeEnabled": raw["resize_enabled"],
            "ResizeWidth": raw["resize_width"],
            "ResizeHeight": raw["resize_height"],
            "KeepAspect": raw["keep_aspect"],
            "IncludeMkdir": raw["include_mkdir"],
            "Overwrite": raw["overwrite"],
            "UseFfmpegPath": raw["use_ffmpeg_path"],
            "FfmpegPath": raw["ffmpeg_path"],
            "DuplicateSubfolderMode": raw["duplicate_subfolder_mode"],
            "ExistingOutputMode": raw["existing_output_mode"],
            "PreventSleep": raw["prevent_sleep"],
            "AfterCompleteAction": raw["after_complete_action"],
            "InputVideoHistory": raw["input_video_history"],
            "WindowSize": {
                "Width": raw["window_width"],
                "Height": raw["window_height"],
            },
            "ColumnWidths": raw["column_widths"],
        }


@dataclass
class VideoQueueItem:
    queue_id: str
    input_path: str
    enabled: bool = True
    status: str = "未処理"
    output_dir: str = ""
    duration_seconds: float | None = None
    fps: float | None = None
    estimated_frame_count: int | None = None
    actual_output_count: int | None = None
    error_message: str = ""
    ffmpeg_command: str = ""
    exit_code: int | None = None

    @property
    def file_name(self) -> str:
        return Path(self.input_path).name

    @property
    def normalized_path(self) -> str:
        return str(Path(self.input_path)).lower()

    def to_job_dict(self) -> dict[str, object]:
        return {
            "input_path": self.input_path,
            "enabled": self.enabled,
            "output_dir": self.output_dir,
            "status": self.status,
        }


@dataclass
class ProbeResult:
    duration_seconds: float | None = None
    fps: float | None = None
    error_message: str = ""


@dataclass
class PlannedOutput:
    output_dir: Path
    will_skip: bool = False
    will_delete: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class BatchItemResult:
    queue_id: str
    input_path: str
    output_dir: str
    status: str
    duration_seconds: float | None
    interval_seconds: float | None
    estimated_frame_count: int | None
    actual_output_count: int | None
    ffmpeg_command: str
    exit_code: int | None
    error_message: str


def _safe_string(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _safe_choice(value: object, allowed: list[str], default: str) -> str:
    text = _safe_string(value)
    return text if text in allowed else default


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip().lower()
        if not value or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def load_settings() -> AppSettings:
    if not SETTINGS_PATH.exists():
        return AppSettings()
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        messagebox.showwarning("設定読込", f"設定ファイルの読み込みに失敗しました。既定値で起動します。\n\n{exc}")
        return AppSettings()
    return AppSettings.from_dict(raw)


def save_settings(settings: AppSettings) -> None:
    SETTINGS_PATH.write_text(
        json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )


def quote_powershell_text(text: str) -> str:
    escaped = text.replace("`", "``").replace('"', '`"').replace("$", "`$")
    return f'"{escaped}"'


def sanitize_file_component(text: str, default: str = "video") -> str:
    cleaned = INVALID_FILE_CHARS.sub("_", text).strip().rstrip(".")
    return cleaned or default


def format_decimal(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def format_duration_text(value: float | None) -> str:
    if value is None:
        return ""
    if value < 0:
        value = 0.0
    total_ms = int(round(value * 1000))
    seconds, milliseconds = divmod(total_ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if milliseconds:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_count_text(value: int | None) -> str:
    return f"{value:,}" if value is not None else ""


def parse_timecode_to_seconds(raw: str) -> float | None:
    text = raw.strip()
    if not text:
        return None
    match = TIME_PROGRESS_RE.match(text)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = float(match.group(3))
        return (hours * 3600) + (minutes * 60) + seconds
    if ":" in text:
        parts = text.split(":")
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return (minutes * 60) + seconds
    return float(text)


def parse_fraction(raw: str) -> float | None:
    text = raw.strip()
    if not text:
        return None
    if "/" in text:
        left, right = text.split("/", 1)
        denominator = float(right)
        if denominator == 0:
            return None
        return float(left) / denominator
    return float(text)


def get_interval_seconds(settings: AppSettings) -> float | None:
    if settings.extract_mode == "10秒ごと":
        return 10.0
    if settings.extract_mode == "5秒ごと":
        return 5.0
    if settings.extract_mode == "1秒ごと":
        return 1.0
    if settings.extract_mode == "指定秒ごと":
        return settings.custom_seconds
    return None


def build_fps_expression(settings: AppSettings) -> str | None:
    interval = get_interval_seconds(settings)
    if interval is None:
        return None
    if interval <= 0:
        raise ValueError("指定秒ごとの秒数は 0 より大きい値を指定してください。")
    if interval == 1:
        return "fps=1"
    return f"fps=1/{format_decimal(interval)}"


def build_scale_expression(settings: AppSettings) -> str | None:
    if not settings.resize_enabled:
        return None
    width = max(0, settings.resize_width)
    height = max(0, settings.resize_height)
    if width <= 0 and height <= 0:
        raise ValueError("リサイズを有効にした場合は横幅か高さのどちらかを指定してください。")
    if settings.keep_aspect:
        if width > 0 and height > 0:
            return f"scale={width}:{height}:force_original_aspect_ratio=decrease"
        if width > 0:
            return f"scale={width}:-2"
        return f"scale=-2:{height}"
    width_text = str(width) if width > 0 else "-1"
    height_text = str(height) if height > 0 else "-1"
    return f"scale={width_text}:{height_text}"


def build_filter_expression(settings: AppSettings) -> str | None:
    filters: list[str] = []
    fps_expression = build_fps_expression(settings)
    if fps_expression:
        filters.append(fps_expression)
    scale_expression = build_scale_expression(settings)
    if scale_expression:
        filters.append(scale_expression)
    return ",".join(filters) if filters else None


def build_output_pattern(settings: AppSettings) -> str:
    file_name = f"{settings.base_name}_%0{settings.digits}d.{settings.image_format}"
    return str(Path(settings.output_folder) / file_name)


def build_preview_lines(settings: AppSettings) -> list[str]:
    lines: list[str] = []
    for index in (1, 2, 3):
        number = f"{index:0{settings.digits}d}"
        file_name = f"{settings.base_name}_{number}.{settings.image_format}"
        if settings.output_folder:
            lines.append(str(Path(settings.output_folder) / file_name))
        else:
            lines.append(file_name)
    return lines


def validate_single_settings(settings: AppSettings) -> None:
    if not settings.input_path:
        raise ValueError("入力動画ファイルを指定してください。")
    if not Path(settings.input_path).is_file():
        raise ValueError("入力動画ファイルが存在しません。")
    if not settings.output_folder:
        raise ValueError("単体出力フォルダを指定してください。")
    if not settings.base_name:
        raise ValueError("単体連番ベース名を入力してください。")
    if settings.use_ffmpeg_path:
        if not settings.ffmpeg_path:
            raise ValueError("ffmpeg パス指定を有効にした場合は、ffmpeg.exe のパスを入力してください。")
        if not Path(settings.ffmpeg_path).is_file():
            raise ValueError("指定された ffmpeg.exe が見つかりません。")
    build_filter_expression(settings)


def validate_batch_settings(settings: AppSettings) -> None:
    if not settings.output_root:
        raise ValueError("出力ルートフォルダを指定してください。")
    if not settings.file_name_pattern:
        raise ValueError("出力ファイル名パターンを入力してください。")
    validate_filename_pattern(settings.file_name_pattern)
    build_filter_expression(settings)
    if settings.use_ffmpeg_path:
        if not settings.ffmpeg_path:
            raise ValueError("ffmpeg パス指定を有効にした場合は、ffmpeg.exe のパスを入力してください。")
        if not Path(settings.ffmpeg_path).is_file():
            raise ValueError("指定された ffmpeg.exe が見つかりません。")


def validate_filename_pattern(pattern: str) -> None:
    allowed = {"video_name", "frame_no", "timestamp"}
    found = set(re.findall(r"{([^{}]+)}", pattern))
    unknown = sorted(found - allowed)
    if unknown:
        raise ValueError(f"出力ファイル名パターンに未対応のプレースホルダーがあります: {', '.join(unknown)}")
    if "{frame_no}" not in pattern and "{timestamp}" not in pattern:
        raise ValueError("出力ファイル名パターンには {frame_no} か {timestamp} のどちらかを含めてください。")


def build_command(settings: AppSettings) -> str:
    validate_single_settings(settings)
    filter_expression = build_filter_expression(settings)
    output_pattern = build_output_pattern(settings)

    parts: list[str] = []
    if settings.use_ffmpeg_path:
        parts.append(f"& {quote_powershell_text(settings.ffmpeg_path)}")
    else:
        parts.append("ffmpeg")

    if settings.overwrite:
        parts.append("-y")
    if settings.start_position:
        parts.extend(["-ss", quote_powershell_text(settings.start_position)])
    if settings.end_position:
        parts.extend(["-to", quote_powershell_text(settings.end_position)])
    elif settings.duration:
        parts.extend(["-t", quote_powershell_text(settings.duration)])

    parts.extend(["-i", quote_powershell_text(settings.input_path)])

    if filter_expression:
        parts.extend(["-vf", quote_powershell_text(filter_expression)])
    if settings.image_format == "jpg":
        parts.extend(["-q:v", str(settings.jpeg_quality)])

    parts.append(quote_powershell_text(output_pattern))

    command_lines: list[str] = []
    if settings.include_mkdir:
        command_lines.append(
            f'New-Item -ItemType Directory -Force -Path {quote_powershell_text(settings.output_folder)} | Out-Null'
        )
    command_lines.append(" ".join(parts))
    return WINDOWS_NEWLINE.join(command_lines)


def resolve_ffmpeg_path(settings: AppSettings) -> tuple[str | None, str]:
    if settings.use_ffmpeg_path:
        candidate = Path(settings.ffmpeg_path)
        if candidate.is_file():
            return str(candidate), f"ffmpeg を指定パスで確認しました: {candidate}"
        return None, "指定された ffmpeg.exe が見つかりません。"

    resolved = shutil.which("ffmpeg")
    if resolved:
        return resolved, f"PATH 上の ffmpeg を確認しました: {resolved}"
    return None, "ffmpeg が見つかりません。PATH へ追加するか、ffmpeg.exe のフルパス指定を有効にしてください。"


def resolve_ffprobe_path(ffmpeg_path: str | None) -> str | None:
    if ffmpeg_path:
        ffmpeg_candidate = Path(ffmpeg_path)
        sibling = ffmpeg_candidate.with_name("ffprobe.exe")
        if sibling.is_file():
            return str(sibling)
    return shutil.which("ffprobe")


def probe_video(input_path: str, ffprobe_path: str | None, ffmpeg_path: str | None = None) -> ProbeResult:
    if not ffprobe_path:
        if ffmpeg_path:
            return probe_video_with_ffmpeg(input_path, ffmpeg_path)
        return ProbeResult(error_message="ffprobe が見つからないため長さを取得できません。")
    try:
        result = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                input_path,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except Exception as exc:
        return ProbeResult(error_message=f"ffprobe の実行に失敗しました: {exc}")

    if result.returncode != 0:
        return ProbeResult(error_message=result.stderr.strip() or "ffprobe の解析に失敗しました。")

    try:
        raw = json.loads(result.stdout)
    except Exception as exc:
        return ProbeResult(error_message=f"ffprobe 出力の解析に失敗しました: {exc}")

    duration_seconds: float | None = None
    fps: float | None = None
    format_info = raw.get("format", {})
    if isinstance(format_info, dict):
        try:
            duration_seconds = float(format_info.get("duration"))
        except (TypeError, ValueError):
            duration_seconds = None

    streams = raw.get("streams", [])
    if isinstance(streams, list):
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            if stream.get("codec_type") != "video":
                continue
            fps = _probe_stream_fps(stream)
            break

    return ProbeResult(duration_seconds=duration_seconds, fps=fps)


def probe_video_with_ffmpeg(input_path: str, ffmpeg_path: str) -> ProbeResult:
    try:
        result = subprocess.run(
            [
                ffmpeg_path,
                "-hide_banner",
                "-ss",
                "0",
                "-i",
                input_path,
                "-frames:v",
                "1",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except Exception as exc:
        return ProbeResult(error_message=f"ffmpeg の解析に失敗しました: {exc}")

    stderr_text = result.stderr or ""
    duration_seconds: float | None = None
    fps: float | None = None

    duration_match = DURATION_LINE_RE.search(stderr_text)
    if duration_match:
        try:
            duration_seconds = parse_timecode_to_seconds(duration_match.group(1))
        except (TypeError, ValueError):
            duration_seconds = None

    fps_match = FPS_LINE_RE.search(stderr_text)
    if fps_match:
        try:
            fps = float(fps_match.group(1))
        except ValueError:
            fps = None

    if duration_seconds is None:
        message = stderr_text.strip().splitlines()[-1] if stderr_text.strip() else "動画長さを取得できませんでした。"
        return ProbeResult(error_message=message)
    return ProbeResult(duration_seconds=duration_seconds, fps=fps)


def _probe_stream_fps(stream: dict[str, Any]) -> float | None:
    for key in ("avg_frame_rate", "r_frame_rate"):
        value = stream.get(key)
        if not value:
            continue
        try:
            fps = parse_fraction(str(value))
        except (TypeError, ValueError):
            continue
        if fps and fps > 0:
            return fps
    return None


def compute_effective_duration(total_duration: float | None, settings: AppSettings) -> float | None:
    start_seconds = parse_timecode_to_seconds(settings.start_position) or 0.0
    if settings.end_position:
        end_seconds = parse_timecode_to_seconds(settings.end_position)
        if end_seconds is not None:
            return max(0.0, end_seconds - start_seconds)
    if settings.duration:
        duration_seconds = parse_timecode_to_seconds(settings.duration)
        if duration_seconds is not None:
            return max(0.0, duration_seconds)
    if total_duration is None:
        return None
    return max(0.0, total_duration - start_seconds)


def estimate_frame_count(duration_seconds: float | None, fps: float | None, settings: AppSettings) -> int | None:
    effective_duration = compute_effective_duration(duration_seconds, settings)
    if effective_duration is None or effective_duration <= 0:
        return None
    interval = get_interval_seconds(settings)
    if interval is not None:
        return max(1, int(math.ceil((effective_duration / interval) - 1e-9)))
    if fps and fps > 0:
        return max(1, int(round(effective_duration * fps)))
    return None


def normalize_path_key(path: Path | str) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def next_numbered_path(base_path: Path, reserved: set[str]) -> Path:
    if normalize_path_key(base_path) not in reserved and not base_path.exists():
        return base_path
    index = 1
    while True:
        candidate = base_path.parent / f"{base_path.name}_{index:03d}"
        if normalize_path_key(candidate) not in reserved and not candidate.exists():
            return candidate
        index += 1


def directory_has_any_output(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    try:
        next(path.iterdir())
        return True
    except StopIteration:
        return False


def plan_output_directory(
    input_path: str,
    output_root: Path,
    settings: AppSettings,
    reserved: set[str],
) -> PlannedOutput:
    base_dir_name = sanitize_file_component(f"{Path(input_path).stem}_frames", "video_frames")
    base_path = output_root / base_dir_name
    notes: list[str] = []
    candidate = base_path
    base_key = normalize_path_key(base_path)

    if base_key in reserved:
        candidate = next_numbered_path(base_path, reserved)
        notes.append("同一バッチ内で同名サブフォルダが衝突するため、連番フォルダを使用します。")
    elif base_path.exists() and settings.duplicate_subfolder_mode == "create_numbered_folder":
        candidate = next_numbered_path(base_path, reserved)
        if candidate != base_path:
            notes.append("既存の同名フォルダがあるため、連番フォルダを使用します。")

    candidate_key = normalize_path_key(candidate)
    has_existing_output = directory_has_any_output(candidate)

    if has_existing_output:
        if settings.existing_output_mode == "skip_existing":
            notes.append("既存出力があるためスキップ予定です。")
            reserved.add(candidate_key)
            return PlannedOutput(output_dir=candidate, will_skip=True, will_delete=False, notes=notes)
        if settings.existing_output_mode == "create_numbered_folder":
            numbered = next_numbered_path(base_path, reserved)
            if numbered != candidate:
                candidate = numbered
                candidate_key = normalize_path_key(candidate)
                notes.append("既存出力があるため、新しい連番フォルダへ出力します。")
        elif settings.existing_output_mode == "recreate_output":
            notes.append("既存出力を削除して再作成します。")
            reserved.add(candidate_key)
            return PlannedOutput(output_dir=candidate, will_skip=False, will_delete=True, notes=notes)

    reserved.add(candidate_key)
    return PlannedOutput(output_dir=candidate, will_skip=False, will_delete=False, notes=notes)


def build_batch_ffmpeg_args(
    settings: AppSettings,
    ffmpeg_path: str,
    input_path: str,
    output_pattern: str,
) -> list[str]:
    args = [ffmpeg_path, "-hide_banner"]
    args.append("-y" if settings.overwrite else "-n")
    if settings.start_position:
        args.extend(["-ss", settings.start_position])
    if settings.end_position:
        args.extend(["-to", settings.end_position])
    elif settings.duration:
        args.extend(["-t", settings.duration])
    args.extend(["-i", input_path])

    filter_expression = build_filter_expression(settings)
    if filter_expression:
        args.extend(["-vf", filter_expression])
    if settings.image_format == "jpg":
        args.extend(["-q:v", str(settings.jpeg_quality)])

    args.extend(["-progress", "pipe:1", "-nostats", output_pattern])
    return args


def render_commandline(args: list[str]) -> str:
    return subprocess.list2cmdline(args)


def compute_frame_timestamp_seconds(
    index: int,
    settings: AppSettings,
    fps: float | None,
) -> float | None:
    start_seconds = parse_timecode_to_seconds(settings.start_position) or 0.0
    interval = get_interval_seconds(settings)
    if interval is not None:
        return start_seconds + (index - 1) * interval
    if fps and fps > 0:
        return start_seconds + ((index - 1) / fps)
    return None


def format_timestamp_for_filename(seconds_value: float | None) -> str:
    if seconds_value is None:
        return "ts_unknown"
    total_ms = int(round(max(0.0, seconds_value) * 1000))
    seconds, milliseconds = divmod(total_ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}-{minutes:02d}-{seconds:02d}_{milliseconds:03d}"


def build_output_file_stem(
    pattern: str,
    video_name: str,
    frame_no: int,
    digits: int,
    timestamp_seconds: float | None,
) -> str:
    stem = pattern
    stem = stem.replace("{video_name}", video_name)
    stem = stem.replace("{frame_no}", f"{frame_no:0{digits}d}")
    stem = stem.replace("{timestamp}", format_timestamp_for_filename(timestamp_seconds))
    return sanitize_file_component(stem, "frame")


def unique_file_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    index = 1
    while True:
        candidate = path.with_name(f"{stem}_{index:03d}{suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def rename_extracted_files(
    output_dir: Path,
    settings: AppSettings,
    video_name: str,
    fps: float | None,
) -> int:
    pattern = f"__ffextract_tmp_*.{settings.image_format}"
    files = sorted(output_dir.glob(pattern))
    count = 0
    for index, file_path in enumerate(files, start=1):
        timestamp_seconds = compute_frame_timestamp_seconds(index, settings, fps)
        stem = build_output_file_stem(
            settings.file_name_pattern,
            video_name=video_name,
            frame_no=index,
            digits=settings.digits,
            timestamp_seconds=timestamp_seconds,
        )
        target_path = unique_file_path(output_dir / f"{stem}.{settings.image_format}")
        file_path.rename(target_path)
        count += 1
    return count


def count_output_images(output_dir: Path, image_format: str) -> int:
    return sum(1 for _ in output_dir.glob(f"*.{image_format}"))


def ensure_output_root_accessible(output_root: Path) -> tuple[bool, str]:
    if output_root.exists():
        if not output_root.is_dir():
            return False, "出力ルートがフォルダではありません。"
        if not os.access(output_root, os.W_OK):
            return False, "出力ルートに書き込みできません。"
        return True, "出力ルートへ書き込みできます。"

    current = output_root.parent
    while current and not current.exists():
        current = current.parent
    if not current:
        return False, "出力ルートの親フォルダを確認できません。"
    if not os.access(current, os.W_OK):
        return False, f"出力ルートの親フォルダへ書き込みできません: {current}"
    return True, f"出力ルートは未作成ですが、親フォルダへ書き込みできます: {current}"


def list_video_files_from_folder(folder_path: Path) -> list[str]:
    results: list[str] = []
    for file_path in folder_path.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in VIDEO_EXTENSIONS:
            results.append(str(file_path))
    return sorted(results, key=str.lower)


class SleepInhibitor:
    def __init__(self) -> None:
        self.active = False

    def enable(self) -> None:
        if self.active:
            return
        try:
            result = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        except Exception:
            result = 0
        self.active = bool(result)

    def disable(self) -> None:
        if not self.active:
            return
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        finally:
            self.active = False


class DropFilesHook:
    WM_DROPFILES = 0x0233
    GWL_WNDPROC = -4

    def __init__(self, widget: tk.Misc, callback: callable[[list[str]], None]) -> None:
        self.widget = widget
        self.callback = callback
        self.hwnd = widget.winfo_id()
        self.user32 = ctypes.windll.user32
        self.shell32 = ctypes.windll.shell32
        long_ptr = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
        self._set_window_long = self.user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else self.user32.SetWindowLongW
        self._call_window_proc = self.user32.CallWindowProcW
        self._set_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int, long_ptr]
        self._set_window_long.restype = long_ptr
        self._call_window_proc.argtypes = [long_ptr, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        self._call_window_proc.restype = long_ptr
        wndproc_type = ctypes.WINFUNCTYPE(long_ptr, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)
        self._callback_type = wndproc_type
        self._wndproc = self._callback_type(self._window_proc)
        self._old_proc = self._set_window_long(self.hwnd, self.GWL_WNDPROC, self._wndproc)
        self.shell32.DragAcceptFiles(self.hwnd, True)

    def close(self) -> None:
        try:
            self.shell32.DragAcceptFiles(self.hwnd, False)
            if self._old_proc:
                self._set_window_long(self.hwnd, self.GWL_WNDPROC, self._old_proc)
        except Exception:
            pass

    def _window_proc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == self.WM_DROPFILES:
            paths = self._extract_paths(wparam)
            if paths:
                self.callback(paths)
            return 0
        return self._call_window_proc(self._old_proc, hwnd, msg, wparam, lparam)

    def _extract_paths(self, handle: int) -> list[str]:
        count = self.shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
        results: list[str] = []
        try:
            for index in range(count):
                length = self.shell32.DragQueryFileW(handle, index, None, 0) + 1
                buffer = ctypes.create_unicode_buffer(length)
                self.shell32.DragQueryFileW(handle, index, buffer, length)
                results.append(buffer.value)
        finally:
            self.shell32.DragFinish(handle)
        return results


class FfmpegFrameExtractCommandGui:
    def __init__(self) -> None:
        self.loaded_settings = load_settings()
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry(f"{self.loaded_settings.window_width}x{self.loaded_settings.window_height}")
        self.root.minsize(1200, 860)

        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("vista")
        except tk.TclError:
            pass
        self.style.configure("Treeview", rowheight=26)
        self.style.configure("Treeview.Heading", padding=(6, 6))

        self.input_path_var = tk.StringVar()
        self.output_folder_var = tk.StringVar()
        self.output_root_var = tk.StringVar()
        self.base_name_var = tk.StringVar(value="frame")
        self.file_name_pattern_var = tk.StringVar(value="{video_name}_{frame_no}")
        self.digits_var = tk.IntVar(value=6)
        self.image_format_var = tk.StringVar(value="jpg")
        self.jpeg_quality_var = tk.IntVar(value=2)
        self.extract_mode_var = tk.StringVar(value="10秒ごと")
        self.custom_seconds_var = tk.StringVar(value="10")
        self.start_position_var = tk.StringVar()
        self.end_position_var = tk.StringVar()
        self.duration_var = tk.StringVar()
        self.resize_enabled_var = tk.BooleanVar(value=False)
        self.resize_width_var = tk.IntVar(value=0)
        self.resize_height_var = tk.IntVar(value=0)
        self.keep_aspect_var = tk.BooleanVar(value=True)
        self.include_mkdir_var = tk.BooleanVar(value=True)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.use_ffmpeg_path_var = tk.BooleanVar(value=False)
        self.ffmpeg_path_var = tk.StringVar(value="ffmpeg")
        self.duplicate_subfolder_mode_var = tk.StringVar(value=DUPLICATE_SUBFOLDER_MODE_LABELS["create_numbered_folder"])
        self.existing_output_mode_var = tk.StringVar(value=EXISTING_OUTPUT_MODE_LABELS["create_numbered_folder"])
        self.prevent_sleep_var = tk.BooleanVar(value=True)
        self.after_complete_action_var = tk.StringVar(value=AFTER_COMPLETE_ACTION_LABELS["none"])

        self.status_var = tk.StringVar(value="準備完了")
        self.current_video_var = tk.StringVar(value="現在処理中: -")
        self.overall_count_var = tk.StringVar(value="処理済み本数: 0 / 0")
        self.output_count_var = tk.StringVar(value="出力枚数: 0")

        self.queue_items: list[VideoQueueItem] = []
        self.next_queue_id = 1

        self.preview_text: tk.Text
        self.command_text: tk.Text
        self.log_text: tk.Text
        self.queue_tree: ttk.Treeview
        self.jpeg_quality_spinbox: ttk.Spinbox
        self.custom_seconds_spinbox: ttk.Spinbox
        self.resize_width_spinbox: ttk.Spinbox
        self.resize_height_spinbox: ttk.Spinbox
        self.ffmpeg_path_entry: ttk.Entry
        self.ffmpeg_browse_button: ttk.Button
        self.pause_button: ttk.Button
        self.resume_button: ttk.Button
        self.cancel_button: ttk.Button
        self.run_button: ttk.Button
        self.dry_run_button: ttk.Button

        self.overall_progress = ttk.Progressbar(self.root, mode="determinate")
        self.current_progress = ttk.Progressbar(self.root, mode="determinate")

        self.ui_queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self.sleep_inhibitor = SleepInhibitor()
        self.drop_hook: DropFilesHook | None = None

        self.batch_thread: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.pause_requested = False
        self.batch_paused = False
        self.current_process: subprocess.Popen[str] | None = None
        self.current_process_lock = threading.Lock()
        self.last_log_path: Path | None = None
        self.last_summary_paths: tuple[Path, Path] | None = None
        self.current_run_output_root: Path | None = None

        self._build_layout()
        self._bind_events()
        self._apply_settings(self.loaded_settings)
        self._restore_column_widths()
        self._install_context_menus()
        self._install_drag_and_drop()
        self.update_option_states()
        self.update_preview()
        self._refresh_queue_plans()
        self._refresh_queue_tree()
        self._update_batch_button_states()
        self.root.after(120, self._poll_ui_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        for row in (0, 1, 2, 3, 4):
            self.root.rowconfigure(row, weight=0)
        self.root.rowconfigure(5, weight=1)

        queue_group = ttk.LabelFrame(self.root, text="入力動画キュー", padding=10)
        queue_group.grid(row=0, column=0, padx=10, pady=(10, 6), sticky="nsew")
        queue_group.columnconfigure(0, weight=1)
        queue_group.rowconfigure(0, weight=1)

        self.queue_tree = ttk.Treeview(
            queue_group,
            columns=TREE_COLUMNS,
            show="headings",
            selectmode="extended",
            height=10,
        )
        for column in TREE_COLUMNS:
            self.queue_tree.heading(column, text=TREE_HEADINGS[column])
            self.queue_tree.column(column, width=DEFAULT_COLUMN_WIDTHS[column], anchor="w")
        self.queue_tree.column("enabled", anchor="center")
        self.queue_tree.column("duration", anchor="center")
        self.queue_tree.column("estimated", anchor="e")
        self.queue_tree.column("status", anchor="center")
        self.queue_tree.column("actual_count", anchor="e")
        self.queue_tree.grid(row=0, column=0, sticky="nsew")
        queue_y_scroll = ttk.Scrollbar(queue_group, orient="vertical", command=self.queue_tree.yview)
        queue_y_scroll.grid(row=0, column=1, sticky="ns")
        queue_x_scroll = ttk.Scrollbar(queue_group, orient="horizontal", command=self.queue_tree.xview)
        queue_x_scroll.grid(row=1, column=0, sticky="ew")
        self.queue_tree.configure(yscrollcommand=queue_y_scroll.set, xscrollcommand=queue_x_scroll.set)
        self.queue_tree.tag_configure("status_running", background="#fff8d5")
        self.queue_tree.tag_configure("status_failed", background="#ffe5e5")
        self.queue_tree.tag_configure("status_complete", background="#e7f6e7")
        self.queue_tree.tag_configure("status_skipped", background="#eef1f5")
        self.queue_tree.tag_configure("status_cancelled", background="#f5eef8")

        queue_buttons = ttk.Frame(queue_group)
        queue_buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(queue_buttons, text="動画ファイル追加", command=self.add_video_files).pack(side="left")
        ttk.Button(queue_buttons, text="フォルダから一括追加", command=self.add_video_folder).pack(side="left", padx=(8, 0))
        ttk.Button(queue_buttons, text="選択行を削除", command=self.remove_selected_rows).pack(side="left", padx=(16, 0))
        ttk.Button(queue_buttons, text="一覧をクリア", command=self.clear_queue).pack(side="left", padx=(8, 0))
        ttk.Button(queue_buttons, text="上へ", command=lambda: self.move_selected_rows(-1)).pack(side="left", padx=(16, 0))
        ttk.Button(queue_buttons, text="下へ", command=lambda: self.move_selected_rows(1)).pack(side="left", padx=(8, 0))
        ttk.Button(queue_buttons, text="重複削除", command=self.remove_duplicate_rows).pack(side="left", padx=(16, 0))
        ttk.Button(queue_buttons, text="存在しないファイルを除外", command=self.remove_missing_rows).pack(side="left", padx=(8, 0))
        ttk.Button(queue_buttons, text="選択反転", command=self.toggle_selected_flags).pack(side="left", padx=(16, 0))
        ttk.Label(
            queue_buttons,
            text="動画ファイルやフォルダをこの画面へドラッグ＆ドロップして追加できます。",
        ).pack(side="right")

        settings_group = ttk.LabelFrame(self.root, text="出力ルートと抽出設定", padding=10)
        settings_group.grid(row=1, column=0, padx=10, pady=6, sticky="nsew")
        settings_group.columnconfigure(1, weight=1)
        settings_group.columnconfigure(3, weight=1)

        ttk.Label(settings_group, text="入力動画ファイル").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(settings_group, textvariable=self.input_path_var).grid(row=0, column=1, sticky="ew", padx=(10, 8), pady=4)
        ttk.Button(settings_group, text="参照...", command=self.choose_input_file).grid(row=0, column=2, sticky="ew", pady=4)
        ttk.Button(settings_group, text="キューへ追加", command=self.add_current_input_to_queue).grid(row=0, column=3, sticky="ew", padx=(8, 0), pady=4)

        ttk.Label(settings_group, text="単体出力フォルダ").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(settings_group, textvariable=self.output_folder_var).grid(row=1, column=1, sticky="ew", padx=(10, 8), pady=4)
        ttk.Button(settings_group, text="参照...", command=self.choose_output_folder).grid(row=1, column=2, sticky="ew", pady=4)
        ttk.Label(settings_group, text="単体モードだけで使います。").grid(row=1, column=3, sticky="w", padx=(8, 0), pady=4)

        ttk.Label(settings_group, text="出力ルートフォルダ").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(settings_group, textvariable=self.output_root_var).grid(row=2, column=1, sticky="ew", padx=(10, 8), pady=4)
        ttk.Button(settings_group, text="参照...", command=self.choose_output_root).grid(row=2, column=2, sticky="ew", pady=4)
        ttk.Label(settings_group, text="複数動画バッチの親フォルダです。").grid(row=2, column=3, sticky="w", padx=(8, 0), pady=4)

        ttk.Label(settings_group, text="単体連番ベース名").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(settings_group, textvariable=self.base_name_var).grid(row=3, column=1, sticky="ew", padx=(10, 8), pady=4)
        ttk.Label(settings_group, text="既存の単発コマンド生成に使います。").grid(row=3, column=2, columnspan=2, sticky="w", pady=4)

        ttk.Label(settings_group, text="出力ファイル名パターン").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(settings_group, textvariable=self.file_name_pattern_var).grid(row=4, column=1, sticky="ew", padx=(10, 8), pady=4)
        ttk.Label(
            settings_group,
            text="例: {video_name}_{frame_no} / {video_name}_{timestamp}_{frame_no}",
        ).grid(row=4, column=2, columnspan=2, sticky="w", pady=4)

        digits_row = ttk.Frame(settings_group)
        digits_row.grid(row=5, column=1, sticky="w", padx=(10, 8), pady=4)
        ttk.Label(settings_group, text="連番桁数").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Spinbox(digits_row, from_=1, to=10, width=6, textvariable=self.digits_var).pack(side="left")
        ttk.Label(digits_row, text="例: 6 -> 000001").pack(side="left", padx=(8, 0))

        format_row = ttk.Frame(settings_group)
        format_row.grid(row=5, column=2, columnspan=2, sticky="w", pady=4)
        ttk.Label(format_row, text="画像形式").pack(side="left")
        ttk.Combobox(format_row, width=8, state="readonly", values=IMAGE_FORMATS, textvariable=self.image_format_var).pack(side="left", padx=(8, 8))
        ttk.Label(format_row, text="JPG 品質").pack(side="left")
        self.jpeg_quality_spinbox = ttk.Spinbox(format_row, from_=1, to=31, width=6, textvariable=self.jpeg_quality_var)
        self.jpeg_quality_spinbox.pack(side="left", padx=(8, 0))
        ttk.Label(format_row, text="q:v は小さいほど高画質").pack(side="left", padx=(8, 0))

        extract_row = ttk.Frame(settings_group)
        extract_row.grid(row=6, column=1, columnspan=3, sticky="w", padx=(10, 0), pady=4)
        ttk.Label(settings_group, text="抽出方式").grid(row=6, column=0, sticky="w", pady=4)
        ttk.Combobox(extract_row, width=12, state="readonly", values=EXTRACT_MODES, textvariable=self.extract_mode_var).pack(side="left")
        ttk.Label(extract_row, text="指定秒").pack(side="left", padx=(16, 6))
        self.custom_seconds_spinbox = ttk.Spinbox(
            extract_row,
            from_=0.1,
            to=86400,
            increment=0.1,
            width=8,
            textvariable=self.custom_seconds_var,
        )
        self.custom_seconds_spinbox.pack(side="left")
        ttk.Label(extract_row, text="秒").pack(side="left", padx=(8, 20))
        ttk.Label(extract_row, text="開始位置").pack(side="left")
        ttk.Entry(extract_row, width=12, textvariable=self.start_position_var).pack(side="left", padx=(8, 8))
        ttk.Label(extract_row, text="終了位置").pack(side="left")
        ttk.Entry(extract_row, width=12, textvariable=self.end_position_var).pack(side="left", padx=(8, 8))
        ttk.Label(extract_row, text="抽出時間(旧互換)").pack(side="left")
        ttk.Entry(extract_row, width=12, textvariable=self.duration_var).pack(side="left", padx=(8, 0))

        resize_row = ttk.Frame(settings_group)
        resize_row.grid(row=7, column=1, columnspan=3, sticky="w", padx=(10, 0), pady=4)
        ttk.Label(settings_group, text="リサイズ").grid(row=7, column=0, sticky="w", pady=4)
        ttk.Checkbutton(resize_row, text="有効にする", variable=self.resize_enabled_var).pack(side="left")
        ttk.Label(resize_row, text="横幅").pack(side="left", padx=(16, 6))
        self.resize_width_spinbox = ttk.Spinbox(resize_row, from_=0, to=16384, width=8, textvariable=self.resize_width_var)
        self.resize_width_spinbox.pack(side="left")
        ttk.Label(resize_row, text="高さ").pack(side="left", padx=(16, 6))
        self.resize_height_spinbox = ttk.Spinbox(resize_row, from_=0, to=16384, width=8, textvariable=self.resize_height_var)
        self.resize_height_spinbox.pack(side="left")
        ttk.Checkbutton(resize_row, text="アスペクト比を維持する", variable=self.keep_aspect_var).pack(side="left", padx=(16, 0))

        duplicate_row = ttk.Frame(settings_group)
        duplicate_row.grid(row=8, column=1, sticky="ew", padx=(10, 8), pady=4)
        ttk.Label(settings_group, text="サブフォルダ重複時").grid(row=8, column=0, sticky="w", pady=4)
        ttk.Combobox(
            duplicate_row,
            width=28,
            state="readonly",
            values=list(DUPLICATE_SUBFOLDER_MODE_LABELS.values()),
            textvariable=self.duplicate_subfolder_mode_var,
        ).pack(side="left")

        existing_row = ttk.Frame(settings_group)
        existing_row.grid(row=8, column=2, columnspan=2, sticky="ew", pady=4)
        ttk.Label(existing_row, text="既存出力の扱い").pack(side="left")
        ttk.Combobox(
            existing_row,
            width=30,
            state="readonly",
            values=list(EXISTING_OUTPUT_MODE_LABELS.values()),
            textvariable=self.existing_output_mode_var,
        ).pack(side="left", padx=(8, 0))

        options_row = ttk.Frame(settings_group)
        options_row.grid(row=9, column=1, columnspan=3, sticky="w", padx=(10, 0), pady=4)
        ttk.Label(settings_group, text="オプション").grid(row=9, column=0, sticky="nw", pady=4)
        ttk.Checkbutton(options_row, text="出力フォルダ作成コマンドを付ける", variable=self.include_mkdir_var).pack(side="left")
        ttk.Checkbutton(options_row, text="上書き -y を付ける", variable=self.overwrite_var).pack(side="left", padx=(16, 0))
        ttk.Checkbutton(options_row, text="実行中は PC スリープを抑止する", variable=self.prevent_sleep_var).pack(side="left", padx=(16, 0))

        ffmpeg_row = ttk.Frame(settings_group)
        ffmpeg_row.grid(row=10, column=1, columnspan=3, sticky="ew", padx=(10, 0), pady=4)
        ffmpeg_row.columnconfigure(1, weight=1)
        ttk.Label(settings_group, text="ffmpeg パス").grid(row=10, column=0, sticky="w", pady=4)
        ttk.Checkbutton(ffmpeg_row, text="ffmpeg.exe のフルパスを指定する", variable=self.use_ffmpeg_path_var).grid(row=0, column=0, sticky="w")
        self.ffmpeg_path_entry = ttk.Entry(ffmpeg_row, textvariable=self.ffmpeg_path_var)
        self.ffmpeg_path_entry.grid(row=0, column=1, sticky="ew", padx=(10, 8))
        self.ffmpeg_browse_button = ttk.Button(ffmpeg_row, text="参照...", command=self.choose_ffmpeg_file)
        self.ffmpeg_browse_button.grid(row=0, column=2, sticky="ew")

        after_action_row = ttk.Frame(settings_group)
        after_action_row.grid(row=11, column=1, columnspan=3, sticky="w", padx=(10, 0), pady=4)
        ttk.Label(settings_group, text="完了後アクション").grid(row=11, column=0, sticky="w", pady=4)
        ttk.Combobox(
            after_action_row,
            width=24,
            state="readonly",
            values=list(AFTER_COMPLETE_ACTION_LABELS.values()),
            textvariable=self.after_complete_action_var,
        ).pack(side="left")
        ttk.Label(after_action_row, text="シャットダウン / スリープは実行前に確認が出ます。").pack(side="left", padx=(8, 0))

        preview_group = ttk.LabelFrame(self.root, text="単体モードのファイル名プレビュー", padding=10)
        preview_group.grid(row=2, column=0, padx=10, pady=6, sticky="nsew")
        preview_group.columnconfigure(0, weight=1)
        preview_group.rowconfigure(0, weight=1)
        self.preview_text = tk.Text(preview_group, height=4, wrap="none", font=("Consolas", 10))
        self.preview_text.grid(row=0, column=0, sticky="nsew")
        preview_scroll = ttk.Scrollbar(preview_group, orient="vertical", command=self.preview_text.yview)
        preview_scroll.grid(row=0, column=1, sticky="ns")
        self.preview_text.configure(yscrollcommand=preview_scroll.set)

        command_group = ttk.LabelFrame(self.root, text="単体モードの生成コマンド", padding=10)
        command_group.grid(row=3, column=0, padx=10, pady=6, sticky="nsew")
        command_group.columnconfigure(0, weight=1)
        command_group.rowconfigure(1, weight=1)
        ttk.Label(command_group, text="PowerShell にそのまま貼り付けて実行できる形式で出力します。").grid(
            row=0,
            column=0,
            sticky="w",
            pady=(0, 8),
        )
        self.command_text = tk.Text(command_group, height=10, wrap="none", font=("Consolas", 10))
        self.command_text.grid(row=1, column=0, sticky="nsew")
        command_y_scroll = ttk.Scrollbar(command_group, orient="vertical", command=self.command_text.yview)
        command_y_scroll.grid(row=1, column=1, sticky="ns")
        command_x_scroll = ttk.Scrollbar(command_group, orient="horizontal", command=self.command_text.xview)
        command_x_scroll.grid(row=2, column=0, sticky="ew")
        self.command_text.configure(yscrollcommand=command_y_scroll.set, xscrollcommand=command_x_scroll.set)

        control_group = ttk.LabelFrame(self.root, text="操作と進捗", padding=10)
        control_group.grid(row=4, column=0, padx=10, pady=6, sticky="nsew")
        control_group.columnconfigure(0, weight=1)
        control_group.columnconfigure(1, weight=1)

        single_button_row = ttk.Frame(control_group)
        single_button_row.grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(single_button_row, text="単体モード").pack(side="left")
        ttk.Button(single_button_row, text="コマンド生成", command=self.generate_command).pack(side="left", padx=(12, 0))
        ttk.Button(single_button_row, text="コピー", command=self.copy_command).pack(side="left", padx=(8, 0))
        ttk.Button(single_button_row, text="生成してコピー", command=self.generate_and_copy).pack(side="left", padx=(8, 0))
        ttk.Button(single_button_row, text="実行", command=self.execute_command).pack(side="left", padx=(8, 0))
        ttk.Button(single_button_row, text="クリア", command=self.clear_form).pack(side="left", padx=(8, 0))

        batch_button_row = ttk.Frame(control_group)
        batch_button_row.grid(row=0, column=1, sticky="e", pady=(0, 8))
        ttk.Label(batch_button_row, text="バッチモード").pack(side="left")
        self.dry_run_button = ttk.Button(batch_button_row, text="ドライラン", command=self.run_dry_run)
        self.dry_run_button.pack(side="left", padx=(12, 0))
        self.run_button = ttk.Button(batch_button_row, text="一括実行", command=self.start_batch_run)
        self.run_button.pack(side="left", padx=(8, 0))
        self.pause_button = ttk.Button(batch_button_row, text="一時停止", command=self.request_pause)
        self.pause_button.pack(side="left", padx=(8, 0))
        self.resume_button = ttk.Button(batch_button_row, text="再開", command=self.resume_batch_run)
        self.resume_button.pack(side="left", padx=(8, 0))
        self.cancel_button = ttk.Button(batch_button_row, text="キャンセル", command=self.cancel_batch_run)
        self.cancel_button.pack(side="left", padx=(8, 0))
        ttk.Button(batch_button_row, text="出力フォルダを開く", command=self.open_output_folder).pack(side="left", padx=(8, 0))
        ttk.Button(batch_button_row, text="ログ保存", command=self.save_log_to_file).pack(side="left", padx=(8, 0))
        ttk.Button(batch_button_row, text="ジョブ保存", command=self.save_job_file).pack(side="left", padx=(8, 0))
        ttk.Button(batch_button_row, text="ジョブ読込", command=self.load_job_file).pack(side="left", padx=(8, 0))

        ttk.Label(control_group, textvariable=self.current_video_var).grid(row=1, column=0, sticky="w")
        ttk.Label(control_group, textvariable=self.overall_count_var).grid(row=1, column=1, sticky="e")
        self.overall_progress.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        ttk.Label(control_group, textvariable=self.output_count_var).grid(row=3, column=0, sticky="w")
        ttk.Label(control_group, textvariable=self.status_var).grid(row=3, column=1, sticky="e")
        self.current_progress.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        log_group = ttk.LabelFrame(self.root, text="進捗とログ", padding=10)
        log_group.grid(row=5, column=0, padx=10, pady=(6, 10), sticky="nsew")
        log_group.columnconfigure(0, weight=1)
        log_group.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_group, wrap="none", font=("Consolas", 10))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.tag_configure("error", foreground="#c00000")
        self.log_text.tag_configure("success", foreground="#1f7a1f")
        self.log_text.tag_configure("info", foreground="#1f1f1f")
        log_y_scroll = ttk.Scrollbar(log_group, orient="vertical", command=self.log_text.yview)
        log_y_scroll.grid(row=0, column=1, sticky="ns")
        log_x_scroll = ttk.Scrollbar(log_group, orient="horizontal", command=self.log_text.xview)
        log_x_scroll.grid(row=1, column=0, sticky="ew")
        self.log_text.configure(yscrollcommand=log_y_scroll.set, xscrollcommand=log_x_scroll.set)

    def _bind_events(self) -> None:
        tracked_vars = [
            self.input_path_var,
            self.output_folder_var,
            self.base_name_var,
            self.digits_var,
            self.image_format_var,
            self.extract_mode_var,
            self.custom_seconds_var,
            self.start_position_var,
            self.end_position_var,
            self.duration_var,
            self.resize_enabled_var,
            self.resize_width_var,
            self.resize_height_var,
            self.keep_aspect_var,
            self.use_ffmpeg_path_var,
            self.ffmpeg_path_var,
            self.output_root_var,
            self.file_name_pattern_var,
            self.duplicate_subfolder_mode_var,
            self.existing_output_mode_var,
        ]
        for variable in tracked_vars:
            variable.trace_add("write", self._on_settings_changed)

        self.queue_tree.bind("<Button-1>", self._on_tree_left_click, add="+")
        self.queue_tree.bind("<Double-1>", self._on_tree_double_click, add="+")
        self.queue_tree.bind("<space>", self._on_tree_space_key, add="+")

    def _apply_settings(self, settings: AppSettings) -> None:
        self.input_path_var.set(settings.input_path)
        self.output_folder_var.set(settings.output_folder)
        self.output_root_var.set(settings.output_root)
        self.base_name_var.set(settings.base_name)
        self.file_name_pattern_var.set(settings.file_name_pattern)
        self.digits_var.set(settings.digits)
        self.image_format_var.set(settings.image_format)
        self.jpeg_quality_var.set(settings.jpeg_quality)
        self.extract_mode_var.set(settings.extract_mode)
        self.custom_seconds_var.set(format_decimal(settings.custom_seconds))
        self.start_position_var.set(settings.start_position)
        self.end_position_var.set(settings.end_position)
        self.duration_var.set(settings.duration)
        self.resize_enabled_var.set(settings.resize_enabled)
        self.resize_width_var.set(settings.resize_width)
        self.resize_height_var.set(settings.resize_height)
        self.keep_aspect_var.set(settings.keep_aspect)
        self.include_mkdir_var.set(settings.include_mkdir)
        self.overwrite_var.set(settings.overwrite)
        self.use_ffmpeg_path_var.set(settings.use_ffmpeg_path)
        self.ffmpeg_path_var.set(settings.ffmpeg_path)
        self.duplicate_subfolder_mode_var.set(self._mode_label(settings.duplicate_subfolder_mode, DUPLICATE_SUBFOLDER_MODE_LABELS))
        self.existing_output_mode_var.set(self._mode_label(settings.existing_output_mode, EXISTING_OUTPUT_MODE_LABELS))
        self.prevent_sleep_var.set(settings.prevent_sleep)
        self.after_complete_action_var.set(self._mode_label(settings.after_complete_action, AFTER_COMPLETE_ACTION_LABELS))

    def collect_settings(self) -> AppSettings:
        width = max(self.root.winfo_width(), 1200)
        height = max(self.root.winfo_height(), 860)
        history = self._build_input_video_history()
        return AppSettings(
            input_path=self.input_path_var.get().strip(),
            output_folder=self.output_folder_var.get().strip(),
            output_root=self.output_root_var.get().strip(),
            base_name=self.base_name_var.get().strip() or "frame",
            file_name_pattern=self.file_name_pattern_var.get().strip() or "{video_name}_{frame_no}",
            digits=_clamp(_safe_int(self.digits_var.get(), 6), 1, 10),
            image_format=_safe_choice(self.image_format_var.get(), IMAGE_FORMATS, "jpg"),
            jpeg_quality=_clamp(_safe_int(self.jpeg_quality_var.get(), 2), 1, 31),
            extract_mode=_safe_choice(self.extract_mode_var.get(), EXTRACT_MODES, "10秒ごと"),
            custom_seconds=max(_safe_float(self.custom_seconds_var.get(), 0.1), 0.001),
            start_position=self.start_position_var.get().strip(),
            end_position=self.end_position_var.get().strip(),
            duration=self.duration_var.get().strip(),
            resize_enabled=self.resize_enabled_var.get(),
            resize_width=max(0, _safe_int(self.resize_width_var.get(), 0)),
            resize_height=max(0, _safe_int(self.resize_height_var.get(), 0)),
            keep_aspect=self.keep_aspect_var.get(),
            include_mkdir=self.include_mkdir_var.get(),
            overwrite=self.overwrite_var.get(),
            use_ffmpeg_path=self.use_ffmpeg_path_var.get(),
            ffmpeg_path=self.ffmpeg_path_var.get().strip(),
            duplicate_subfolder_mode=self._mode_key(self.duplicate_subfolder_mode_var.get(), DUPLICATE_SUBFOLDER_MODE_LABELS),
            existing_output_mode=self._mode_key(self.existing_output_mode_var.get(), EXISTING_OUTPUT_MODE_LABELS),
            prevent_sleep=self.prevent_sleep_var.get(),
            after_complete_action=self._mode_key(self.after_complete_action_var.get(), AFTER_COMPLETE_ACTION_LABELS),
            input_video_history=history,
            window_width=width,
            window_height=height,
            column_widths=self._capture_column_widths(),
        )

    def _build_input_video_history(self) -> list[str]:
        history: list[str] = []
        if self.input_path_var.get().strip():
            history.append(self.input_path_var.get().strip())
        for item in self.queue_items:
            history.append(item.input_path)
        existing = self.loaded_settings.input_video_history if self.loaded_settings else []
        history.extend(existing)
        return _unique_strings(history)[:100]

    def _restore_column_widths(self) -> None:
        for key, width in self.loaded_settings.column_widths.items():
            if key in TREE_COLUMNS:
                self.queue_tree.column(key, width=width)

    def _capture_column_widths(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for key in TREE_COLUMNS:
            result[key] = _clamp(_safe_int(self.queue_tree.column(key, "width"), DEFAULT_COLUMN_WIDTHS[key]), 40, 1200)
        return result

    def _on_settings_changed(self, *_args: object) -> None:
        self.update_option_states()
        self.update_preview()
        self._refresh_queue_plans()
        self._refresh_queue_tree()

    def update_option_states(self) -> None:
        jpeg_state = "normal" if self.image_format_var.get() == "jpg" else "disabled"
        custom_state = "normal" if self.extract_mode_var.get() == "指定秒ごと" else "disabled"
        ffmpeg_state = "normal" if self.use_ffmpeg_path_var.get() else "disabled"
        resize_state = "normal" if self.resize_enabled_var.get() else "disabled"

        self.jpeg_quality_spinbox.configure(state=jpeg_state)
        self.custom_seconds_spinbox.configure(state=custom_state)
        self.ffmpeg_path_entry.configure(state=ffmpeg_state)
        self.ffmpeg_browse_button.configure(state=ffmpeg_state)
        self.resize_width_spinbox.configure(state=resize_state)
        self.resize_height_spinbox.configure(state=resize_state)

    def update_preview(self) -> None:
        settings = self.collect_settings()
        lines = build_preview_lines(settings)
        self._replace_text(self.preview_text, WINDOWS_NEWLINE.join(lines), readonly=True)

    def _install_context_menus(self) -> None:
        self.root.bind_class("Entry", "<Button-3>", self._show_entry_context_menu, add="+")
        self.root.bind_class("TEntry", "<Button-3>", self._show_entry_context_menu, add="+")
        self.root.bind_class("TCombobox", "<Button-3>", self._show_entry_context_menu, add="+")
        self.root.bind_class("TSpinbox", "<Button-3>", self._show_entry_context_menu, add="+")
        self.root.bind_class("Text", "<Button-3>", self._show_text_context_menu, add="+")
        self.root.bind_class("Treeview", "<Button-3>", self._show_tree_context_menu, add="+")

    def _install_drag_and_drop(self) -> None:
        try:
            self.root.update_idletasks()
            self.drop_hook = DropFilesHook(self.root, self._handle_dropped_paths)
        except Exception as exc:
            self._append_log(f"ドラッグ＆ドロップ登録に失敗しました: {exc}", tag="error")

    def choose_input_file(self) -> None:
        initial_dir = self._existing_parent_directory(self.input_path_var.get()) or self._existing_directory(self.output_folder_var.get())
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="入力動画ファイルを選択",
            filetypes=VIDEO_FILETYPES,
            initialdir=initial_dir,
        )
        if selected:
            self.input_path_var.set(str(Path(selected)))

    def choose_output_folder(self) -> None:
        initial_dir = self._existing_directory(self.output_folder_var.get()) or self._existing_parent_directory(self.input_path_var.get())
        selected = filedialog.askdirectory(
            parent=self.root,
            title="単体出力フォルダを選択してください",
            initialdir=initial_dir,
            mustexist=False,
        )
        if selected:
            self.output_folder_var.set(str(Path(selected)))

    def choose_output_root(self) -> None:
        initial_dir = self._existing_directory(self.output_root_var.get()) or self._existing_directory(self.output_folder_var.get())
        selected = filedialog.askdirectory(
            parent=self.root,
            title="バッチ出力ルートフォルダを選択してください",
            initialdir=initial_dir,
            mustexist=False,
        )
        if selected:
            self.output_root_var.set(str(Path(selected)))

    def choose_ffmpeg_file(self) -> None:
        initial_dir = self._existing_parent_directory(self.ffmpeg_path_var.get())
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="ffmpeg.exe を選択",
            filetypes=FFMPEG_FILETYPES,
            initialdir=initial_dir,
        )
        if selected:
            self.ffmpeg_path_var.set(str(Path(selected)))

    def add_current_input_to_queue(self) -> None:
        raw_path = self.input_path_var.get().strip()
        if not raw_path:
            messagebox.showwarning("キュー追加", "入力動画ファイルを指定してください。", parent=self.root)
            return
        self._add_paths_to_queue([raw_path])

    def add_video_files(self) -> None:
        initial_dir = self._existing_parent_directory(self.input_path_var.get()) or self._existing_directory(self.output_root_var.get())
        selected = filedialog.askopenfilenames(
            parent=self.root,
            title="動画ファイルを選択",
            filetypes=VIDEO_FILETYPES,
            initialdir=initial_dir,
        )
        if selected:
            self._add_paths_to_queue(list(selected))

    def add_video_folder(self) -> None:
        initial_dir = self._existing_directory(self.output_root_var.get()) or self._existing_parent_directory(self.input_path_var.get())
        selected = filedialog.askdirectory(
            parent=self.root,
            title="動画フォルダを選択してください",
            initialdir=initial_dir,
            mustexist=True,
        )
        if not selected:
            return
        paths = list_video_files_from_folder(Path(selected))
        if not paths:
            messagebox.showinfo("フォルダ追加", "対象動画が見つかりませんでした。", parent=self.root)
            return
        self._add_paths_to_queue(paths)

    def _handle_dropped_paths(self, raw_paths: list[str]) -> None:
        self.root.after(0, lambda: self._add_paths_to_queue(raw_paths))

    def _add_paths_to_queue(self, raw_paths: list[str]) -> None:
        expanded_paths: list[str] = []
        for raw_path in raw_paths:
            candidate = Path(raw_path)
            if candidate.is_dir():
                expanded_paths.extend(list_video_files_from_folder(candidate))
            elif candidate.is_file() and candidate.suffix.lower() in VIDEO_EXTENSIONS:
                expanded_paths.append(str(candidate))

        expanded_paths = _unique_strings(expanded_paths)
        if not expanded_paths:
            messagebox.showinfo("キュー追加", "追加できる動画ファイルがありません。", parent=self.root)
            return

        settings = self.collect_settings()
        ffmpeg_path, _ = resolve_ffmpeg_path(settings)
        ffprobe_path = resolve_ffprobe_path(ffmpeg_path)

        self.status_var.set(f"動画情報を取得中... 0 / {len(expanded_paths)}")
        self.root.update_idletasks()

        for index, path in enumerate(expanded_paths, start=1):
            self.status_var.set(f"動画情報を取得中... {index} / {len(expanded_paths)}")
            self.root.update_idletasks()
            item = VideoQueueItem(queue_id=f"q{self.next_queue_id:05d}", input_path=path)
            self.next_queue_id += 1

            if Path(path).is_file():
                probe = probe_video(path, ffprobe_path, ffmpeg_path)
                item.duration_seconds = probe.duration_seconds
                item.fps = probe.fps
                if probe.error_message:
                    item.error_message = probe.error_message
                item.estimated_frame_count = estimate_frame_count(item.duration_seconds, item.fps, settings)
            else:
                item.error_message = "入力動画ファイルが存在しません。"
            self.queue_items.append(item)

        self._refresh_queue_plans()
        self._refresh_queue_tree()
        self.status_var.set(f"{len(expanded_paths)} 本の動画をキューへ追加しました。")
        self._append_log(f"キュー追加: {len(expanded_paths)} 本", tag="info")

    def _refresh_queue_plans(self) -> None:
        settings = self.collect_settings()
        reserved: set[str] = set()
        output_root = Path(settings.output_root) if settings.output_root else None
        for item in self.queue_items:
            item.estimated_frame_count = estimate_frame_count(item.duration_seconds, item.fps, settings)
            if output_root:
                plan = plan_output_directory(item.input_path, output_root, settings, reserved)
                item.output_dir = str(plan.output_dir)
            else:
                item.output_dir = ""

    def _refresh_queue_tree(self) -> None:
        selected = set(self.queue_tree.selection())
        self.queue_tree.delete(*self.queue_tree.get_children())
        for item in self.queue_items:
            tags: tuple[str, ...] = ()
            if item.status == "実行中":
                tags = ("status_running",)
            elif item.status == "完了":
                tags = ("status_complete",)
            elif item.status == "失敗":
                tags = ("status_failed",)
            elif item.status == "スキップ":
                tags = ("status_skipped",)
            elif item.status == "キャンセル":
                tags = ("status_cancelled",)

            self.queue_tree.insert(
                "",
                "end",
                iid=item.queue_id,
                values=(
                    "☑" if item.enabled else "☐",
                    item.file_name,
                    item.input_path,
                    format_duration_text(item.duration_seconds),
                    format_count_text(item.estimated_frame_count),
                    item.status,
                    item.output_dir,
                    format_count_text(item.actual_output_count),
                    item.error_message,
                ),
                tags=tags,
            )
        for item_id in selected:
            if self.queue_tree.exists(item_id):
                self.queue_tree.selection_add(item_id)

    def remove_selected_rows(self) -> None:
        selected_ids = set(self.queue_tree.selection())
        if not selected_ids:
            return
        self.queue_items = [item for item in self.queue_items if item.queue_id not in selected_ids]
        self._refresh_queue_plans()
        self._refresh_queue_tree()
        self.status_var.set(f"{len(selected_ids)} 行を削除しました。")

    def clear_queue(self) -> None:
        if not self.queue_items:
            return
        proceed = messagebox.askyesno("一覧クリア", "動画キューをすべて消しますか？", parent=self.root)
        if not proceed:
            return
        self.queue_items.clear()
        self._refresh_queue_tree()
        self.status_var.set("動画キューをクリアしました。")

    def move_selected_rows(self, direction: int) -> None:
        selected_ids = self.queue_tree.selection()
        if not selected_ids:
            return
        id_to_index = {item.queue_id: index for index, item in enumerate(self.queue_items)}
        ordered_ids = sorted(selected_ids, key=lambda item_id: id_to_index.get(item_id, 0), reverse=(direction > 0))

        for item_id in ordered_ids:
            current_index = id_to_index[item_id]
            new_index = current_index + direction
            if new_index < 0 or new_index >= len(self.queue_items):
                continue
            self.queue_items[current_index], self.queue_items[new_index] = self.queue_items[new_index], self.queue_items[current_index]
            id_to_index[self.queue_items[current_index].queue_id] = current_index
            id_to_index[self.queue_items[new_index].queue_id] = new_index

        self._refresh_queue_plans()
        self._refresh_queue_tree()
        self.queue_tree.selection_set(selected_ids)

    def remove_duplicate_rows(self) -> None:
        seen: set[str] = set()
        kept: list[VideoQueueItem] = []
        removed = 0
        for item in self.queue_items:
            key = item.normalized_path
            if key in seen:
                removed += 1
                continue
            seen.add(key)
            kept.append(item)
        self.queue_items = kept
        self._refresh_queue_plans()
        self._refresh_queue_tree()
        self.status_var.set(f"重複行を {removed} 件削除しました。")

    def remove_missing_rows(self) -> None:
        before = len(self.queue_items)
        self.queue_items = [item for item in self.queue_items if Path(item.input_path).is_file()]
        removed = before - len(self.queue_items)
        self._refresh_queue_plans()
        self._refresh_queue_tree()
        self.status_var.set(f"存在しないファイルを {removed} 件除外しました。")

    def toggle_selected_flags(self) -> None:
        selected_ids = set(self.queue_tree.selection())
        if not selected_ids:
            return
        for item in self.queue_items:
            if item.queue_id in selected_ids:
                item.enabled = not item.enabled
        self._refresh_queue_tree()

    def _on_tree_left_click(self, event: tk.Event) -> str | None:
        region = self.queue_tree.identify("region", event.x, event.y)
        column = self.queue_tree.identify_column(event.x)
        item_id = self.queue_tree.identify_row(event.y)
        if region == "cell" and column == "#1" and item_id:
            item = self._find_queue_item(item_id)
            if item:
                item.enabled = not item.enabled
                self._refresh_queue_tree()
            return "break"
        return None

    def _on_tree_double_click(self, event: tk.Event) -> None:
        item_id = self.queue_tree.identify_row(event.y)
        item = self._find_queue_item(item_id)
        if not item:
            return
        self.input_path_var.set(item.input_path)
        if item.output_dir:
            self.output_folder_var.set(item.output_dir)
        self.base_name_var.set(Path(item.input_path).stem)
        self.status_var.set(f"単体設定へ反映: {item.file_name}")

    def _on_tree_space_key(self, _event: tk.Event) -> str:
        self.toggle_selected_flags()
        return "break"

    def _find_queue_item(self, queue_id: str) -> VideoQueueItem | None:
        for item in self.queue_items:
            if item.queue_id == queue_id:
                return item
        return None

    def generate_command(self) -> str | None:
        settings = self.collect_settings()
        if settings.output_folder and not Path(settings.output_folder).exists() and not settings.include_mkdir:
            proceed = messagebox.askyesno(
                "確認",
                "単体出力フォルダが存在しません。\n"
                "「出力フォルダ作成コマンドを付ける」を ON にすることを推奨します。\n\n"
                "このままコマンドを生成しますか？",
                parent=self.root,
            )
            if not proceed:
                return None

        try:
            command = build_command(settings)
        except Exception as exc:
            messagebox.showwarning("コマンド生成", str(exc), parent=self.root)
            return None

        self._replace_text(self.command_text, command, readonly=False)
        self.status_var.set("単体モードのコマンドを生成しました。")
        self._save_current_settings()
        return command

    def copy_command(self) -> None:
        command = self.get_command_text()
        if not command.strip():
            messagebox.showwarning("コピー", "コピーするコマンドがありません。", parent=self.root)
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(command)
        self.root.update_idletasks()
        self.status_var.set("コマンドをクリップボードへコピーしました。")

    def generate_and_copy(self) -> None:
        command = self.generate_command()
        if not command:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(command)
        self.root.update_idletasks()
        self.status_var.set("コマンドを生成してクリップボードへコピーしました。")

    def execute_command(self) -> None:
        command = self.get_command_text().strip()
        if not command:
            generated = self.generate_command()
            if not generated:
                return
            command = generated

        proceed = messagebox.askyesno(
            "実行確認",
            "生成されたコマンドを PowerShell で実行します。\n"
            "別ウィンドウで ffmpeg の進行状況が表示され、完了後は自動で閉じます。\n\n"
            "続行しますか？",
            parent=self.root,
        )
        if not proceed:
            return

        try:
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ]
            )
        except Exception as exc:
            messagebox.showerror("実行", f"PowerShell の起動に失敗しました。\n\n{exc}", parent=self.root)
            return

        self.status_var.set("PowerShell を起動しました。")
        self._append_log("単体モードの PowerShell 実行を開始しました。", tag="info")

    def clear_form(self) -> None:
        self._apply_settings(AppSettings())
        self._replace_text(self.command_text, "", readonly=False)
        self.update_option_states()
        self.update_preview()
        self._refresh_queue_plans()
        self._refresh_queue_tree()
        self.status_var.set("入力内容を初期値へ戻しました。")

    def run_dry_run(self) -> None:
        settings = self.collect_settings()
        selected_items = [item for item in self.queue_items if item.enabled]
        if not selected_items:
            messagebox.showwarning("ドライラン", "選択チェック ON の動画がありません。", parent=self.root)
            return
        try:
            validate_batch_settings(settings)
        except Exception as exc:
            messagebox.showwarning("ドライラン", str(exc), parent=self.root)
            return

        ffmpeg_path, ffmpeg_message = resolve_ffmpeg_path(settings)
        ffprobe_path = resolve_ffprobe_path(ffmpeg_path)
        ok, output_message = ensure_output_root_accessible(Path(settings.output_root))

        reserved: set[str] = set()
        total_estimated = 0
        dry_lines = [
            f"ドライラン開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"対象動画数: {len(selected_items)}",
            f"FFmpeg 確認: {ffmpeg_message}",
            f"ffprobe 確認: {ffprobe_path or '見つかりません。長さ取得不可の動画は推定枚数が空欄になります。'}",
            f"出力ルート確認: {output_message}",
            f"既存出力の扱い: {self._mode_label(settings.existing_output_mode, EXISTING_OUTPUT_MODE_LABELS)}",
            f"サブフォルダ重複時: {self._mode_label(settings.duplicate_subfolder_mode, DUPLICATE_SUBFOLDER_MODE_LABELS)}",
            "",
        ]

        for item in selected_items:
            if item.duration_seconds is None and ffprobe_path and Path(item.input_path).is_file():
                probe = probe_video(item.input_path, ffprobe_path, ffmpeg_path)
                item.duration_seconds = probe.duration_seconds
                item.fps = probe.fps
                if probe.error_message:
                    item.error_message = probe.error_message
            item.estimated_frame_count = estimate_frame_count(item.duration_seconds, item.fps, settings)
            plan = plan_output_directory(item.input_path, Path(settings.output_root), settings, reserved)
            item.output_dir = str(plan.output_dir)
            if item.estimated_frame_count is not None:
                total_estimated += item.estimated_frame_count

            dry_lines.append(f"- {item.file_name}")
            dry_lines.append(f"  入力: {item.input_path}")
            dry_lines.append(f"  長さ: {format_duration_text(item.duration_seconds) or '取得不可'}")
            dry_lines.append(f"  推定出力枚数: {format_count_text(item.estimated_frame_count) or '取得不可'}")
            dry_lines.append(f"  出力予定: {item.output_dir}")
            if plan.notes:
                dry_lines.append(f"  注意: {' / '.join(plan.notes)}")
            if item.error_message:
                dry_lines.append(f"  備考: {item.error_message}")
            dry_lines.append("")

        dry_lines.insert(8, f"全体の推定出力枚数: {format_count_text(total_estimated) or '取得不可'}")
        if not ok or ffmpeg_path is None:
            dry_lines.append("実行可否: 現状のままでは実行できません。上の確認結果を見直してください。")
        else:
            dry_lines.append("実行可否: 実行準備は整っています。")

        self._refresh_queue_tree()
        self._append_log("\n".join(dry_lines), tag="info")
        self.status_var.set("ドライランを実行しました。")
        self._save_current_settings()

    def start_batch_run(self) -> None:
        self._start_batch_run(resume_mode=False)

    def resume_batch_run(self) -> None:
        self._start_batch_run(resume_mode=True)

    def _start_batch_run(self, resume_mode: bool) -> None:
        if self.batch_thread and self.batch_thread.is_alive():
            messagebox.showinfo("一括実行", "すでに処理中です。", parent=self.root)
            return

        settings = self.collect_settings()
        try:
            validate_batch_settings(settings)
        except Exception as exc:
            messagebox.showwarning("一括実行", str(exc), parent=self.root)
            return

        selected_items = [item for item in self.queue_items if item.enabled]
        if resume_mode:
            selected_items = [item for item in selected_items if item.status == "未処理"]
        if not selected_items:
            messagebox.showwarning("一括実行", "処理対象の動画がありません。", parent=self.root)
            return

        ffmpeg_path, ffmpeg_message = resolve_ffmpeg_path(settings)
        if ffmpeg_path is None:
            messagebox.showwarning("一括実行", ffmpeg_message, parent=self.root)
            return

        ok, output_message = ensure_output_root_accessible(Path(settings.output_root))
        if not ok:
            messagebox.showwarning("一括実行", output_message, parent=self.root)
            return

        if settings.existing_output_mode == "recreate_output":
            preview_reserved: set[str] = set()
            delete_targets: list[str] = []
            for item in selected_items:
                plan = plan_output_directory(item.input_path, Path(settings.output_root), settings, preview_reserved)
                if plan.will_delete and directory_has_any_output(plan.output_dir):
                    delete_targets.append(str(plan.output_dir))
            if delete_targets:
                preview_text = WINDOWS_NEWLINE.join(delete_targets[:10])
                if len(delete_targets) > 10:
                    preview_text += WINDOWS_NEWLINE + f"... 他 {len(delete_targets) - 10} 件"
                proceed = messagebox.askyesno(
                    "削除確認",
                    "既存出力を削除して作り直す設定です。次のフォルダを削除して再作成します。\n\n"
                    f"{preview_text}\n\n続行しますか？",
                    parent=self.root,
                )
                if not proceed:
                    return

        after_action_key = settings.after_complete_action
        if after_action_key in {"shutdown", "sleep"}:
            proceed = messagebox.askyesno(
                "完了後アクション確認",
                "完了後アクションに PC の終了系操作が選ばれています。\n"
                "夜間バッチの最後に実行されます。続行しますか？",
                parent=self.root,
            )
            if not proceed:
                return

        if not resume_mode:
            for item in selected_items:
                item.status = "未処理"
                item.actual_output_count = None
                item.error_message = ""
                item.exit_code = None
                item.ffmpeg_command = ""

        self._refresh_queue_plans()
        self._refresh_queue_tree()
        self._save_current_settings()
        self._reset_progress_state(selected_items_count=len(selected_items))

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self.last_log_path = LOGS_DIR / f"ffmpeg_batch_extract_{timestamp}.log"
        self.last_summary_paths = None
        self.current_run_output_root = Path(settings.output_root)
        self.cancel_event.clear()
        self.pause_requested = False
        self.batch_paused = False
        self._update_batch_button_states(running=True, paused=False)
        self._append_log(f"一括実行を開始します。FFmpeg: {ffmpeg_message}", tag="info")

        run_ids = [item.queue_id for item in selected_items]
        self.batch_thread = threading.Thread(
            target=self._batch_worker,
            args=(settings, ffmpeg_path, run_ids, self.last_log_path, resume_mode),
            daemon=True,
        )
        self.batch_thread.start()

    def _reset_progress_state(self, selected_items_count: int) -> None:
        self.current_video_var.set("現在処理中: -")
        self.overall_count_var.set(f"処理済み本数: 0 / {selected_items_count}")
        self.output_count_var.set("出力枚数: 0")
        self.overall_progress.configure(maximum=max(1, selected_items_count), value=0)
        self.current_progress.configure(maximum=100, value=0)

    def request_pause(self) -> None:
        if not self.batch_thread or not self.batch_thread.is_alive():
            return
        self.pause_requested = True
        self.status_var.set("現在の動画が終わり次第、一時停止します。")
        self._append_log("一時停止を予約しました。現在の動画完了後に止まります。", tag="info")
        self._update_batch_button_states(running=True, paused=False)

    def cancel_batch_run(self) -> None:
        if self.batch_paused and not (self.batch_thread and self.batch_thread.is_alive()):
            for item in self.queue_items:
                if item.enabled and item.status == "未処理":
                    item.status = "キャンセル"
            self.batch_paused = False
            self._refresh_queue_tree()
            self._update_batch_button_states(running=False, paused=False)
            self.status_var.set("一時停止中の残りジョブをキャンセルしました。")
            self._append_log("一時停止中の残りジョブをキャンセルしました。", tag="info")
            return

        if not self.batch_thread or not self.batch_thread.is_alive():
            return
        self.cancel_event.set()
        with self.current_process_lock:
            process = self.current_process
        if process and process.poll() is None:
            try:
                process.terminate()
            except Exception:
                pass
        self.status_var.set("キャンセルしています...")
        self._append_log("キャンセル要求を受け付けました。", tag="info")
        self._update_batch_button_states(running=True, paused=False)

    def _batch_worker(
        self,
        settings: AppSettings,
        ffmpeg_path: str,
        run_ids: list[str],
        log_path: Path,
        resume_mode: bool,
    ) -> None:
        started_at = datetime.now()
        ffprobe_path = resolve_ffprobe_path(ffmpeg_path)
        selected_items: list[VideoQueueItem] = []
        for item_id in run_ids:
            copied = self._copy_queue_item_for_worker(item_id)
            if copied is not None:
                selected_items.append(copied)
        if settings.prevent_sleep:
            self.ui_queue.put(("sleep", {"enable": True}))

        self.ui_queue.put(("run_started", {"started_at": started_at, "log_path": str(log_path), "total": len(selected_items)}))

        reserved: set[str] = set()
        results: list[BatchItemResult] = []
        processed = 0
        success_count = 0
        failure_count = 0
        skip_count = 0
        total_output_count = 0
        cancelled = False
        paused = False

        try:
            for worker_item in selected_items:
                if self.cancel_event.is_set():
                    cancelled = True
                    break
                if self.pause_requested and processed > 0:
                    paused = True
                    break

                source_path = Path(worker_item.input_path)
                if not source_path.is_file():
                    processed += 1
                    failure_count += 1
                    self.ui_queue.put(
                        (
                            "item_finished",
                            {
                                "queue_id": worker_item.queue_id,
                                "status": "失敗",
                                "output_dir": worker_item.output_dir,
                                "actual_output_count": 0,
                                "exit_code": None,
                                "error_message": "入力動画ファイルが存在しません。",
                                "ffmpeg_command": "",
                            },
                        )
                    )
                    results.append(
                        BatchItemResult(
                            queue_id=worker_item.queue_id,
                            input_path=worker_item.input_path,
                            output_dir=worker_item.output_dir,
                            status="失敗",
                            duration_seconds=worker_item.duration_seconds,
                            interval_seconds=get_interval_seconds(settings),
                            estimated_frame_count=worker_item.estimated_frame_count,
                            actual_output_count=0,
                            ffmpeg_command="",
                            exit_code=None,
                            error_message="入力動画ファイルが存在しません。",
                        )
                    )
                    self.ui_queue.put(("overall_progress", {"processed": processed, "total": len(selected_items), "output_count": total_output_count}))
                    continue

                if worker_item.duration_seconds is None and ffprobe_path:
                    probe = probe_video(worker_item.input_path, ffprobe_path, ffmpeg_path)
                    worker_item.duration_seconds = probe.duration_seconds
                    worker_item.fps = probe.fps
                    worker_item.estimated_frame_count = estimate_frame_count(worker_item.duration_seconds, worker_item.fps, settings)

                plan = plan_output_directory(worker_item.input_path, Path(settings.output_root), settings, reserved)
                output_dir = plan.output_dir
                worker_item.output_dir = str(output_dir)

                if plan.will_skip:
                    processed += 1
                    skip_count += 1
                    output_count = count_output_images(output_dir, settings.image_format)
                    total_output_count += output_count
                    self.ui_queue.put(
                        (
                            "item_finished",
                            {
                                "queue_id": worker_item.queue_id,
                                "status": "スキップ",
                                "output_dir": str(output_dir),
                                "actual_output_count": output_count,
                                "exit_code": None,
                                "error_message": "既存出力があるためスキップしました。",
                                "ffmpeg_command": "",
                            },
                        )
                    )
                    results.append(
                        BatchItemResult(
                            queue_id=worker_item.queue_id,
                            input_path=worker_item.input_path,
                            output_dir=str(output_dir),
                            status="スキップ",
                            duration_seconds=worker_item.duration_seconds,
                            interval_seconds=get_interval_seconds(settings),
                            estimated_frame_count=worker_item.estimated_frame_count,
                            actual_output_count=output_count,
                            ffmpeg_command="",
                            exit_code=None,
                            error_message="既存出力があるためスキップしました。",
                        )
                    )
                    self.ui_queue.put(("overall_progress", {"processed": processed, "total": len(selected_items), "output_count": total_output_count}))
                    continue

                try:
                    output_dir.mkdir(parents=True, exist_ok=True)
                    if plan.will_delete and output_dir.exists():
                        shutil.rmtree(output_dir)
                        output_dir.mkdir(parents=True, exist_ok=True)
                except Exception as exc:
                    processed += 1
                    failure_count += 1
                    error_message = f"出力フォルダの準備に失敗しました: {exc}"
                    self.ui_queue.put(
                        (
                            "item_finished",
                            {
                                "queue_id": worker_item.queue_id,
                                "status": "失敗",
                                "output_dir": str(output_dir),
                                "actual_output_count": 0,
                                "exit_code": None,
                                "error_message": error_message,
                                "ffmpeg_command": "",
                            },
                        )
                    )
                    results.append(
                        BatchItemResult(
                            queue_id=worker_item.queue_id,
                            input_path=worker_item.input_path,
                            output_dir=str(output_dir),
                            status="失敗",
                            duration_seconds=worker_item.duration_seconds,
                            interval_seconds=get_interval_seconds(settings),
                            estimated_frame_count=worker_item.estimated_frame_count,
                            actual_output_count=0,
                            ffmpeg_command="",
                            exit_code=None,
                            error_message=error_message,
                        )
                    )
                    self.ui_queue.put(("overall_progress", {"processed": processed, "total": len(selected_items), "output_count": total_output_count}))
                    continue

                temp_pattern = str(output_dir / f"__ffextract_tmp_%0{settings.digits}d.{settings.image_format}")
                ffmpeg_args = build_batch_ffmpeg_args(settings, ffmpeg_path, worker_item.input_path, temp_pattern)
                command_line = render_commandline(ffmpeg_args)
                self.ui_queue.put(
                    (
                        "item_started",
                        {
                            "queue_id": worker_item.queue_id,
                            "file_name": worker_item.file_name,
                            "output_dir": str(output_dir),
                            "estimated_frame_count": worker_item.estimated_frame_count,
                            "command_line": command_line,
                        },
                    )
                )

                exit_code, error_lines, current_output_count = self._run_ffmpeg_process(
                    ffmpeg_args=ffmpeg_args,
                    queue_id=worker_item.queue_id,
                    total_duration=compute_effective_duration(worker_item.duration_seconds, settings),
                    estimated_frame_count=worker_item.estimated_frame_count,
                )

                if self.cancel_event.is_set():
                    cancelled = True
                    try:
                        for temp_file in output_dir.glob(f"__ffextract_tmp_*.{settings.image_format}"):
                            temp_file.unlink(missing_ok=True)
                    except Exception:
                        pass
                    self.ui_queue.put(
                        (
                            "item_finished",
                            {
                                "queue_id": worker_item.queue_id,
                                "status": "キャンセル",
                                "output_dir": str(output_dir),
                                "actual_output_count": current_output_count,
                                "exit_code": exit_code,
                                "error_message": "キャンセルしました。",
                                "ffmpeg_command": command_line,
                            },
                        )
                    )
                    results.append(
                        BatchItemResult(
                            queue_id=worker_item.queue_id,
                            input_path=worker_item.input_path,
                            output_dir=str(output_dir),
                            status="キャンセル",
                            duration_seconds=worker_item.duration_seconds,
                            interval_seconds=get_interval_seconds(settings),
                            estimated_frame_count=worker_item.estimated_frame_count,
                            actual_output_count=current_output_count,
                            ffmpeg_command=command_line,
                            exit_code=exit_code,
                            error_message="キャンセルしました。",
                        )
                    )
                    break

                if exit_code == 0:
                    try:
                        actual_count = rename_extracted_files(output_dir, settings, Path(worker_item.input_path).stem, worker_item.fps)
                    except Exception as exc:
                        actual_count = count_output_images(output_dir, settings.image_format)
                        exit_code = 9001
                        error_lines.append(f"リネーム処理に失敗しました: {exc}")
                else:
                    actual_count = count_output_images(output_dir, settings.image_format)

                processed += 1
                total_output_count += actual_count

                if exit_code == 0:
                    success_count += 1
                    finish_status = "完了"
                    finish_error = ""
                else:
                    failure_count += 1
                    finish_status = "失敗"
                    finish_error = WINDOWS_NEWLINE.join(line for line in error_lines if line.strip()) or "ffmpeg がエラー終了しました。"

                self.ui_queue.put(
                    (
                        "item_finished",
                        {
                            "queue_id": worker_item.queue_id,
                            "status": finish_status,
                            "output_dir": str(output_dir),
                            "actual_output_count": actual_count,
                            "exit_code": exit_code,
                            "error_message": finish_error,
                            "ffmpeg_command": command_line,
                        },
                    )
                )
                self.ui_queue.put(("overall_progress", {"processed": processed, "total": len(selected_items), "output_count": total_output_count}))

                results.append(
                    BatchItemResult(
                        queue_id=worker_item.queue_id,
                        input_path=worker_item.input_path,
                        output_dir=str(output_dir),
                        status=finish_status,
                        duration_seconds=worker_item.duration_seconds,
                        interval_seconds=get_interval_seconds(settings),
                        estimated_frame_count=worker_item.estimated_frame_count,
                        actual_output_count=actual_count,
                        ffmpeg_command=command_line,
                        exit_code=exit_code,
                        error_message=finish_error,
                    )
                )

                if self.pause_requested:
                    paused = True
                    break

            if cancelled:
                for worker_item in selected_items:
                    if any(result.queue_id == worker_item.queue_id for result in results):
                        continue
                    self.ui_queue.put(
                        (
                            "item_finished",
                            {
                                "queue_id": worker_item.queue_id,
                                "status": "キャンセル",
                                "output_dir": worker_item.output_dir,
                                "actual_output_count": None,
                                "exit_code": None,
                                "error_message": "キャンセルにより未処理のまま終了しました。",
                                "ffmpeg_command": "",
                            },
                        )
                    )
                    results.append(
                        BatchItemResult(
                            queue_id=worker_item.queue_id,
                            input_path=worker_item.input_path,
                            output_dir=worker_item.output_dir,
                            status="キャンセル",
                            duration_seconds=worker_item.duration_seconds,
                            interval_seconds=get_interval_seconds(settings),
                            estimated_frame_count=worker_item.estimated_frame_count,
                            actual_output_count=None,
                            ffmpeg_command="",
                            exit_code=None,
                            error_message="キャンセルにより未処理のまま終了しました。",
                        )
                    )
        finally:
            if settings.prevent_sleep:
                self.ui_queue.put(("sleep", {"enable": False}))

        finished_at = datetime.now()
        summary_txt_path, summary_json_path = self._write_summary_files(
            settings=settings,
            results=results,
            started_at=started_at,
            finished_at=finished_at,
            success_count=success_count,
            failure_count=failure_count,
            skip_count=skip_count,
            total_output_count=total_output_count,
            cancelled=cancelled,
        )
        self.ui_queue.put(
            (
                "run_finished",
                {
                    "finished_at": finished_at,
                    "success_count": success_count,
                    "failure_count": failure_count,
                    "skip_count": skip_count,
                    "output_count": total_output_count,
                    "cancelled": cancelled,
                    "paused": paused and not cancelled,
                    "summary_txt_path": str(summary_txt_path) if summary_txt_path else "",
                    "summary_json_path": str(summary_json_path) if summary_json_path else "",
                    "after_action": settings.after_complete_action,
                },
            )
        )

    def _copy_queue_item_for_worker(self, queue_id: str) -> VideoQueueItem | None:
        item = self._find_queue_item(queue_id)
        if item is None:
            return None
        return VideoQueueItem(
            queue_id=item.queue_id,
            input_path=item.input_path,
            enabled=item.enabled,
            status=item.status,
            output_dir=item.output_dir,
            duration_seconds=item.duration_seconds,
            fps=item.fps,
            estimated_frame_count=item.estimated_frame_count,
            actual_output_count=item.actual_output_count,
            error_message=item.error_message,
            ffmpeg_command=item.ffmpeg_command,
            exit_code=item.exit_code,
        )

    def _run_ffmpeg_process(
        self,
        ffmpeg_args: list[str],
        queue_id: str,
        total_duration: float | None,
        estimated_frame_count: int | None,
    ) -> tuple[int | None, list[str], int]:
        stderr_lines: list[str] = []
        progress_messages: queue.Queue[tuple[str, str]] = queue.Queue()
        current_frame = 0

        process = subprocess.Popen(
            ffmpeg_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            universal_newlines=True,
            creationflags=CREATE_NO_WINDOW,
        )
        with self.current_process_lock:
            self.current_process = process

        def reader(stream: Any, stream_name: str) -> None:
            try:
                for raw_line in iter(stream.readline, ""):
                    progress_messages.put((stream_name, raw_line.rstrip()))
            finally:
                progress_messages.put((stream_name, "__EOF__"))

        stdout_thread = threading.Thread(target=reader, args=(process.stdout, "stdout"), daemon=True)
        stderr_thread = threading.Thread(target=reader, args=(process.stderr, "stderr"), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        stdout_done = False
        stderr_done = False

        try:
            while True:
                if self.cancel_event.is_set() and process.poll() is None:
                    try:
                        process.terminate()
                    except Exception:
                        pass

                try:
                    stream_name, line = progress_messages.get(timeout=0.2)
                except queue.Empty:
                    if process.poll() is not None and stdout_done and stderr_done:
                        break
                    continue

                if line == "__EOF__":
                    if stream_name == "stdout":
                        stdout_done = True
                    else:
                        stderr_done = True
                    if process.poll() is not None and stdout_done and stderr_done:
                        break
                    continue

                if stream_name == "stderr":
                    if line.strip():
                        stderr_lines.append(line)
                        self.ui_queue.put(("log", {"text": line, "tag": "error"}))
                    continue

                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                value = value.strip()
                if key == "frame":
                    current_frame = _safe_int(value, current_frame)
                if key == "out_time_ms":
                    try:
                        current_seconds = max(0.0, int(value) / 1_000_000.0)
                    except ValueError:
                        current_seconds = None
                    self.ui_queue.put(
                        (
                            "item_progress",
                            {
                                "queue_id": queue_id,
                                "current_seconds": current_seconds,
                                "total_seconds": total_duration,
                                "current_frame": current_frame,
                                "estimated_frame_count": estimated_frame_count,
                            },
                        )
                    )
                elif key == "progress" and value == "end":
                    self.ui_queue.put(
                        (
                            "item_progress",
                            {
                                "queue_id": queue_id,
                                "current_seconds": total_duration,
                                "total_seconds": total_duration,
                                "current_frame": current_frame,
                                "estimated_frame_count": estimated_frame_count,
                            },
                        )
                    )

            return process.wait(), stderr_lines, current_frame
        finally:
            with self.current_process_lock:
                self.current_process = None
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)

    def _write_summary_files(
        self,
        settings: AppSettings,
        results: list[BatchItemResult],
        started_at: datetime,
        finished_at: datetime,
        success_count: int,
        failure_count: int,
        skip_count: int,
        total_output_count: int,
        cancelled: bool,
    ) -> tuple[Path | None, Path | None]:
        if not settings.output_root:
            return None, None
        output_root = Path(settings.output_root)
        output_root.mkdir(parents=True, exist_ok=True)
        timestamp = finished_at.strftime("%Y%m%d_%H%M%S")
        summary_txt_path = output_root / f"batch_extract_summary_{timestamp}.txt"
        summary_json_path = output_root / f"batch_extract_summary_{timestamp}.json"

        summary_json = {
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "cancelled": cancelled,
            "settings": {
                "interval_seconds": get_interval_seconds(settings),
                "start_time": settings.start_position,
                "end_time": settings.end_position,
                "duration_legacy": settings.duration,
                "image_format": settings.image_format,
                "jpg_quality": settings.jpeg_quality,
                "resize_enabled": settings.resize_enabled,
                "resize_width": settings.resize_width,
                "resize_height": settings.resize_height,
                "keep_aspect": settings.keep_aspect,
                "file_name_pattern": settings.file_name_pattern,
                "existing_output_mode": settings.existing_output_mode,
                "prevent_sleep": settings.prevent_sleep,
                "after_complete_action": settings.after_complete_action,
            },
            "videos": [
                {
                    "input_path": result.input_path,
                    "output_dir": result.output_dir,
                    "status": result.status,
                    "duration_seconds": result.duration_seconds,
                    "interval_seconds": result.interval_seconds,
                    "estimated_frame_count": result.estimated_frame_count,
                    "actual_output_count": result.actual_output_count,
                    "ffmpeg_command": result.ffmpeg_command,
                    "exit_code": result.exit_code,
                    "error_message": result.error_message,
                }
                for result in results
            ],
        }
        summary_json_path.write_text(json.dumps(summary_json, ensure_ascii=False, indent=2), encoding="utf-8-sig")

        failed_videos = [result for result in results if result.status == "失敗"]
        lines = [
            f"実行日時: {started_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"終了日時: {finished_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"入力動画数: {len(results)}",
            f"成功: {success_count}",
            f"失敗: {failure_count}",
            f"スキップ: {skip_count}",
            f"キャンセル: {'あり' if cancelled else 'なし'}",
            f"出力合計枚数: {total_output_count:,}",
            "",
            "失敗した動画一覧:",
        ]
        if failed_videos:
            for result in failed_videos:
                lines.append(f"- {result.input_path}")
                lines.append(f"  理由: {result.error_message or 'ffmpeg エラー'}")
        else:
            lines.append("- なし")

        lines.extend(["", "各動画の出力先:"])
        for result in results:
            lines.append(f"- {result.input_path}")
            lines.append(f"  状態: {result.status}")
            lines.append(f"  出力先: {result.output_dir}")
            lines.append(f"  出力枚数: {result.actual_output_count if result.actual_output_count is not None else '-'}")
        summary_txt_path.write_text(WINDOWS_NEWLINE.join(lines), encoding="utf-8-sig")

        return summary_txt_path, summary_json_path

    def _poll_ui_queue(self) -> None:
        try:
            while True:
                event_name, payload = self.ui_queue.get_nowait()
                if event_name == "log":
                    self._append_log(payload.get("text", ""), tag=payload.get("tag", "info"))
                elif event_name == "sleep":
                    if payload.get("enable"):
                        self.sleep_inhibitor.enable()
                    else:
                        self.sleep_inhibitor.disable()
                elif event_name == "run_started":
                    started_at = payload["started_at"]
                    self.status_var.set(f"一括実行中... {started_at.strftime('%H:%M:%S')} 開始")
                    self._append_log(f"実行開始: {started_at.strftime('%Y-%m-%d %H:%M:%S')}", tag="info")
                    if payload.get("log_path"):
                        self._append_log(f"ログファイル: {payload['log_path']}", tag="info")
                elif event_name == "item_started":
                    queue_id = payload["queue_id"]
                    item = self._find_queue_item(queue_id)
                    if item:
                        item.status = "実行中"
                        item.output_dir = payload["output_dir"]
                        item.error_message = ""
                        item.ffmpeg_command = payload["command_line"]
                    self.current_video_var.set(f"現在処理中: {payload['file_name']}")
                    self.current_progress.configure(maximum=100, value=0)
                    self._append_log(f"開始: {payload['file_name']}", tag="info")
                    self._append_log(f"出力先: {payload['output_dir']}", tag="info")
                    self._append_log(f"FFmpeg: {payload['command_line']}", tag="info")
                    self._refresh_queue_tree()
                elif event_name == "item_progress":
                    total_seconds = payload.get("total_seconds")
                    current_seconds = payload.get("current_seconds")
                    estimated_frame_count = payload.get("estimated_frame_count")
                    current_frame = payload.get("current_frame") or 0
                    if total_seconds and total_seconds > 0 and current_seconds is not None:
                        percent = max(0.0, min(100.0, (current_seconds / total_seconds) * 100.0))
                        self.current_progress.configure(maximum=100, value=percent)
                    elif estimated_frame_count and estimated_frame_count > 0:
                        percent = max(0.0, min(100.0, (current_frame / estimated_frame_count) * 100.0))
                        self.current_progress.configure(maximum=100, value=percent)
                elif event_name == "item_finished":
                    queue_id = payload["queue_id"]
                    item = self._find_queue_item(queue_id)
                    if item:
                        item.status = payload["status"]
                        item.output_dir = payload["output_dir"]
                        item.actual_output_count = payload["actual_output_count"]
                        item.exit_code = payload["exit_code"]
                        item.error_message = payload["error_message"]
                        item.ffmpeg_command = payload["ffmpeg_command"]
                    self.current_progress.configure(maximum=100, value=100 if payload["status"] == "完了" else 0)
                    if payload["status"] == "完了":
                        self._append_log(
                            f"完了: {Path(item.input_path).name if item else queue_id} / 出力枚数 {payload['actual_output_count']}",
                            tag="success",
                        )
                    elif payload["status"] == "スキップ":
                        self._append_log(
                            f"スキップ: {Path(item.input_path).name if item else queue_id} / {payload['error_message']}",
                            tag="info",
                        )
                    elif payload["status"] == "キャンセル":
                        self._append_log(
                            f"キャンセル: {Path(item.input_path).name if item else queue_id}",
                            tag="error",
                        )
                    else:
                        self._append_log(
                            f"失敗: {Path(item.input_path).name if item else queue_id} / {payload['error_message']}",
                            tag="error",
                        )
                    self._refresh_queue_tree()
                elif event_name == "overall_progress":
                    processed = payload["processed"]
                    total = payload["total"]
                    output_count = payload["output_count"]
                    self.overall_count_var.set(f"処理済み本数: {processed} / {total}")
                    self.output_count_var.set(f"出力枚数: {output_count:,}")
                    self.overall_progress.configure(maximum=max(1, total), value=processed)
                elif event_name == "run_finished":
                    self.batch_paused = payload["paused"]
                    cancelled = payload["cancelled"]
                    if cancelled:
                        self.status_var.set("一括実行をキャンセルしました。")
                    elif payload["paused"]:
                        self.status_var.set("一時停止しました。再開で残りを処理できます。")
                    else:
                        self.status_var.set("一括実行が完了しました。")
                    self.last_summary_paths = (
                        Path(payload["summary_txt_path"]) if payload["summary_txt_path"] else None,
                        Path(payload["summary_json_path"]) if payload["summary_json_path"] else None,
                    )
                    self._append_log(
                        f"実行終了: 成功 {payload['success_count']} / 失敗 {payload['failure_count']} / スキップ {payload['skip_count']}",
                        tag="info",
                    )
                    if payload["summary_txt_path"]:
                        self._append_log(f"サマリ TXT: {payload['summary_txt_path']}", tag="info")
                    if payload["summary_json_path"]:
                        self._append_log(f"サマリ JSON: {payload['summary_json_path']}", tag="info")
                    self.current_video_var.set("現在処理中: -")
                    self.current_progress.configure(maximum=100, value=0 if payload["paused"] else 100)
                    self._update_batch_button_states(running=False, paused=payload["paused"])
                    if not payload["paused"]:
                        self.pause_requested = False
                    self._run_after_complete_action(payload["after_action"], cancelled=cancelled, paused=payload["paused"])
        except queue.Empty:
            pass
        finally:
            self.root.after(120, self._poll_ui_queue)

    def _append_log(self, text: str, tag: str = "info") -> None:
        if not text:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        for line in text.splitlines():
            entry = f"[{timestamp}] {line}"
            previous_state = self.log_text.cget("state")
            self.log_text.configure(state="normal")
            self.log_text.insert(tk.END, entry + WINDOWS_NEWLINE, tag)
            self.log_text.see(tk.END)
            self.log_text.configure(state=previous_state)
            if self.last_log_path:
                self.last_log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.last_log_path.open("a", encoding="utf-8-sig") as handle:
                    handle.write(entry + WINDOWS_NEWLINE)

    def _run_after_complete_action(self, action: str, cancelled: bool, paused: bool) -> None:
        if cancelled or paused:
            return
        if action == "none":
            return
        if action == "beep":
            try:
                import winsound

                winsound.MessageBeep()
            except Exception:
                pass
            return
        if action == "open_output":
            self.open_output_folder()
            return
        if action == "shutdown":
            try:
                subprocess.Popen(["shutdown", "/s", "/t", "30"], creationflags=CREATE_NO_WINDOW)
                self._append_log("30 秒後に PC をシャットダウンします。", tag="info")
            except Exception as exc:
                self._append_log(f"シャットダウン指示に失敗しました: {exc}", tag="error")
            return
        if action == "sleep":
            try:
                ctypes.windll.powrprof.SetSuspendState(False, True, True)
                self._append_log("PC をスリープします。", tag="info")
            except Exception as exc:
                self._append_log(f"スリープ指示に失敗しました: {exc}", tag="error")

    def _update_batch_button_states(self, running: bool | None = None, paused: bool | None = None) -> None:
        is_running = running if running is not None else bool(self.batch_thread and self.batch_thread.is_alive())
        is_paused = paused if paused is not None else self.batch_paused
        self.dry_run_button.configure(state="disabled" if is_running else "normal")
        self.run_button.configure(state="disabled" if is_running else "normal")
        self.pause_button.configure(state="normal" if is_running else "disabled")
        self.resume_button.configure(state="normal" if is_paused and not is_running else "disabled")
        self.cancel_button.configure(state="normal" if is_running or is_paused else "disabled")

    def open_output_folder(self) -> None:
        candidate = None
        selected_ids = self.queue_tree.selection()
        if selected_ids:
            item = self._find_queue_item(selected_ids[0])
            if item and item.output_dir:
                candidate = item.output_dir
        if candidate is None and self.output_root_var.get().strip():
            candidate = self.output_root_var.get().strip()
        if candidate is None and self.output_folder_var.get().strip():
            candidate = self.output_folder_var.get().strip()
        if not candidate:
            messagebox.showwarning("出力フォルダを開く", "開くフォルダがありません。", parent=self.root)
            return
        path = Path(candidate)
        if not path.exists():
            messagebox.showwarning("出力フォルダを開く", "指定フォルダがまだ存在しません。", parent=self.root)
            return
        os.startfile(path)

    def save_log_to_file(self) -> None:
        initial_name = f"ffmpeg_batch_extract_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="ログ保存先を選択",
            defaultextension=".txt",
            filetypes=[("テキスト ファイル", "*.txt"), ("すべてのファイル", "*.*")],
            initialfile=initial_name,
        )
        if not selected:
            return
        Path(selected).write_text(self.log_text.get("1.0", tk.END), encoding="utf-8-sig")
        self.status_var.set("ログを保存しました。")

    def save_job_file(self) -> None:
        settings = self.collect_settings()
        data = {
            "job_name": "",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "output_root": settings.output_root,
            "settings": {
                "interval_seconds": get_interval_seconds(settings) or 0,
                "extract_mode": settings.extract_mode,
                "custom_seconds": settings.custom_seconds,
                "start_time": settings.start_position,
                "end_time": settings.end_position,
                "duration_legacy": settings.duration,
                "image_format": settings.image_format,
                "jpg_quality": settings.jpeg_quality,
                "digits": settings.digits,
                "resize_enabled": settings.resize_enabled,
                "resize_width": settings.resize_width,
                "resize_height": settings.resize_height,
                "keep_aspect": settings.keep_aspect,
                "file_name_pattern": settings.file_name_pattern,
                "existing_output_mode": settings.existing_output_mode,
                "duplicate_subfolder_mode": settings.duplicate_subfolder_mode,
                "prevent_sleep": settings.prevent_sleep,
                "after_complete_action": settings.after_complete_action,
                "ffmpeg_path": settings.ffmpeg_path,
                "use_ffmpeg_path": settings.use_ffmpeg_path,
            },
            "videos": [item.to_job_dict() for item in self.queue_items],
        }
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="ジョブ保存先を選択",
            defaultextension=".json",
            filetypes=JSON_FILETYPES,
            initialfile=f"ffmpeg_batch_job_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
        if not selected:
            return
        Path(selected).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8-sig")
        self.status_var.set("ジョブを保存しました。")

    def load_job_file(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="ジョブ JSON を選択",
            filetypes=JSON_FILETYPES,
        )
        if not selected:
            return
        try:
            raw = json.loads(Path(selected).read_text(encoding="utf-8-sig"))
        except Exception as exc:
            messagebox.showerror("ジョブ読込", f"ジョブ JSON の読み込みに失敗しました。\n\n{exc}", parent=self.root)
            return

        settings_data = raw.get("settings", {}) if isinstance(raw, dict) else {}
        current = self.collect_settings()
        current.output_root = _safe_string(raw.get("output_root", current.output_root))
        current.extract_mode = _safe_choice(settings_data.get("extract_mode", current.extract_mode), EXTRACT_MODES, current.extract_mode)
        current.custom_seconds = max(_safe_float(settings_data.get("custom_seconds", current.custom_seconds), current.custom_seconds), 0.001)
        current.start_position = _safe_string(settings_data.get("start_time", current.start_position))
        current.end_position = _safe_string(settings_data.get("end_time", current.end_position))
        current.duration = _safe_string(settings_data.get("duration_legacy", current.duration))
        current.image_format = _safe_choice(settings_data.get("image_format", current.image_format), IMAGE_FORMATS, current.image_format)
        current.jpeg_quality = _clamp(_safe_int(settings_data.get("jpg_quality", current.jpeg_quality), current.jpeg_quality), 1, 31)
        current.digits = _clamp(_safe_int(settings_data.get("digits", current.digits), current.digits), 1, 10)
        current.resize_enabled = _safe_bool(settings_data.get("resize_enabled", current.resize_enabled))
        current.resize_width = max(0, _safe_int(settings_data.get("resize_width", current.resize_width), current.resize_width))
        current.resize_height = max(0, _safe_int(settings_data.get("resize_height", current.resize_height), current.resize_height))
        current.keep_aspect = _safe_bool(settings_data.get("keep_aspect", current.keep_aspect))
        current.file_name_pattern = _safe_string(settings_data.get("file_name_pattern", current.file_name_pattern)) or current.file_name_pattern
        current.existing_output_mode = _safe_choice(
            settings_data.get("existing_output_mode", current.existing_output_mode),
            list(EXISTING_OUTPUT_MODE_LABELS.keys()),
            current.existing_output_mode,
        )
        current.duplicate_subfolder_mode = _safe_choice(
            settings_data.get("duplicate_subfolder_mode", current.duplicate_subfolder_mode),
            list(DUPLICATE_SUBFOLDER_MODE_LABELS.keys()),
            current.duplicate_subfolder_mode,
        )
        current.prevent_sleep = _safe_bool(settings_data.get("prevent_sleep", current.prevent_sleep))
        current.after_complete_action = _safe_choice(
            settings_data.get("after_complete_action", current.after_complete_action),
            list(AFTER_COMPLETE_ACTION_LABELS.keys()),
            current.after_complete_action,
        )
        current.ffmpeg_path = _safe_string(settings_data.get("ffmpeg_path", current.ffmpeg_path)) or current.ffmpeg_path
        current.use_ffmpeg_path = _safe_bool(settings_data.get("use_ffmpeg_path", current.use_ffmpeg_path))
        self._apply_settings(current)

        videos_raw = raw.get("videos", []) if isinstance(raw, dict) else []
        self.queue_items.clear()
        for video_raw in videos_raw:
            if not isinstance(video_raw, dict):
                continue
            item = VideoQueueItem(
                queue_id=f"q{self.next_queue_id:05d}",
                input_path=_safe_string(video_raw.get("input_path", "")),
                enabled=_safe_bool(video_raw.get("enabled", True)),
                output_dir=_safe_string(video_raw.get("output_dir", "")),
                status=_safe_choice(video_raw.get("status", "未処理"), QUEUE_STATUSES, "未処理"),
            )
            self.next_queue_id += 1
            self.queue_items.append(item)

        self._hydrate_queue_metadata()
        self._refresh_queue_plans()
        self._refresh_queue_tree()
        self.status_var.set("ジョブを読み込みました。")

    def _hydrate_queue_metadata(self) -> None:
        settings = self.collect_settings()
        ffmpeg_path, _ = resolve_ffmpeg_path(settings)
        ffprobe_path = resolve_ffprobe_path(ffmpeg_path)
        for item in self.queue_items:
            if Path(item.input_path).is_file():
                probe = probe_video(item.input_path, ffprobe_path, ffmpeg_path)
                item.duration_seconds = probe.duration_seconds
                item.fps = probe.fps
                item.estimated_frame_count = estimate_frame_count(item.duration_seconds, item.fps, settings)
                item.error_message = probe.error_message
            else:
                item.error_message = "入力動画ファイルが存在しません。"

    def _show_entry_context_menu(self, event: tk.Event) -> str:
        widget = event.widget
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="切り取り", command=lambda w=widget: self._entry_cut(w))
        menu.add_command(label="コピー", command=lambda w=widget: self._entry_copy(w))
        menu.add_command(label="貼り付け", command=lambda w=widget: self._entry_paste(w))
        menu.add_separator()
        menu.add_command(label="すべて選択", command=lambda w=widget: self._entry_select_all(w))
        self._popup_menu(menu, event)
        return "break"

    def _show_text_context_menu(self, event: tk.Event) -> str:
        widget = event.widget
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="コピー", command=lambda w=widget: self._text_copy(w))
        menu.add_separator()
        menu.add_command(label="すべて選択", command=lambda w=widget: self._text_select_all(w))
        self._popup_menu(menu, event)
        return "break"

    def _show_tree_context_menu(self, event: tk.Event) -> str:
        item_id = self.queue_tree.identify_row(event.y)
        if item_id and item_id not in self.queue_tree.selection():
            self.queue_tree.selection_set(item_id)
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="選択反転", command=self.toggle_selected_flags)
        menu.add_command(label="選択行を削除", command=self.remove_selected_rows)
        menu.add_separator()
        menu.add_command(label="コピー", command=self._copy_selected_tree_cells)
        self._popup_menu(menu, event)
        return "break"

    def _copy_selected_tree_cells(self) -> None:
        selected_ids = self.queue_tree.selection()
        if not selected_ids:
            return
        lines: list[str] = []
        for item_id in selected_ids:
            values = self.queue_tree.item(item_id, "values")
            lines.append("\t".join(str(value) for value in values))
        self.root.clipboard_clear()
        self.root.clipboard_append(WINDOWS_NEWLINE.join(lines))

    def _popup_menu(self, menu: tk.Menu, event: tk.Event) -> None:
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _entry_cut(self, widget: tk.Widget) -> None:
        try:
            selected = widget.selection_get()
        except tk.TclError:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(selected)
        widget.delete("sel.first", "sel.last")

    def _entry_copy(self, widget: tk.Widget) -> None:
        try:
            selected = widget.selection_get()
        except tk.TclError:
            selected = widget.get()
        self.root.clipboard_clear()
        self.root.clipboard_append(selected)

    def _entry_paste(self, widget: tk.Widget) -> None:
        try:
            paste_text = self.root.clipboard_get()
        except tk.TclError:
            return
        try:
            widget.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        insert_index = widget.index("insert")
        widget.insert(insert_index, paste_text)

    def _entry_select_all(self, widget: tk.Widget) -> None:
        widget.focus_set()
        try:
            widget.selection_range(0, tk.END)
            widget.icursor(tk.END)
        except tk.TclError:
            pass

    def _text_copy(self, widget: tk.Text) -> None:
        try:
            selected = widget.get("sel.first", "sel.last")
        except tk.TclError:
            selected = widget.get("1.0", tk.END).rstrip()
        self.root.clipboard_clear()
        self.root.clipboard_append(selected)

    def _text_select_all(self, widget: tk.Text) -> None:
        widget.focus_set()
        widget.tag_add("sel", "1.0", tk.END)
        widget.mark_set("insert", "1.0")
        widget.see("insert")

    def _replace_text(self, widget: tk.Text, text: str, readonly: bool) -> None:
        previous_state = widget.cget("state")
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state="disabled" if readonly else "normal")
        if previous_state == "disabled" and not readonly:
            widget.configure(state="normal")

    def get_command_text(self) -> str:
        return self.command_text.get("1.0", tk.END).strip()

    def _mode_label(self, key: str, mapping: dict[str, str]) -> str:
        return mapping.get(key, next(iter(mapping.values())))

    def _mode_key(self, label: str, mapping: dict[str, str]) -> str:
        reverse = {value: key for key, value in mapping.items()}
        return reverse.get(label, next(iter(mapping.keys())))

    def _save_current_settings(self) -> None:
        try:
            settings = self.collect_settings()
            save_settings(settings)
            self.loaded_settings = settings
        except Exception as exc:
            messagebox.showerror("設定保存", f"設定ファイルの保存に失敗しました。\n\n{exc}", parent=self.root)

    @staticmethod
    def _existing_directory(raw_path: str) -> str | None:
        if not raw_path:
            return None
        candidate = Path(raw_path)
        if candidate.is_dir():
            return str(candidate)
        return None

    @staticmethod
    def _existing_parent_directory(raw_path: str) -> str | None:
        if not raw_path:
            return None
        candidate = Path(raw_path)
        parent = candidate.parent
        if parent.is_dir():
            return str(parent)
        return None

    def on_close(self) -> None:
        if self.batch_thread and self.batch_thread.is_alive():
            proceed = messagebox.askyesno(
                "終了確認",
                "一括処理が実行中です。キャンセルして終了しますか？",
                parent=self.root,
            )
            if not proceed:
                return
            self.cancel_event.set()
            with self.current_process_lock:
                process = self.current_process
            if process and process.poll() is None:
                try:
                    process.terminate()
                except Exception:
                    pass
        self.sleep_inhibitor.disable()
        if self.drop_hook:
            self.drop_hook.close()
        self._save_current_settings()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    app = FfmpegFrameExtractCommandGui()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
