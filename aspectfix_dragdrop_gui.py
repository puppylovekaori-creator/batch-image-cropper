from __future__ import annotations

import argparse
import json
import queue
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

try:
    from PIL import Image, ImageFilter, ImageOps, ImageTk, UnidentifiedImageError

    PIL_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - depends on environment
    Image = None  # type: ignore[assignment]
    ImageFilter = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]
    ImageTk = None  # type: ignore[assignment]
    UnidentifiedImageError = OSError  # type: ignore[assignment]
    PIL_IMPORT_ERROR = exc

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    TKDND_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - optional dependency
    DND_FILES = None  # type: ignore[assignment]
    TkinterDnD = None  # type: ignore[assignment]
    TKDND_IMPORT_ERROR = exc


APP_TITLE = "画像アスペクト補正ツール"
HEADLESS_OK_MESSAGE = "gui_ok"
WINDOWS_NEWLINE = "\r\n"
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "aspectfix_dragdrop_config.json"
LOG_FOLDER_NAME = "logs"
REPORT_FILE_PREFIX = "aspectfix_report_"
DEFAULT_WINDOW_GEOMETRY = "1560x980"
DEFAULT_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".bmp"]
INVALID_FILE_NAME_CHARS = set('<>:"/\\|?*')
DROP_MESSAGE = "ここに画像ファイルをドラッグ＆ドロップ"
DROP_FALLBACK_MESSAGE = "ドラッグ＆ドロップを使うには requirements_aspectfix.txt のインストールが必要です"
PREVIEW_BOX_SIZE = (760, 720)

STATUS_WAITING = "待機"
STATUS_READY = "準備完了"
STATUS_PROCESSING = "処理中"
STATUS_DONE = "完了"
STATUS_FAILED = "失敗"
STATUS_SKIPPED = "スキップ"
STATUS_STOPPED = "停止"

MODE_LABELS = {
    "manual_scale": "手動倍率補正",
}
DEFAULT_X_SCALE = 1.185185
DEFAULT_Y_SCALE = 1.0
CUSTOM_PRESET_LABEL = "カスタム"
CONTENT_PRESET_LABELS = {
    "720x480 → 16:9表示相当補正": (1.185185, 1.0),
    "変更なし": (1.0, 1.0),
    "横を少し縮める": (0.98, 1.0),
    "横を縮める": (0.95, 1.0),
    "横を少し広げる": (1.05, 1.0),
    "縦を少し縮める": (1.0, 0.98),
    "縦を縮める": (1.0, 0.95),
    CUSTOM_PRESET_LABEL: None,
}
DEFAULT_CONTENT_PRESET_LABEL = "720x480 → 16:9表示相当補正"
CANVAS_PROCESSING_LABELS = {
    "none": "なし",
    "original_fit": "元画像サイズに中央配置",
    "original_crop": "元画像サイズに中央クロップ",
    "aspect_ratio_fit": "指定比率キャンバスに配置",
    "blur": "ぼかし背景",
}
CANVAS_PAD_COLOR_LABELS = {
    "black": "黒",
    "white": "白",
    "gray": "グレー",
}
OUTPUT_FORMAT_LABELS = {
    "keep_original": "元拡張子で保存",
    "jpeg": "JPEGで保存",
    "png": "PNGで保存",
    "webp": "WebPで保存",
}
INTERPOLATION_LABELS = {
    "lanczos": "高品質補間",
    "bicubic": "なめらか補間",
    "bilinear": "標準補間",
    "nearest": "最近傍補間",
}

MODE_LABEL_TO_KEY = {label: key for key, label in MODE_LABELS.items()}
CANVAS_PROCESSING_LABEL_TO_KEY = {label: key for key, label in CANVAS_PROCESSING_LABELS.items()}
CANVAS_PAD_COLOR_LABEL_TO_KEY = {label: key for key, label in CANVAS_PAD_COLOR_LABELS.items()}
OUTPUT_FORMAT_LABEL_TO_KEY = {label: key for key, label in OUTPUT_FORMAT_LABELS.items()}
INTERPOLATION_LABEL_TO_KEY = {label: key for key, label in INTERPOLATION_LABELS.items()}

if Image is not None:
    try:
        RESAMPLE_NEAREST = Image.Resampling.NEAREST
        RESAMPLE_BILINEAR = Image.Resampling.BILINEAR
        RESAMPLE_BICUBIC = Image.Resampling.BICUBIC
        RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
    except AttributeError:  # pragma: no cover - Pillow compatibility fallback
        RESAMPLE_NEAREST = Image.NEAREST
        RESAMPLE_BILINEAR = Image.BILINEAR
        RESAMPLE_BICUBIC = Image.BICUBIC
        RESAMPLE_LANCZOS = Image.LANCZOS
else:  # pragma: no cover - depends on environment
    RESAMPLE_NEAREST = None
    RESAMPLE_BILINEAR = None
    RESAMPLE_BICUBIC = None
    RESAMPLE_LANCZOS = None

RESAMPLE_MAP = {
    "nearest": RESAMPLE_NEAREST,
    "bilinear": RESAMPLE_BILINEAR,
    "bicubic": RESAMPLE_BICUBIC,
    "lanczos": RESAMPLE_LANCZOS,
}

PIL_FORMAT_BY_EXTENSION = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".bmp": "BMP",
}


@dataclass
class AppConfig:
    output_folder: str = r"C:\output_aspect_fixed"
    recursive_folder_drop: bool = True
    keep_folder_structure_when_folder_added: bool = False
    extensions: list[str] = field(default_factory=lambda: list(DEFAULT_EXTENSIONS))
    mode: str = "manual_scale"
    x_scale: float = DEFAULT_X_SCALE
    y_scale: float = DEFAULT_Y_SCALE
    content_preset: str = DEFAULT_CONTENT_PRESET_LABEL
    canvas_processing: str = "none"
    save_canvas_aspect_ratio: str = "16:9"
    canvas_pad_color: str = "black"
    output_format: str = "keep_original"
    suffix: str = "_aspectfix"
    jpeg_quality: int = 95
    webp_quality: int = 95
    interpolation: str = "lanczos"
    overwrite: bool = False
    delete_source: bool = False
    window_geometry: str = DEFAULT_WINDOW_GEOMETRY

    @classmethod
    def from_dict(cls, raw: object) -> "AppConfig":
        data = raw if isinstance(raw, dict) else {}
        x_scale = max(0.01, _safe_float(data.get("XScale", DEFAULT_X_SCALE), DEFAULT_X_SCALE))
        y_scale = max(0.01, _safe_float(data.get("YScale", DEFAULT_Y_SCALE), DEFAULT_Y_SCALE))
        content_preset = normalize_content_preset(
            _safe_string(data.get("DefaultPreset", data.get("ContentPreset", ""))),
            x_scale,
            y_scale,
        )
        canvas_processing = normalize_canvas_mode(
            _safe_string(data.get("CanvasMode", data.get("CanvasProcessing", ""))),
            data,
        )
        return cls(
            output_folder=_safe_string(data.get("OutputFolder", r"C:\output_aspect_fixed")),
            recursive_folder_drop=_safe_bool(data.get("RecursiveFolderDrop", True)),
            keep_folder_structure_when_folder_added=_safe_bool(data.get("KeepFolderStructureWhenFolderAdded", False)),
            extensions=normalize_extensions(data.get("Extensions", DEFAULT_EXTENSIONS)),
            mode=normalize_choice(_safe_string(data.get("Mode", "manual_scale")), MODE_LABELS, "manual_scale"),
            x_scale=x_scale,
            y_scale=y_scale,
            content_preset=content_preset,
            canvas_processing=canvas_processing,
            save_canvas_aspect_ratio=(
                _safe_string(data.get("SaveCanvasAspectRatio", _safe_string(data.get("TargetAspectRatio", "16:9"))))
                or "16:9"
            ),
            canvas_pad_color=normalize_choice(
                _safe_string(data.get("CanvasPadColor", _legacy_canvas_pad_color_key(data))),
                CANVAS_PAD_COLOR_LABELS,
                "black",
            ),
            output_format=normalize_choice(
                _safe_string(data.get("OutputFormat", "keep_original")),
                OUTPUT_FORMAT_LABELS,
                "keep_original",
            ),
            suffix=_safe_string(data.get("Suffix", "_aspectfix")) or "_aspectfix",
            jpeg_quality=_clamp_int(_safe_int(data.get("JpegQuality", 95), 95), 1, 100),
            webp_quality=_clamp_int(_safe_int(data.get("WebpQuality", 95), 95), 1, 100),
            interpolation=normalize_choice(
                _safe_string(data.get("Interpolation", "lanczos")),
                INTERPOLATION_LABELS,
                "lanczos",
            ),
            overwrite=_safe_bool(data.get("Overwrite", False)),
            delete_source=_safe_bool(data.get("DeleteSource", False)),
            window_geometry=_safe_string(data.get("WindowGeometry", DEFAULT_WINDOW_GEOMETRY)) or DEFAULT_WINDOW_GEOMETRY,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "OutputFolder": self.output_folder,
            "RecursiveFolderDrop": self.recursive_folder_drop,
            "KeepFolderStructureWhenFolderAdded": self.keep_folder_structure_when_folder_added,
            "Extensions": list(self.extensions),
            "Mode": self.mode,
            "XScale": self.x_scale,
            "YScale": self.y_scale,
            "DefaultPreset": self.content_preset,
            "CanvasMode": canvas_processing_name(self.canvas_processing),
            "SaveCanvasAspectRatio": self.save_canvas_aspect_ratio,
            "CanvasPadColor": canvas_pad_color_name(self.canvas_pad_color),
            "OutputFormat": self.output_format,
            "Suffix": self.suffix,
            "JpegQuality": self.jpeg_quality,
            "WebpQuality": self.webp_quality,
            "Interpolation": self.interpolation,
            "Overwrite": self.overwrite,
            "DeleteSource": self.delete_source,
            "WindowGeometry": self.window_geometry,
        }


@dataclass
class ProcessItem:
    item_id: str
    source_path: Path
    source_root: Path | None
    added_via_folder: bool
    original_size: tuple[int, int]
    original_aspect_text: str
    status: str = STATUS_READY
    output_name: str = "-"
    output_path: Path | None = None
    corrected_size: tuple[int, int] | None = None
    corrected_aspect_text: str = "-"
    output_size: tuple[int, int] | None = None
    output_aspect_text: str = "-"
    canvas_status_text: str = "倍率補正のみ / キャンバス処理なし"
    error_text: str = ""
    processed_at: datetime | None = None


@dataclass
class BatchSummary:
    started_at: datetime
    finished_at: datetime | None = None
    total_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    skip_count: int = 0
    stopped: bool = False
    log_file_path: Path | None = None
    report_file_path: Path | None = None


class RunLogger:
    def __init__(self, log_path: Path, ui_sender: Callable[[dict[str, Any]], None]) -> None:
        self.log_path = log_path
        self._ui_sender = ui_sender
        self._lock = threading.Lock()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def info(self, message: str) -> None:
        self._write("情報", message)

    def warning(self, message: str) -> None:
        self._write("注意", message)

    def error(self, message: str) -> None:
        self._write("エラー", message)

    def _write(self, level: str, message: str) -> None:
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {message}"
        with self._lock:
            with self.log_path.open("a", encoding="utf-8", newline="") as handle:
                handle.write(line + WINDOWS_NEWLINE)
        self._ui_sender({"kind": "log", "line": line})


if TkinterDnD is not None:
    AppBase = TkinterDnD.Tk
else:
    AppBase = tk.Tk


class AspectFixApp(AppBase):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(1320, 860)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.config_data = load_config()
        self.ui_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.items: list[ProcessItem] = []
        self.item_lookup: dict[str, ProcessItem] = {}
        self.source_key_set: set[str] = set()
        self.item_counter = 0
        self.processing_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.current_summary: BatchSummary | None = None
        self.current_logger: RunLogger | None = None
        self.preview_before_photo: Any | None = None
        self.preview_after_photo: Any | None = None
        self.preview_window: tk.Toplevel | None = None
        self.preview_before_label: ttk.Label | None = None
        self.preview_after_label: ttk.Label | None = None
        self.preview_file_name_var = tk.StringVar(value="-")
        self.preview_status_var = tk.StringVar(value="プレビュー未作成")
        self.preview_after_caption_var = tk.StringVar(value="倍率補正のみ / キャンバス処理なし")
        self._pending_output_refresh: str | None = None

        self.output_folder_var = tk.StringVar()
        self.recursive_folder_drop_var = tk.BooleanVar(value=True)
        self.keep_structure_var = tk.BooleanVar(value=False)
        self.extensions_var = tk.StringVar()
        self.mode_var = tk.StringVar(value=MODE_LABELS["manual_scale"])
        self.content_preset_var = tk.StringVar(value=DEFAULT_CONTENT_PRESET_LABEL)
        self.x_scale_var = tk.StringVar()
        self.y_scale_var = tk.StringVar()
        self.canvas_processing_var = tk.StringVar()
        self.save_canvas_aspect_ratio_var = tk.StringVar()
        self.canvas_pad_color_var = tk.StringVar()
        self.output_format_var = tk.StringVar()
        self.suffix_var = tk.StringVar()
        self.jpeg_quality_var = tk.StringVar()
        self.webp_quality_var = tk.StringVar()
        self.interpolation_var = tk.StringVar()
        self.overwrite_var = tk.BooleanVar(value=False)
        self.delete_source_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="待機中")
        self.progress_text_var = tk.StringVar(value="0 / 0 件")
        self.selected_file_name_var = tk.StringVar(value="-")
        self.selected_size_var = tk.StringVar(value="-")
        self.selected_aspect_var = tk.StringVar(value="-")
        self.corrected_size_var = tk.StringVar(value="-")
        self.corrected_aspect_var = tk.StringVar(value="-")
        self.saved_size_var = tk.StringVar(value="-")
        self.saved_aspect_var = tk.StringVar(value="-")

        self._build_ui()
        self._load_config_into_vars(self.config_data)
        self._update_canvas_control_states()
        self.geometry(self.config_data.window_geometry or DEFAULT_WINDOW_GEOMETRY)
        self._register_drop_targets()
        self._bind_var_traces()
        self._schedule_output_refresh()
        self.after(100, self._drain_ui_queue)

        if TKDND_IMPORT_ERROR is not None:
            self._append_log_line("ドラッグ＆ドロップは未有効です。ファイル追加ボタンは利用できます。")

        if PIL_IMPORT_ERROR is not None:
            self._append_log_line(f"Pillow の読み込みに失敗しています: {PIL_IMPORT_ERROR}")

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=3)
        root.rowconfigure(3, weight=1)

        drop_frame = ttk.LabelFrame(root, text="画像追加", padding=12)
        drop_frame.grid(row=0, column=0, sticky="ew")
        drop_frame.columnconfigure(0, weight=1)
        self.drop_label = tk.Label(
            drop_frame,
            text=DROP_MESSAGE,
            relief="groove",
            bd=2,
            padx=16,
            pady=34,
            font=("Yu Gothic UI", 18, "bold"),
            justify="center",
            bg="#f4f7fb",
            fg="#1d2d44",
        )
        self.drop_label.grid(row=0, column=0, sticky="ew")
        self.drop_note_label = ttk.Label(drop_frame, text="")
        self.drop_note_label.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._update_drop_note()

        settings_frame = ttk.LabelFrame(root, text="設定", padding=12)
        settings_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        settings_frame.columnconfigure(0, weight=1)

        general_frame = ttk.Frame(settings_frame)
        general_frame.grid(row=0, column=0, sticky="ew")
        for column in range(6):
            general_frame.columnconfigure(column, weight=1 if column in {1, 3, 5} else 0)

        ttk.Label(general_frame, text="出力フォルダ").grid(row=0, column=0, sticky="w")
        self.output_folder_entry = ttk.Entry(general_frame, textvariable=self.output_folder_var)
        self.output_folder_entry.grid(row=0, column=1, columnspan=4, sticky="ew", padx=(8, 8))
        self.output_folder_button = ttk.Button(general_frame, text="出力フォルダ選択", command=self.select_output_folder)
        self.output_folder_button.grid(row=0, column=5, sticky="ew")

        ttk.Label(general_frame, text="対象拡張子").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.extensions_entry = ttk.Entry(general_frame, textvariable=self.extensions_var)
        self.extensions_entry.grid(row=1, column=1, columnspan=5, sticky="ew", padx=(8, 0), pady=(10, 0))

        group_row = ttk.Frame(settings_frame)
        group_row.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        group_row.columnconfigure(0, weight=1)
        group_row.columnconfigure(1, weight=1)

        content_frame = ttk.LabelFrame(group_row, text="1. 倍率補正", padding=12)
        content_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        for column in range(4):
            content_frame.columnconfigure(column, weight=1 if column % 2 == 1 else 0)
        ttk.Label(content_frame, text="横倍率").grid(row=0, column=0, sticky="w")
        self.x_scale_entry = ttk.Entry(content_frame, textvariable=self.x_scale_var)
        self.x_scale_entry.grid(row=0, column=1, sticky="ew", padx=(8, 12))
        ttk.Label(content_frame, text="縦倍率").grid(row=0, column=2, sticky="w")
        self.y_scale_entry = ttk.Entry(content_frame, textvariable=self.y_scale_var)
        self.y_scale_entry.grid(row=0, column=3, sticky="ew", padx=(8, 0))
        ttk.Label(content_frame, text="プリセット").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.content_preset_combo = ttk.Combobox(
            content_frame,
            textvariable=self.content_preset_var,
            values=list(CONTENT_PRESET_LABELS.keys()),
            state="readonly",
        )
        self.content_preset_combo.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(10, 0))
        self.content_preset_combo.bind("<<ComboboxSelected>>", self._on_content_preset_changed)

        canvas_frame = ttk.LabelFrame(group_row, text="2. 保存時のキャンバス処理", padding=12)
        canvas_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        for column in range(4):
            canvas_frame.columnconfigure(column, weight=1 if column % 2 == 1 else 0)
        ttk.Label(canvas_frame, text="キャンバス処理").grid(row=0, column=0, sticky="w")
        self.canvas_processing_combo = ttk.Combobox(
            canvas_frame,
            textvariable=self.canvas_processing_var,
            values=list(CANVAS_PROCESSING_LABELS.values()),
            state="readonly",
        )
        self.canvas_processing_combo.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(8, 0))
        ttk.Label(canvas_frame, text="保存キャンバス比率").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.save_canvas_aspect_entry = ttk.Entry(canvas_frame, textvariable=self.save_canvas_aspect_ratio_var)
        self.save_canvas_aspect_entry.grid(row=1, column=1, sticky="ew", padx=(8, 12), pady=(10, 0))
        ttk.Label(canvas_frame, text="余白色").grid(row=1, column=2, sticky="w", pady=(10, 0))
        self.canvas_pad_color_combo = ttk.Combobox(
            canvas_frame,
            textvariable=self.canvas_pad_color_var,
            values=list(CANVAS_PAD_COLOR_LABELS.values()),
            state="readonly",
        )
        self.canvas_pad_color_combo.grid(row=1, column=3, sticky="ew", pady=(10, 0))

        save_frame = ttk.LabelFrame(settings_frame, text="保存設定", padding=12)
        save_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        for column in range(6):
            save_frame.columnconfigure(column, weight=1 if column % 2 == 1 else 0)
        ttk.Label(save_frame, text="出力形式").grid(row=0, column=0, sticky="w")
        self.output_format_combo = ttk.Combobox(
            save_frame,
            textvariable=self.output_format_var,
            values=list(OUTPUT_FORMAT_LABELS.values()),
            state="readonly",
        )
        self.output_format_combo.grid(row=0, column=1, sticky="ew", padx=(8, 12))
        ttk.Label(save_frame, text="接尾辞").grid(row=0, column=2, sticky="w")
        self.suffix_entry = ttk.Entry(save_frame, textvariable=self.suffix_var)
        self.suffix_entry.grid(row=0, column=3, sticky="ew", padx=(8, 12))
        ttk.Label(save_frame, text="補間方式").grid(row=0, column=4, sticky="w")
        self.interpolation_combo = ttk.Combobox(
            save_frame,
            textvariable=self.interpolation_var,
            values=list(INTERPOLATION_LABELS.values()),
            state="readonly",
        )
        self.interpolation_combo.grid(row=0, column=5, sticky="ew")
        ttk.Label(save_frame, text="JPEG画質").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.jpeg_quality_entry = ttk.Entry(save_frame, textvariable=self.jpeg_quality_var)
        self.jpeg_quality_entry.grid(row=1, column=1, sticky="ew", padx=(8, 12), pady=(10, 0))
        ttk.Label(save_frame, text="WebP画質").grid(row=1, column=2, sticky="w", pady=(10, 0))
        self.webp_quality_entry = ttk.Entry(save_frame, textvariable=self.webp_quality_var)
        self.webp_quality_entry.grid(row=1, column=3, sticky="ew", padx=(8, 12), pady=(10, 0))

        option_row = ttk.Frame(save_frame)
        option_row.grid(row=1, column=4, columnspan=2, sticky="ew", pady=(10, 0))
        for column in range(3):
            option_row.columnconfigure(column, weight=1)
        self.recursive_folder_drop_check = ttk.Checkbutton(
            option_row,
            text="フォルダドロップを再帰追加",
            variable=self.recursive_folder_drop_var,
        )
        self.recursive_folder_drop_check.grid(row=0, column=0, sticky="w")
        self.keep_structure_check = ttk.Checkbutton(
            option_row,
            text="フォルダ追加時に階層を保持",
            variable=self.keep_structure_var,
        )
        self.keep_structure_check.grid(row=0, column=1, sticky="w")
        self.overwrite_check = ttk.Checkbutton(option_row, text="既存出力を上書き", variable=self.overwrite_var)
        self.overwrite_check.grid(row=0, column=2, sticky="w")
        self.delete_source_check = ttk.Checkbutton(option_row, text="処理後に元画像を削除", variable=self.delete_source_var)
        self.delete_source_check.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.save_config_button = ttk.Button(option_row, text="設定保存", command=self.save_current_config)
        self.save_config_button.grid(row=1, column=2, sticky="e", pady=(6, 0))

        content = ttk.Frame(root)
        content.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)

        list_frame = ttk.LabelFrame(content, text="処理対象リスト", padding=12)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(1, weight=1)

        list_button_frame = ttk.Frame(list_frame)
        list_button_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        for column in range(5):
            list_button_frame.columnconfigure(column, weight=1)
        self.add_files_button = ttk.Button(list_button_frame, text="ファイル追加", command=self.add_files_from_dialog)
        self.add_files_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.add_folder_button = ttk.Button(list_button_frame, text="フォルダから追加", command=self.add_folder_from_dialog)
        self.add_folder_button.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self.remove_selected_button = ttk.Button(list_button_frame, text="選択行を削除", command=self.remove_selected_items)
        self.remove_selected_button.grid(row=0, column=2, sticky="ew", padx=(0, 6))
        self.clear_list_button = ttk.Button(list_button_frame, text="リストをクリア", command=self.clear_items)
        self.clear_list_button.grid(row=0, column=3, sticky="ew", padx=(0, 6))
        self.remove_missing_button = ttk.Button(list_button_frame, text="存在しないファイルを除外", command=self.remove_missing_items)
        self.remove_missing_button.grid(row=0, column=4, sticky="ew")

        columns = ("file_name", "original_size", "aspect_ratio", "status", "output_name")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("file_name", text="ファイル名")
        self.tree.heading("original_size", text="元サイズ")
        self.tree.heading("aspect_ratio", text="現在アスペクト比")
        self.tree.heading("status", text="状態")
        self.tree.heading("output_name", text="出力予定名")
        self.tree.column("file_name", width=280, anchor="w")
        self.tree.column("original_size", width=110, anchor="center")
        self.tree.column("aspect_ratio", width=110, anchor="center")
        self.tree.column("status", width=100, anchor="center")
        self.tree.column("output_name", width=320, anchor="w")
        tree_scroll_y = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        tree_scroll_x = ttk.Scrollbar(list_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        tree_scroll_y.grid(row=1, column=1, sticky="ns")
        tree_scroll_x.grid(row=2, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_selection_changed)

        right_panel = ttk.Frame(content)
        right_panel.grid(row=0, column=1, sticky="nsew")
        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(2, weight=1)

        action_frame = ttk.LabelFrame(right_panel, text="操作", padding=12)
        action_frame.grid(row=0, column=0, sticky="ew")
        for column in range(5):
            action_frame.columnconfigure(column, weight=1)
        self.previous_button = ttk.Button(action_frame, text="前の画像", command=self.select_previous_item)
        self.previous_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.next_button = ttk.Button(action_frame, text="次の画像", command=self.select_next_item)
        self.next_button.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self.refresh_preview_button = ttk.Button(action_frame, text="プレビュー更新", command=self.update_preview)
        self.refresh_preview_button.grid(row=0, column=2, sticky="ew", padx=(0, 6))
        self.start_button = ttk.Button(action_frame, text="処理開始", command=self.start_processing)
        self.start_button.grid(row=0, column=3, sticky="ew", padx=(0, 6))
        self.stop_button = ttk.Button(action_frame, text="停止要求", command=self.request_stop, state="disabled")
        self.stop_button.grid(row=0, column=4, sticky="ew")

        progress_frame = ttk.Frame(action_frame)
        progress_frame.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(10, 0))
        progress_frame.columnconfigure(1, weight=1)
        ttk.Label(progress_frame, text="状態").grid(row=0, column=0, sticky="w")
        ttk.Label(progress_frame, textvariable=self.status_var).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(progress_frame, textvariable=self.progress_text_var).grid(row=0, column=2, sticky="e")
        self.progress_bar = ttk.Progressbar(progress_frame, maximum=1.0, value=0.0)
        self.progress_bar.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        info_frame = ttk.LabelFrame(right_panel, text="現在選択中画像の情報", padding=12)
        info_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        for column in range(4):
            info_frame.columnconfigure(column, weight=1 if column % 2 == 1 else 0)
        ttk.Label(info_frame, text="ファイル名").grid(row=0, column=0, sticky="w")
        ttk.Label(info_frame, textvariable=self.selected_file_name_var).grid(row=0, column=1, sticky="w", padx=(8, 12))
        ttk.Label(info_frame, text="元サイズ").grid(row=0, column=2, sticky="w")
        ttk.Label(info_frame, textvariable=self.selected_size_var).grid(row=0, column=3, sticky="w", padx=(8, 0))
        ttk.Label(info_frame, text="元アスペクト比").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(info_frame, textvariable=self.selected_aspect_var).grid(row=1, column=1, sticky="w", padx=(8, 12), pady=(8, 0))
        ttk.Label(info_frame, text="倍率補正後サイズ").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Label(info_frame, textvariable=self.corrected_size_var).grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Label(info_frame, text="倍率補正後アスペクト比").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Label(info_frame, textvariable=self.corrected_aspect_var).grid(row=2, column=1, sticky="w", padx=(8, 12), pady=(8, 0))
        ttk.Label(info_frame, text="保存サイズ").grid(row=2, column=2, sticky="w", pady=(8, 0))
        ttk.Label(info_frame, textvariable=self.saved_size_var).grid(row=2, column=3, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Label(info_frame, text="保存アスペクト比").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Label(info_frame, textvariable=self.saved_aspect_var).grid(row=3, column=1, sticky="w", padx=(8, 12), pady=(8, 0))

        preview_frame = ttk.LabelFrame(right_panel, text="プレビュー", padding=12)
        preview_frame.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        ttk.Label(
            preview_frame,
            text="プレビュー更新を押すと、左に補正前、右に倍率補正後の画像内容を別ウィンドウで表示します。保存時のキャンバス処理は状態表示で確認できます。",
            justify="left",
        ).grid(row=0, column=0, sticky="nw")

        log_frame = ttk.LabelFrame(root, text="ログ", padding=12)
        log_frame.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, state="disabled", wrap="word", font=("Consolas", 10))
        self.log_text.grid(row=0, column=0, sticky="nsew")

    def _load_config_into_vars(self, config: AppConfig) -> None:
        self.output_folder_var.set(config.output_folder)
        self.recursive_folder_drop_var.set(config.recursive_folder_drop)
        self.keep_structure_var.set(config.keep_folder_structure_when_folder_added)
        self.extensions_var.set(", ".join(config.extensions))
        self.mode_var.set(MODE_LABELS.get(config.mode, MODE_LABELS["manual_scale"]))
        self.content_preset_var.set(normalize_content_preset(config.content_preset, config.x_scale, config.y_scale))
        self.x_scale_var.set(_format_number(config.x_scale))
        self.y_scale_var.set(_format_number(config.y_scale))
        self.canvas_processing_var.set(
            CANVAS_PROCESSING_LABELS.get(config.canvas_processing, CANVAS_PROCESSING_LABELS["none"])
        )
        self.save_canvas_aspect_ratio_var.set(config.save_canvas_aspect_ratio)
        self.canvas_pad_color_var.set(
            CANVAS_PAD_COLOR_LABELS.get(config.canvas_pad_color, CANVAS_PAD_COLOR_LABELS["black"])
        )
        self.output_format_var.set(OUTPUT_FORMAT_LABELS.get(config.output_format, OUTPUT_FORMAT_LABELS["keep_original"]))
        self.suffix_var.set(config.suffix)
        self.jpeg_quality_var.set(str(config.jpeg_quality))
        self.webp_quality_var.set(str(config.webp_quality))
        self.interpolation_var.set(INTERPOLATION_LABELS.get(config.interpolation, INTERPOLATION_LABELS["lanczos"]))
        self.overwrite_var.set(config.overwrite)
        self.delete_source_var.set(config.delete_source)

    def _bind_var_traces(self) -> None:
        watched_vars: list[tk.Variable] = [
            self.output_folder_var,
            self.keep_structure_var,
            self.canvas_processing_var,
            self.save_canvas_aspect_ratio_var,
            self.canvas_pad_color_var,
            self.output_format_var,
            self.suffix_var,
            self.overwrite_var,
        ]
        for variable in watched_vars:
            variable.trace_add("write", lambda *_: self._schedule_output_refresh())
        self.x_scale_var.trace_add("write", lambda *_: self._on_scale_fields_changed())
        self.y_scale_var.trace_add("write", lambda *_: self._on_scale_fields_changed())
        self.canvas_processing_var.trace_add("write", lambda *_: self._update_canvas_control_states())

    def _on_content_preset_changed(self, _event: Any) -> None:
        preset_label = self.content_preset_var.get().strip()
        preset_values = CONTENT_PRESET_LABELS.get(preset_label)
        if preset_values is None:
            return
        x_scale, y_scale = preset_values
        self.x_scale_var.set(_format_number(x_scale))
        self.y_scale_var.set(_format_number(y_scale))

    def _on_scale_fields_changed(self) -> None:
        self._sync_preset_from_scale_fields()
        self._schedule_output_refresh()

    def _sync_preset_from_scale_fields(self) -> None:
        try:
            x_scale = float(self.x_scale_var.get().strip())
            y_scale = float(self.y_scale_var.get().strip())
            if x_scale <= 0 or y_scale <= 0:
                return
        except Exception:
            return
        preset_label = guess_content_preset_label(x_scale, y_scale)
        if self.content_preset_var.get().strip() != preset_label:
            self.content_preset_var.set(preset_label)

    def _update_canvas_control_states(self) -> None:
        processing_key = CANVAS_PROCESSING_LABEL_TO_KEY.get(self.canvas_processing_var.get().strip(), "none")

        if processing_key in {"aspect_ratio_fit", "blur"}:
            self.save_canvas_aspect_entry.configure(state="normal")
        else:
            self.save_canvas_aspect_entry.configure(state="disabled")

        if processing_key in {"original_fit", "aspect_ratio_fit"}:
            self.canvas_pad_color_combo.configure(state="readonly")
        else:
            self.canvas_pad_color_combo.configure(state="disabled")

    def _register_drop_targets(self) -> None:
        if TkinterDnD is None or DND_FILES is None:
            return
        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind("<<Drop>>", self._on_drop)

    def _update_drop_note(self) -> None:
        if TKDND_IMPORT_ERROR is None:
            self.drop_note_label.configure(text="画像ファイルとフォルダのドロップに対応しています。")
        else:
            self.drop_note_label.configure(text=DROP_FALLBACK_MESSAGE)

    def _schedule_output_refresh(self) -> None:
        if self.processing_thread is not None:
            return
        if self._pending_output_refresh is not None:
            try:
                self.after_cancel(self._pending_output_refresh)
            except Exception:
                pass
        self._pending_output_refresh = self.after(150, self._refresh_planned_outputs)

    def _refresh_planned_outputs(self) -> None:
        self._pending_output_refresh = None
        if not self.items:
            return
        try:
            config = self._build_config_from_vars(strict=False)
            assign_output_paths(self.items, config)
            self._refresh_all_tree_rows()
            self._update_selected_info()
        except Exception:
            for item in self.items:
                item.output_name = "-"
                item.output_path = None
            self._refresh_all_tree_rows()

    def select_output_folder(self) -> None:
        selected = filedialog.askdirectory(title="出力フォルダを選択", initialdir=self.output_folder_var.get().strip() or None)
        if selected:
            self.output_folder_var.set(selected)

    def add_files_from_dialog(self) -> None:
        if self.processing_thread is not None:
            return
        paths = filedialog.askopenfilenames(
            title="画像ファイルを追加",
            filetypes=self._build_dialog_filetypes(),
        )
        if not paths:
            return
        self._add_paths([Path(path) for path in paths], source_root=None, added_via_folder=False)

    def add_folder_from_dialog(self) -> None:
        if self.processing_thread is not None:
            return
        selected = filedialog.askdirectory(title="画像フォルダを追加")
        if not selected:
            return
        folder = Path(selected)
        self._add_folder_contents(folder)

    def _on_drop(self, event: Any) -> None:
        if self.processing_thread is not None:
            return
        paths = self._parse_drop_data(str(getattr(event, "data", "")))
        if not paths:
            return
        self._add_mixed_drop_paths(paths)

    def _parse_drop_data(self, raw: str) -> list[Path]:
        if not raw:
            return []
        try:
            parsed = self.tk.splitlist(raw)
        except Exception:
            parsed = [raw]
        results: list[Path] = []
        for item in parsed:
            text = str(item).strip()
            if not text:
                continue
            results.append(Path(text))
        return results

    def _add_mixed_drop_paths(self, paths: list[Path]) -> None:
        file_paths: list[Path] = []
        for path in paths:
            if path.is_dir():
                self._add_folder_contents(path)
            else:
                file_paths.append(path)
        if file_paths:
            self._add_paths(file_paths, source_root=None, added_via_folder=False)

    def _add_folder_contents(self, folder: Path) -> None:
        if not folder.exists():
            self._append_log_line(f"存在しないフォルダのため追加しませんでした: {folder}")
            return
        try:
            config = self._build_config_from_vars(strict=False)
        except Exception:
            config = self.config_data
        image_files = collect_image_files(folder, normalize_extensions(config.extensions), config.recursive_folder_drop)
        if not image_files:
            self._append_log_line(f"フォルダ内に対象画像がありませんでした: {folder}")
            return
        self._add_paths(image_files, source_root=folder, added_via_folder=True)

    def _add_paths(self, paths: list[Path], source_root: Path | None, added_via_folder: bool) -> None:
        if PIL_IMPORT_ERROR is not None or Image is None or ImageOps is None:
            messagebox.showerror(APP_TITLE, f"Pillow の読み込みに失敗しているため画像を追加できません。{PIL_IMPORT_ERROR}")
            return

        added_count = 0
        skipped_count = 0
        for raw_path in paths:
            path = Path(raw_path)
            if not path.exists() or not path.is_file():
                skipped_count += 1
                continue
            if not is_supported_extension(path.suffix, normalize_extensions(self.extensions_var.get().split(","))):
                skipped_count += 1
                continue
            source_key = normalize_path_key(path)
            if source_key in self.source_key_set:
                skipped_count += 1
                continue
            try:
                image_size = read_oriented_image_size(path)
            except (UnidentifiedImageError, OSError) as exc:
                skipped_count += 1
                self._append_log_line(f"画像を読み込めなかったため追加しませんでした: {path.name} ({exc})")
                continue

            self.item_counter += 1
            item = ProcessItem(
                item_id=str(self.item_counter),
                source_path=path,
                source_root=source_root,
                added_via_folder=added_via_folder,
                original_size=image_size,
                original_aspect_text=format_ratio_text(*image_size),
            )
            self.items.append(item)
            self.item_lookup[item.item_id] = item
            self.source_key_set.add(source_key)
            self.tree.insert("", "end", iid=item.item_id, values=self._build_tree_values(item))
            added_count += 1

        if added_count:
            self._schedule_output_refresh()
            self._append_log_line(f"画像を {added_count} 件追加しました。")
            if not self.tree.selection():
                self.tree.selection_set(self.items[0].item_id)
                self.tree.focus(self.items[0].item_id)
                self._update_selected_info()
                self.update_preview(open_window=False)
        if skipped_count:
            self._append_log_line(f"追加対象外の項目を {skipped_count} 件スキップしました。")

    def remove_selected_items(self) -> None:
        if self.processing_thread is not None:
            return
        selected_ids = list(self.tree.selection())
        if not selected_ids:
            return
        removed_count = 0
        for item_id in selected_ids:
            item = self.item_lookup.pop(item_id, None)
            if item is None:
                continue
            self.source_key_set.discard(normalize_path_key(item.source_path))
            self.items = [existing for existing in self.items if existing.item_id != item_id]
            self.tree.delete(item_id)
            removed_count += 1
        if removed_count:
            self._append_log_line(f"選択行を {removed_count} 件削除しました。")
            self._schedule_output_refresh()
            self._select_first_item_if_needed()

    def clear_items(self) -> None:
        if self.processing_thread is not None:
            return
        if not self.items:
            return
        self.items.clear()
        self.item_lookup.clear()
        self.source_key_set.clear()
        self.tree.delete(*self.tree.get_children())
        self._clear_preview()
        self._update_selected_info()
        self._append_log_line("処理対象リストをクリアしました。")

    def remove_missing_items(self) -> None:
        if self.processing_thread is not None:
            return
        missing_ids = [item.item_id for item in self.items if not item.source_path.exists()]
        if not missing_ids:
            self._append_log_line("存在しないファイルはありませんでした。")
            return
        for item_id in missing_ids:
            item = self.item_lookup.pop(item_id, None)
            if item is not None:
                self.source_key_set.discard(normalize_path_key(item.source_path))
        self.items = [item for item in self.items if item.item_id not in set(missing_ids)]
        for item_id in missing_ids:
            if self.tree.exists(item_id):
                self.tree.delete(item_id)
        self._append_log_line(f"存在しないファイルを {len(missing_ids)} 件除外しました。")
        self._schedule_output_refresh()
        self._select_first_item_if_needed()

    def select_previous_item(self) -> None:
        self._select_relative_item(-1)

    def select_next_item(self) -> None:
        self._select_relative_item(1)

    def _select_relative_item(self, delta: int) -> None:
        if not self.items:
            return
        selected_item = self.get_selected_item()
        if selected_item is None:
            target = self.items[0]
        else:
            current_index = next((index for index, item in enumerate(self.items) if item.item_id == selected_item.item_id), 0)
            target = self.items[max(0, min(len(self.items) - 1, current_index + delta))]
        self.tree.selection_set(target.item_id)
        self.tree.focus(target.item_id)
        self.tree.see(target.item_id)
        self._update_selected_info()
        self.update_preview(open_window=False)

    def _select_first_item_if_needed(self) -> None:
        if self.tree.selection():
            self._update_selected_info()
            return
        if not self.items:
            self._clear_preview()
            self._update_selected_info()
            return
        first = self.items[0]
        self.tree.selection_set(first.item_id)
        self.tree.focus(first.item_id)
        self.tree.see(first.item_id)
        self._update_selected_info()
        self.update_preview(open_window=False)

    def get_selected_item(self) -> ProcessItem | None:
        selected_ids = self.tree.selection()
        if not selected_ids:
            return None
        return self.item_lookup.get(selected_ids[0])

    def _on_tree_selection_changed(self, _event: Any) -> None:
        self._update_selected_info()
        if self.preview_window is not None and self.preview_window.winfo_exists():
            self.update_preview(open_window=False)

    def _update_selected_info(self) -> None:
        item = self.get_selected_item()
        if item is None:
            self.selected_file_name_var.set("-")
            self.selected_size_var.set("-")
            self.selected_aspect_var.set("-")
            self.corrected_size_var.set("-")
            self.corrected_aspect_var.set("-")
            self.saved_size_var.set("-")
            self.saved_aspect_var.set("-")
            return

        self.selected_file_name_var.set(item.source_path.name)
        self.selected_size_var.set(format_size(item.original_size))
        self.selected_aspect_var.set(item.original_aspect_text)

        try:
            config = self._build_config_from_vars(strict=False)
            plan = build_output_plan(item.original_size, config)
            self.corrected_size_var.set(format_size(plan["corrected_size"]))
            self.corrected_aspect_var.set(format_ratio_text(*plan["corrected_size"]))
            self.saved_size_var.set(format_size(plan["output_size"]))
            self.saved_aspect_var.set(format_ratio_text(*plan["output_size"]))
        except Exception:
            self.corrected_size_var.set("-")
            self.corrected_aspect_var.set("-")
            self.saved_size_var.set("-")
            self.saved_aspect_var.set("-")

    def update_preview(self, open_window: bool = True) -> None:
        item = self.get_selected_item()
        if item is None:
            self._clear_preview()
            return
        if not open_window and (self.preview_window is None or not self.preview_window.winfo_exists()):
            return
        try:
            config = self._build_config_from_vars(strict=False)
            before_image, after_image, metadata = render_preview_images(item.source_path, config)
            self.preview_before_photo = make_photo_image(before_image, PREVIEW_BOX_SIZE)
            self.preview_after_photo = make_photo_image(after_image, PREVIEW_BOX_SIZE)
            self._ensure_preview_window()
            if self.preview_before_label is not None:
                self.preview_before_label.configure(image=self.preview_before_photo, text="")
            if self.preview_after_label is not None:
                self.preview_after_label.configure(image=self.preview_after_photo, text="")
            self.preview_file_name_var.set(item.source_path.name)
            self.preview_after_caption_var.set(str(metadata["preview_status_text"]))
            self.preview_status_var.set(build_preview_status_text(metadata, config))
            self.corrected_size_var.set(format_size(metadata["corrected_size"]))
            self.corrected_aspect_var.set(format_ratio_text(*metadata["corrected_size"]))
            self.saved_size_var.set(format_size(metadata["output_size"]))
            self.saved_aspect_var.set(format_ratio_text(*metadata["output_size"]))
        except Exception as exc:
            self._clear_preview()
            self.corrected_size_var.set("-")
            self.corrected_aspect_var.set("-")
            self.saved_size_var.set("-")
            self.saved_aspect_var.set("-")
            self._append_log_line(f"プレビュー更新に失敗しました: {item.source_path.name} ({exc})")

    def _clear_preview(self) -> None:
        self.preview_before_photo = None
        self.preview_after_photo = None
        self.preview_file_name_var.set("-")
        self.preview_status_var.set("プレビュー未作成")
        self.preview_after_caption_var.set("倍率補正のみ / キャンバス処理なし")
        if self.preview_before_label is not None:
            self.preview_before_label.configure(image="", text="画像を選択してください")
        if self.preview_after_label is not None:
            self.preview_after_label.configure(image="", text="プレビュー未作成")

    def _ensure_preview_window(self) -> None:
        if self.preview_window is not None and self.preview_window.winfo_exists():
            self.preview_window.deiconify()
            self.preview_window.lift()
            return

        preview_window = tk.Toplevel(self)
        preview_window.title(f"{APP_TITLE} プレビュー")
        preview_window.geometry("1640x860")
        preview_window.minsize(1120, 620)
        preview_window.protocol("WM_DELETE_WINDOW", self._close_preview_window)
        preview_window.columnconfigure(0, weight=1)
        preview_window.rowconfigure(1, weight=1)

        header = ttk.Frame(preview_window, padding=12)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        header.columnconfigure(2, weight=1)
        ttk.Label(header, text="ファイル名").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.preview_file_name_var).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(header, textvariable=self.preview_status_var, justify="left", wraplength=860).grid(row=0, column=2, sticky="ew")

        content = ttk.Frame(preview_window, padding=(12, 0, 12, 12))
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)

        before_frame = ttk.LabelFrame(content, text="補正前プレビュー", padding=8)
        before_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        before_frame.columnconfigure(0, weight=1)
        before_frame.rowconfigure(0, weight=1)
        preview_before_label = ttk.Label(before_frame, text="画像を選択してください", anchor="center")
        preview_before_label.grid(row=0, column=0, sticky="nsew")

        after_frame = ttk.LabelFrame(content, text="倍率補正後プレビュー", padding=8)
        after_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        after_frame.columnconfigure(0, weight=1)
        after_frame.rowconfigure(1, weight=1)
        ttk.Label(after_frame, textvariable=self.preview_after_caption_var, anchor="w").grid(row=0, column=0, sticky="ew", pady=(0, 6))
        preview_after_label = ttk.Label(after_frame, text="プレビュー未作成", anchor="center")
        preview_after_label.grid(row=1, column=0, sticky="nsew")

        self.preview_window = preview_window
        self.preview_before_label = preview_before_label
        self.preview_after_label = preview_after_label

    def _close_preview_window(self) -> None:
        if self.preview_window is not None and self.preview_window.winfo_exists():
            self.preview_window.destroy()
        self.preview_window = None
        self.preview_before_label = None
        self.preview_after_label = None

    def request_stop(self) -> None:
        if self.processing_thread is None:
            return
        self.stop_event.set()
        self.status_var.set("停止要求を受け付けました")
        if self.current_logger is not None:
            self.current_logger.warning("停止要求を受け付けました。現在の画像処理完了後に停止します。")

    def save_current_config(self) -> None:
        try:
            config = self._build_config_from_vars(strict=False)
            config.window_geometry = self.geometry()
            save_config(config)
            self.config_data = config
            self._append_log_line(f"設定を保存しました: {CONFIG_PATH.name}")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"設定保存に失敗しました。{exc}")

    def start_processing(self) -> None:
        if self.processing_thread is not None:
            return
        if not self.items:
            messagebox.showwarning(APP_TITLE, "処理対象リストに画像がありません。")
            return
        try:
            config = self._build_config_from_vars(strict=True)
            config.window_geometry = self.geometry()
            assign_output_paths(self.items, config)
            save_config(config)
            self.config_data = config
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        output_dir = Path(config.output_folder)
        output_dir.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now()
        log_path = output_dir / LOG_FOLDER_NAME / f"aspectfix_{started_at.strftime('%Y%m%d_%H%M%S')}.log"
        report_path = output_dir / f"{REPORT_FILE_PREFIX}{started_at.strftime('%Y%m%d_%H%M%S')}.txt"

        self.stop_event.clear()
        self.current_summary = BatchSummary(
            started_at=started_at,
            total_count=len(self.items),
            log_file_path=log_path,
            report_file_path=report_path,
        )
        self.current_logger = RunLogger(log_path, self._send_ui_message)

        self.status_var.set("処理を開始します")
        self.progress_text_var.set(f"0 / {len(self.items)} 件")
        self.progress_bar.configure(maximum=max(1, len(self.items)), value=0)
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.save_config_button.configure(state="disabled")

        for item in self.items:
            item.status = STATUS_WAITING
            item.error_text = ""
            item.corrected_size = None
            item.corrected_aspect_text = "-"
            item.output_size = None
            item.output_aspect_text = "-"
            item.canvas_status_text = "倍率補正のみ / キャンバス処理なし"
            item.processed_at = None
        self._refresh_all_tree_rows()

        self.processing_thread = threading.Thread(target=self._run_batch, args=(config,), daemon=True)
        self.processing_thread.start()

    def _run_batch(self, config: AppConfig) -> None:
        assert self.current_summary is not None
        assert self.current_logger is not None

        summary = self.current_summary
        logger = self.current_logger
        items_snapshot = list(self.items)

        try:
            logger.info(f"追加された画像数: {len(items_snapshot)}")
            logger.info(f"処理開始時刻: {summary.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(
                f"使用設定: 横倍率={format_scale(config.x_scale)}, 縦倍率={format_scale(config.y_scale)}, "
                f"キャンバス処理={canvas_processing_name(config.canvas_processing)}, "
                f"保存キャンバス比率={config.save_canvas_aspect_ratio}, "
                f"余白色={canvas_pad_color_name(config.canvas_pad_color)}, "
                f"出力形式={output_format_name(config.output_format)}"
            )

            for index, item in enumerate(items_snapshot, start=1):
                if self.stop_event.is_set():
                    summary.stopped = True
                    self._send_ui_message({"kind": "item_status", "item_id": item.item_id, "status": STATUS_STOPPED})
                    break

                if not item.source_path.exists():
                    summary.skip_count += 1
                    logger.warning(f"{item.source_path.name}: 元ファイルが存在しないためスキップしました。")
                    self._send_ui_message(
                        {
                            "kind": "item_result",
                            "item_id": item.item_id,
                            "status": STATUS_SKIPPED,
                            "error_text": "元ファイルが存在しません。",
                        }
                    )
                    self._send_ui_message({"kind": "progress", "current": index, "total": len(items_snapshot)})
                    continue

                self._send_ui_message({"kind": "item_status", "item_id": item.item_id, "status": STATUS_PROCESSING})
                try:
                    output_path = item.output_path
                    if output_path is None:
                        raise RuntimeError("出力予定パスを決定できませんでした。")
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    if config.overwrite and output_path.exists():
                        output_path.unlink()

                    result_image, metadata = render_output_image(item.source_path, config)
                    save_output_image(result_image, output_path, item.source_path, config)

                    if config.delete_source:
                        item.source_path.unlink()

                    summary.success_count += 1
                    logger.info(
                        f"{item.source_path.name}: 完了 / 元サイズ={format_size(metadata['source_size'])} / "
                        f"倍率補正後サイズ={format_size(metadata['corrected_size'])} / "
                        f"出力サイズ={format_size(metadata['output_size'])} / 横倍率={format_scale(config.x_scale)} / "
                        f"縦倍率={format_scale(config.y_scale)} / キャンバス処理={canvas_processing_name(config.canvas_processing)} / "
                        f"保存先={output_path.name}"
                    )
                    self._send_ui_message(
                        {
                            "kind": "item_result",
                            "item_id": item.item_id,
                            "status": STATUS_DONE,
                            "corrected_size": metadata["corrected_size"],
                            "corrected_aspect_text": format_ratio_text(*metadata["corrected_size"]),
                            "output_size": metadata["output_size"],
                            "output_aspect_text": format_ratio_text(*metadata["output_size"]),
                            "canvas_status_text": metadata["preview_status_text"],
                            "error_text": "",
                        }
                    )
                except Exception as exc:
                    summary.failure_count += 1
                    logger.error(
                        f"{item.source_path.name}: 失敗 / 元サイズ={format_size(item.original_size)} / "
                        f"横倍率={format_scale(config.x_scale)} / 縦倍率={format_scale(config.y_scale)} / "
                        f"キャンバス処理={canvas_processing_name(config.canvas_processing)} / "
                        f"エラー={exc}"
                    )
                    self._send_ui_message(
                        {
                            "kind": "item_result",
                            "item_id": item.item_id,
                            "status": STATUS_FAILED,
                            "error_text": str(exc),
                        }
                    )
                self._send_ui_message({"kind": "progress", "current": index, "total": len(items_snapshot)})

            summary.finished_at = datetime.now()
            write_report(summary.report_file_path, summary, items_snapshot, config)
            logger.info(f"成功数: {summary.success_count}")
            logger.info(f"失敗数: {summary.failure_count}")
            logger.info(f"スキップ数: {summary.skip_count}")
            logger.info(f"レポート: {summary.report_file_path}")
            self._send_ui_message({"kind": "finish", "summary": summary})
        except Exception as exc:
            summary.finished_at = datetime.now()
            self._send_ui_message(
                {
                    "kind": "finish",
                    "summary": summary,
                    "fatal_error": f"{exc}{WINDOWS_NEWLINE}{traceback.format_exc()}",
                }
            )

    def _send_ui_message(self, message: dict[str, Any]) -> None:
        self.ui_queue.put(message)

    def _drain_ui_queue(self) -> None:
        while True:
            try:
                message = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_ui_message(message)
        self.after(100, self._drain_ui_queue)

    def _handle_ui_message(self, message: dict[str, Any]) -> None:
        kind = str(message.get("kind", ""))
        if kind == "log":
            self._append_log_line(str(message.get("line", "")))
            return
        if kind == "item_status":
            item = self.item_lookup.get(str(message.get("item_id", "")))
            if item is None:
                return
            item.status = str(message.get("status", item.status))
            self._refresh_tree_row(item)
            return
        if kind == "item_result":
            item = self.item_lookup.get(str(message.get("item_id", "")))
            if item is None:
                return
            item.status = str(message.get("status", item.status))
            item.error_text = str(message.get("error_text", ""))
            corrected_size = message.get("corrected_size")
            if isinstance(corrected_size, tuple):
                item.corrected_size = corrected_size
            corrected_aspect_text = str(message.get("corrected_aspect_text", ""))
            if corrected_aspect_text:
                item.corrected_aspect_text = corrected_aspect_text
            output_size = message.get("output_size")
            if isinstance(output_size, tuple):
                item.output_size = output_size
            output_aspect_text = str(message.get("output_aspect_text", ""))
            if output_aspect_text:
                item.output_aspect_text = output_aspect_text
            canvas_status_text = str(message.get("canvas_status_text", ""))
            if canvas_status_text:
                item.canvas_status_text = canvas_status_text
            item.processed_at = datetime.now()
            self._refresh_tree_row(item)
            if self.get_selected_item() is item:
                self._update_selected_info()
            return
        if kind == "progress":
            current = int(message.get("current", 0))
            total = max(1, int(message.get("total", 1)))
            self.progress_bar.configure(maximum=total, value=min(current, total))
            self.progress_text_var.set(f"{min(current, total)} / {total} 件")
            self.status_var.set(f"処理中 {min(current, total)} / {total} 件")
            return
        if kind == "finish":
            summary = message.get("summary")
            fatal_error = message.get("fatal_error")
            self.processing_thread = None
            self.stop_button.configure(state="disabled")
            self.start_button.configure(state="normal")
            self.save_config_button.configure(state="normal")
            if isinstance(summary, BatchSummary):
                total = max(1, summary.total_count)
                processed = summary.success_count + summary.failure_count + summary.skip_count
                self.progress_bar.configure(maximum=total, value=min(processed, total))
                self.progress_text_var.set(f"{min(processed, total)} / {summary.total_count} 件")
                if fatal_error:
                    self.status_var.set("致命的エラー")
                    messagebox.showerror(APP_TITLE, f"処理が致命的エラーで終了しました。{fatal_error}")
                elif summary.stopped:
                    self.status_var.set("停止完了")
                    messagebox.showinfo(
                        APP_TITLE,
                        WINDOWS_NEWLINE.join(
                            [
                                "停止要求により処理を終了しました。",
                                f"成功: {summary.success_count}",
                                f"失敗: {summary.failure_count}",
                                f"スキップ: {summary.skip_count}",
                                f"ログ: {summary.log_file_path}",
                                f"レポート: {summary.report_file_path}",
                            ]
                        ),
                    )
                else:
                    self.status_var.set("処理完了")
                    messagebox.showinfo(
                        APP_TITLE,
                        WINDOWS_NEWLINE.join(
                            [
                                "処理が完了しました。",
                                f"成功: {summary.success_count}",
                                f"失敗: {summary.failure_count}",
                                f"スキップ: {summary.skip_count}",
                                f"ログ: {summary.log_file_path}",
                                f"レポート: {summary.report_file_path}",
                            ]
                        ),
                    )
            return

    def _append_log_line(self, line: str) -> None:
        if not line:
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + WINDOWS_NEWLINE)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _build_tree_values(self, item: ProcessItem) -> tuple[str, str, str, str, str]:
        return (
            item.source_path.name,
            format_size(item.original_size),
            item.original_aspect_text,
            item.status,
            item.output_name,
        )

    def _refresh_tree_row(self, item: ProcessItem) -> None:
        if self.tree.exists(item.item_id):
            self.tree.item(item.item_id, values=self._build_tree_values(item))

    def _refresh_all_tree_rows(self) -> None:
        for item in self.items:
            self._refresh_tree_row(item)

    def _build_dialog_filetypes(self) -> list[tuple[str, str]]:
        extensions = normalize_extensions(self.extensions_var.get().split(","))
        patterns = [f"*{extension}" for extension in extensions]
        if patterns:
            return [("画像ファイル", " ".join(patterns)), ("すべてのファイル", "*.*")]
        return [("すべてのファイル", "*.*")]

    def _build_config_from_vars(self, strict: bool) -> AppConfig:
        output_folder = self.output_folder_var.get().strip()
        extensions = normalize_extensions(self.extensions_var.get().split(","))
        mode = MODE_LABEL_TO_KEY.get(self.mode_var.get().strip(), "manual_scale")
        content_preset = self.content_preset_var.get().strip() or DEFAULT_CONTENT_PRESET_LABEL
        canvas_processing = CANVAS_PROCESSING_LABEL_TO_KEY.get(self.canvas_processing_var.get().strip(), "none")
        canvas_pad_color = CANVAS_PAD_COLOR_LABEL_TO_KEY.get(self.canvas_pad_color_var.get().strip(), "black")
        output_format = OUTPUT_FORMAT_LABEL_TO_KEY.get(self.output_format_var.get().strip(), "keep_original")
        interpolation = INTERPOLATION_LABEL_TO_KEY.get(self.interpolation_var.get().strip(), "lanczos")
        suffix = self.suffix_var.get().strip()
        save_canvas_aspect_ratio = self.save_canvas_aspect_ratio_var.get().strip()
        x_scale = _safe_float(self.x_scale_var.get(), DEFAULT_X_SCALE)
        y_scale = _safe_float(self.y_scale_var.get(), DEFAULT_Y_SCALE)
        jpeg_quality = _safe_int(self.jpeg_quality_var.get(), 95)
        webp_quality = _safe_int(self.webp_quality_var.get(), 95)

        if strict:
            if PIL_IMPORT_ERROR is not None or Image is None or ImageOps is None:
                raise ValueError(f"Pillow の読み込みに失敗しています。{PIL_IMPORT_ERROR}")
            if not output_folder:
                raise ValueError("出力フォルダを指定してください。")
            if not suffix:
                raise ValueError("接尾辞を指定してください。")
            if any(character in INVALID_FILE_NAME_CHARS for character in suffix):
                raise ValueError("接尾辞に Windows で使えない文字が含まれています。")
            if x_scale <= 0:
                raise ValueError("横倍率は 0 より大きい値にしてください。")
            if y_scale <= 0:
                raise ValueError("縦倍率は 0 より大きい値にしてください。")
            if not extensions:
                raise ValueError("対象拡張子を 1 つ以上指定してください。")
            if canvas_processing in {"aspect_ratio_fit", "blur"}:
                if not save_canvas_aspect_ratio:
                    raise ValueError("保存キャンバス比率を指定してください。")
                parse_aspect_ratio(save_canvas_aspect_ratio)
            if not (1 <= jpeg_quality <= 100):
                raise ValueError("JPEG画質は 1 から 100 の範囲で指定してください。")
            if not (1 <= webp_quality <= 100):
                raise ValueError("WebP画質は 1 から 100 の範囲で指定してください。")
        else:
            if not output_folder:
                output_folder = self.config_data.output_folder
            if not suffix:
                suffix = "_aspectfix"
            if x_scale <= 0:
                x_scale = DEFAULT_X_SCALE
            if y_scale <= 0:
                y_scale = DEFAULT_Y_SCALE
            if not extensions:
                extensions = list(DEFAULT_EXTENSIONS)
            if not save_canvas_aspect_ratio:
                save_canvas_aspect_ratio = "16:9"
            jpeg_quality = _clamp_int(jpeg_quality, 1, 100)
            webp_quality = _clamp_int(webp_quality, 1, 100)

        return AppConfig(
            output_folder=output_folder,
            recursive_folder_drop=self.recursive_folder_drop_var.get(),
            keep_folder_structure_when_folder_added=self.keep_structure_var.get(),
            extensions=extensions,
            mode=mode,
            x_scale=x_scale,
            y_scale=y_scale,
            content_preset=normalize_content_preset(content_preset, x_scale, y_scale),
            canvas_processing=canvas_processing,
            save_canvas_aspect_ratio=save_canvas_aspect_ratio,
            canvas_pad_color=canvas_pad_color,
            output_format=output_format,
            suffix=suffix,
            jpeg_quality=jpeg_quality,
            webp_quality=webp_quality,
            interpolation=interpolation,
            overwrite=self.overwrite_var.get(),
            delete_source=self.delete_source_var.get(),
            window_geometry=self.geometry(),
        )

    def on_close(self) -> None:
        if self.processing_thread is not None:
            if not messagebox.askyesno(APP_TITLE, "処理中です。停止要求を出して終了しますか。"):
                return
            self.stop_event.set()
        try:
            config = self._build_config_from_vars(strict=False)
            config.window_geometry = self.geometry()
            save_config(config)
        except Exception:
            pass
        self._close_preview_window()
        self.destroy()


def ensure_pillow_available() -> None:
    if PIL_IMPORT_ERROR is not None or Image is None or ImageFilter is None or ImageOps is None:
        raise RuntimeError(f"Pillow の読み込みに失敗しました: {PIL_IMPORT_ERROR}")


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        config = AppConfig()
        save_config(config)
        return config
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return AppConfig()
    return AppConfig.from_dict(raw)


def save_config(config: AppConfig) -> None:
    CONFIG_PATH.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + WINDOWS_NEWLINE, encoding="utf-8")


def read_oriented_image_size(path: Path) -> tuple[int, int]:
    ensure_pillow_available()
    assert Image is not None
    assert ImageOps is not None
    with Image.open(path) as image:
        oriented = ImageOps.exif_transpose(image)
        return tuple(oriented.size)


def collect_image_files(folder: Path, extensions: list[str], recursive: bool) -> list[Path]:
    patterns = folder.rglob("*") if recursive else folder.glob("*")
    normalized = set(normalize_extensions(extensions))
    return sorted(
        [path for path in patterns if path.is_file() and path.suffix.lower() in normalized],
        key=lambda path: str(path).lower(),
    )


def normalize_extensions(raw_extensions: object) -> list[str]:
    if isinstance(raw_extensions, str):
        source = [part.strip() for part in raw_extensions.split(",")]
    elif isinstance(raw_extensions, list):
        source = [str(part).strip() for part in raw_extensions]
    else:
        source = []

    results: list[str] = []
    seen: set[str] = set()
    for item in source:
        if not item:
            continue
        extension = item.lower()
        if not extension.startswith("."):
            extension = f".{extension}"
        if extension in seen:
            continue
        seen.add(extension)
        results.append(extension)
    return results or list(DEFAULT_EXTENSIONS)


def is_supported_extension(extension: str, extensions: list[str]) -> bool:
    return extension.lower() in set(normalize_extensions(extensions))


def assign_output_paths(items: list[ProcessItem], config: AppConfig) -> None:
    output_root = Path(config.output_folder)
    reserved: set[str] = set()
    for item in items:
        relative_dir = Path()
        if config.keep_folder_structure_when_folder_added and item.added_via_folder and item.source_root is not None:
            try:
                relative_dir = item.source_path.parent.relative_to(item.source_root)
            except Exception:
                relative_dir = Path()
        extension = determine_output_extension(item.source_path, config.output_format)
        base_relative_path = relative_dir / f"{item.source_path.stem}{config.suffix}{extension}"
        output_path = output_root / base_relative_path
        output_key = normalize_path_key(output_path)
        if config.overwrite and output_key not in reserved:
            chosen_path = output_path
            reserved.add(output_key)
        else:
            chosen_path = make_unique_output_path(output_path, reserved)
        item.output_path = chosen_path
        item.output_name = str(chosen_path.relative_to(output_root)).replace("/", "\\")


def determine_output_extension(source_path: Path, output_format: str) -> str:
    if output_format == "keep_original":
        extension = source_path.suffix.lower()
        return extension if extension in PIL_FORMAT_BY_EXTENSION else ".png"
    if output_format == "jpeg":
        return ".jpg"
    if output_format == "png":
        return ".png"
    if output_format == "webp":
        return ".webp"
    return ".png"


def make_unique_output_path(base_path: Path, reserved: set[str]) -> Path:
    candidate = base_path
    counter = 1
    while True:
        key = normalize_path_key(candidate)
        if key not in reserved and not candidate.exists():
            reserved.add(key)
            return candidate
        candidate = base_path.with_name(f"{base_path.stem}_{counter:03d}{base_path.suffix}")
        counter += 1


def build_output_plan(source_size: tuple[int, int], config: AppConfig) -> dict[str, Any]:
    corrected_size = (
        max(1, int(round(source_size[0] * config.x_scale))),
        max(1, int(round(source_size[1] * config.y_scale))),
    )
    canvas_processing_applied = config.canvas_processing != "none"
    output_size = corrected_size

    if config.canvas_processing in {"original_fit", "original_crop"}:
        output_size = source_size
    elif config.canvas_processing in {"aspect_ratio_fit", "blur"}:
        target_ratio = parse_aspect_ratio(config.save_canvas_aspect_ratio)
        output_size = calculate_ratio_canvas_size(corrected_size, target_ratio)

    return {
        "source_size": source_size,
        "corrected_size": corrected_size,
        "output_size": output_size,
        "canvas_processing_applied": canvas_processing_applied,
        "preview_status_text": preview_status_text_for_mode(config.canvas_processing),
    }


def render_preview_images(source_path: Path, config: AppConfig) -> tuple[Any, Any, dict[str, Any]]:
    ensure_pillow_available()
    before_image, info = load_source_image(source_path)
    plan = build_output_plan(tuple(before_image.size), config)
    corrected_image = before_image.resize(plan["corrected_size"], resample=get_resample_filter(config.interpolation))
    metadata = {
        "source_size": tuple(before_image.size),
        "corrected_size": plan["corrected_size"],
        "output_size": plan["output_size"],
        "canvas_processing_applied": plan["canvas_processing_applied"],
        "preview_status_text": plan["preview_status_text"],
        "original_info": info,
    }
    return before_image.copy(), corrected_image, metadata


def render_output_image(source_path: Path, config: AppConfig) -> tuple[Any, dict[str, Any]]:
    ensure_pillow_available()
    image, info = load_source_image(source_path)
    return build_output_image(image, info, config)


def load_source_image(source_path: Path) -> tuple[Any, dict[str, Any]]:
    ensure_pillow_available()
    assert Image is not None
    assert ImageOps is not None
    with Image.open(source_path) as source:
        info = dict(source.info)
        oriented = ImageOps.exif_transpose(source)
        return oriented.convert("RGB"), info


def build_output_image(image: Any, original_info: dict[str, Any], config: AppConfig) -> tuple[Any, dict[str, Any]]:
    ensure_pillow_available()
    source_size = tuple(image.size)
    plan = build_output_plan(source_size, config)
    resample = get_resample_filter(config.interpolation)
    corrected_image = image.resize(plan["corrected_size"], resample=resample)
    output_image = apply_canvas_processing(image, corrected_image, source_size, config, resample)

    metadata = {
        "source_size": source_size,
        "corrected_size": plan["corrected_size"],
        "output_size": tuple(output_image.size),
        "canvas_processing_applied": plan["canvas_processing_applied"],
        "preview_status_text": plan["preview_status_text"],
        "original_info": original_info,
    }
    return output_image, metadata


def apply_canvas_processing(
    source_image: Any,
    corrected_image: Any,
    source_size: tuple[int, int],
    config: AppConfig,
    resample: Any,
) -> Any:
    ensure_pillow_available()
    assert ImageOps is not None

    if config.canvas_processing == "none":
        return corrected_image
    if config.canvas_processing == "original_crop":
        return ImageOps.fit(corrected_image, source_size, method=resample, centering=(0.5, 0.5))

    if config.canvas_processing == "original_fit":
        canvas_size = source_size
        placed_image = ImageOps.contain(corrected_image, source_size, method=resample)
    elif config.canvas_processing in {"aspect_ratio_fit", "blur"}:
        target_ratio = parse_aspect_ratio(config.save_canvas_aspect_ratio)
        canvas_size = calculate_ratio_canvas_size(tuple(corrected_image.size), target_ratio)
        placed_image = corrected_image
    else:
        canvas_size = tuple(corrected_image.size)
        placed_image = corrected_image

    background = create_canvas_background(corrected_image, canvas_size, config, resample)
    offset_x = (canvas_size[0] - placed_image.size[0]) // 2
    offset_y = (canvas_size[1] - placed_image.size[1]) // 2
    background.paste(placed_image, (offset_x, offset_y))
    return background


def calculate_ratio_canvas_size(content_size: tuple[int, int], target_ratio: float) -> tuple[int, int]:
    width, height = content_size
    current_ratio = width / height
    if abs(current_ratio - target_ratio) < 1e-9:
        return width, height
    if current_ratio < target_ratio:
        return max(1, int(round(height * target_ratio))), height
    return width, max(1, int(round(width / target_ratio)))


def create_canvas_background(corrected_image: Any, canvas_size: tuple[int, int], config: AppConfig, resample: Any) -> Any:
    ensure_pillow_available()
    assert Image is not None
    assert ImageFilter is not None
    assert ImageOps is not None

    if config.canvas_processing != "blur":
        return Image.new("RGB", canvas_size, canvas_pad_color_rgb(config.canvas_pad_color))

    base = ImageOps.fit(corrected_image, canvas_size, method=resample, centering=(0.5, 0.5))
    blur_radius = max(12, int(round(min(canvas_size) / 28)))
    blurred = base.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    overlay = Image.new("RGB", canvas_size, (24, 24, 24))
    return Image.blend(blurred, overlay, 0.14)


def save_output_image(image: Any, output_path: Path, source_path: Path, config: AppConfig) -> None:
    ensure_pillow_available()
    assert Image is not None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    extension = output_path.suffix.lower()
    image_format = PIL_FORMAT_BY_EXTENSION.get(extension, "PNG")
    save_kwargs: dict[str, Any] = {}

    if image_format == "JPEG":
        image = image.convert("RGB")
        save_kwargs["quality"] = config.jpeg_quality
        save_kwargs["subsampling"] = 0
    elif image_format == "WEBP":
        save_kwargs["quality"] = config.webp_quality
        save_kwargs["method"] = 6

    if image_format in {"JPEG", "PNG", "WEBP"}:
        try:
            with Image.open(source_path) as original:
                icc_profile = original.info.get("icc_profile")
                if icc_profile:
                    save_kwargs["icc_profile"] = icc_profile
        except Exception:
            pass

    image.save(output_path, format=image_format, **save_kwargs)


def write_report(report_path: Path | None, summary: BatchSummary, items: list[ProcessItem], config: AppConfig) -> None:
    if report_path is None:
        return
    started_text = summary.started_at.strftime("%Y-%m-%d %H:%M:%S")
    finished_text = (summary.finished_at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "画像アスペクト補正レポート",
        "",
        f"処理開始時刻: {started_text}",
        f"処理終了時刻: {finished_text}",
        f"追加された画像数: {summary.total_count}",
        f"成功数: {summary.success_count}",
        f"失敗数: {summary.failure_count}",
        f"スキップ数: {summary.skip_count}",
        f"停止要求あり: {bool_to_japanese(summary.stopped)}",
        "",
        "使用設定",
        f"出力フォルダ: {config.output_folder}",
        f"フォルダドロップを再帰追加: {bool_to_japanese(config.recursive_folder_drop)}",
        f"フォルダ追加時に階層を保持: {bool_to_japanese(config.keep_folder_structure_when_folder_added)}",
        f"対象拡張子: {', '.join(config.extensions)}",
        f"補正モード: {mode_name(config.mode)}",
        f"プリセット: {config.content_preset}",
        f"横倍率: {format_scale(config.x_scale)}",
        f"縦倍率: {format_scale(config.y_scale)}",
        f"キャンバス処理: {canvas_processing_name(config.canvas_processing)}",
        f"保存キャンバス比率: {config.save_canvas_aspect_ratio}",
        f"余白色: {canvas_pad_color_name(config.canvas_pad_color)}",
        f"出力形式: {output_format_name(config.output_format)}",
        f"接尾辞: {config.suffix}",
        f"JPEG画質: {config.jpeg_quality}",
        f"WebP画質: {config.webp_quality}",
        f"補間方式: {interpolation_name(config.interpolation)}",
        f"既存出力を上書き: {bool_to_japanese(config.overwrite)}",
        f"処理後に元画像を削除: {bool_to_japanese(config.delete_source)}",
        "",
        "各画像の処理結果",
    ]

    if not items:
        lines.append("画像はありません。")
    else:
        for item in items:
            corrected_size_text = format_size(item.corrected_size) if item.corrected_size is not None else "-"
            corrected_aspect_text = item.corrected_aspect_text if item.corrected_aspect_text else "-"
            output_size_text = format_size(item.output_size) if item.output_size is not None else "-"
            output_aspect_text = item.output_aspect_text if item.output_aspect_text else "-"
            output_name = item.output_name or "-"
            error_text = item.error_text or "なし"
            lines.extend(
                [
                    "",
                    f"ファイル名: {item.source_path.name}",
                    f"元ファイル: {item.source_path}",
                    f"状態: {item.status}",
                    f"元サイズ: {format_size(item.original_size)}",
                    f"元アスペクト比: {item.original_aspect_text}",
                    f"倍率補正後サイズ: {corrected_size_text}",
                    f"倍率補正後アスペクト比: {corrected_aspect_text}",
                    f"保存サイズ: {output_size_text}",
                    f"保存アスペクト比: {output_aspect_text}",
                    f"横倍率: {format_scale(config.x_scale)}",
                    f"縦倍率: {format_scale(config.y_scale)}",
                    f"キャンバス処理: {canvas_processing_name(config.canvas_processing)}",
                    f"プレビュー状態: {item.canvas_status_text}",
                    f"出力ファイル: {output_name}",
                    f"エラー内容: {error_text}",
                ]
            )

    report_path.write_text(WINDOWS_NEWLINE.join(lines) + WINDOWS_NEWLINE, encoding="utf-8")


def get_resample_filter(interpolation: str) -> Any:
    resample = RESAMPLE_MAP.get(interpolation)
    if resample is None:
        return RESAMPLE_LANCZOS
    return resample


def parse_aspect_ratio(text: str) -> float:
    raw = text.strip()
    if not raw:
        raise ValueError("保存キャンバス比率を指定してください。")
    if ":" in raw:
        left, right = raw.split(":", 1)
        numerator = float(left.strip())
        denominator = float(right.strip())
    elif "/" in raw:
        left, right = raw.split("/", 1)
        numerator = float(left.strip())
        denominator = float(right.strip())
    else:
        value = float(raw)
        if value <= 0:
            raise ValueError("保存キャンバス比率は 0 より大きい値にしてください。")
        return value
    if numerator <= 0 or denominator <= 0:
        raise ValueError("保存キャンバス比率は 0 より大きい値にしてください。")
    return numerator / denominator


def make_photo_image(image: Any, box_size: tuple[int, int]) -> Any:
    ensure_pillow_available()
    assert ImageTk is not None
    preview = image.copy()
    preview.thumbnail(box_size, resample=RESAMPLE_LANCZOS)
    return ImageTk.PhotoImage(preview)


def format_size(size: tuple[int, int] | None) -> str:
    if size is None:
        return "-"
    return f"{size[0]} x {size[1]}"


def format_ratio_text(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "-"
    return f"{width / height:.4f}"


def normalize_path_key(path: Path) -> str:
    try:
        return str(path.resolve(strict=False)).lower()
    except Exception:
        return str(path.absolute()).lower()


def normalize_choice(value: str, mapping: dict[str, str], default_key: str) -> str:
    if value in mapping:
        return value
    reverse_mapping = {label: key for key, label in mapping.items()}
    return reverse_mapping.get(value, default_key)


def guess_content_preset_label(x_scale: float, y_scale: float) -> str:
    for label, preset in CONTENT_PRESET_LABELS.items():
        if preset is None:
            continue
        if abs(preset[0] - x_scale) < 0.0001 and abs(preset[1] - y_scale) < 0.0001:
            return label
    return CUSTOM_PRESET_LABEL


def normalize_content_preset(value: str, x_scale: float, y_scale: float) -> str:
    if value in CONTENT_PRESET_LABELS:
        return value
    return guess_content_preset_label(x_scale, y_scale)


def normalize_canvas_mode(value: str, data: dict[str, Any]) -> str:
    aliases = {
        "content_only": "none",
        "none": "none",
        "なし": "none",
        "original_fit": "original_fit",
        "元画像サイズに合わせる": "original_fit",
        "元画像サイズに中央配置": "original_fit",
        "original_crop": "original_crop",
        "元画像サイズに中央クロップ": "original_crop",
        "aspect_ratio_fit": "aspect_ratio_fit",
        "16:9キャンバスに配置": "aspect_ratio_fit",
        "保存キャンバス比率に配置": "aspect_ratio_fit",
        "指定比率キャンバスに配置": "aspect_ratio_fit",
        "blur_background": "blur",
        "blur": "blur",
        "ぼかし背景": "blur",
    }
    raw = value.strip()
    mode = aliases.get(raw, "")
    if not mode:
        mode = aliases.get(_legacy_canvas_processing_key(data), "none")
    legacy_fill = _safe_string(data.get("CanvasFillMode", ""))
    if mode == "aspect_ratio_fit" and legacy_fill in {"blur", "ぼかし背景"}:
        return "blur"
    return mode


def preview_status_text_for_mode(mode: str) -> str:
    if mode == "none":
        return "倍率補正のみ / キャンバス処理なし"
    return f"倍率補正後 / キャンバス処理 {canvas_processing_name(mode)}"


def build_preview_status_text(metadata: dict[str, Any], config: AppConfig) -> str:
    lines = [
        metadata["preview_status_text"],
        (
            f"元サイズ {format_size(metadata['source_size'])} / "
            f"倍率補正後サイズ {format_size(metadata['corrected_size'])} / "
            f"横倍率 {format_scale(config.x_scale)} / 縦倍率 {format_scale(config.y_scale)}"
        ),
        (
            f"元比率 {format_ratio_text(*metadata['source_size'])} / "
            f"倍率補正後比率 {format_ratio_text(*metadata['corrected_size'])} / "
            f"キャンバス処理 {canvas_processing_name(config.canvas_processing)}"
        ),
    ]
    if metadata.get("canvas_processing_applied"):
        lines.append(
            f"保存サイズ {format_size(metadata['output_size'])} / 保存比率 {format_ratio_text(*metadata['output_size'])}"
        )
    return WINDOWS_NEWLINE.join(lines)


def canvas_processing_name(mode: str) -> str:
    return CANVAS_PROCESSING_LABELS.get(mode, mode)


def canvas_pad_color_name(color_key: str) -> str:
    return CANVAS_PAD_COLOR_LABELS.get(color_key, color_key)


def canvas_pad_color_rgb(color_key: str) -> tuple[int, int, int]:
    if color_key == "white":
        return (255, 255, 255)
    if color_key == "gray":
        return (96, 96, 96)
    return (0, 0, 0)


def output_format_name(output_format: str) -> str:
    return OUTPUT_FORMAT_LABELS.get(output_format, output_format)


def interpolation_name(interpolation: str) -> str:
    return INTERPOLATION_LABELS.get(interpolation, interpolation)


def mode_name(mode: str) -> str:
    return MODE_LABELS.get(mode, mode)


def _legacy_canvas_processing_key(data: dict[str, Any]) -> str:
    legacy_mode = _safe_string(data.get("OutputCanvasMode", ""))
    if legacy_mode in {"blur_background", "ぼかし背景"}:
        return "blur"
    if legacy_mode:
        return "aspect_ratio_fit"
    if _safe_string(data.get("CanvasProcessing", "")) == "content_only":
        return "none"
    return "none"


def _legacy_canvas_pad_color_key(data: dict[str, Any]) -> str:
    legacy_mode = _safe_string(data.get("OutputCanvasMode", ""))
    if legacy_mode in {"solid_white", CANVAS_PAD_COLOR_LABELS.get("white")}:
        return "white"
    if legacy_mode in {"solid_black", CANVAS_PAD_COLOR_LABELS.get("black")}:
        return "black"
    return "black"


def bool_to_japanese(value: bool) -> str:
    return "はい" if value else "いいえ"


def _safe_string(value: object, default: str = "") -> str:
    if value is None:
        return default
    text = str(value)
    return text if text else default


def _safe_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: object, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _clamp_int(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def _format_number(value: float) -> str:
    return format_scale(value)


def format_scale(value: float) -> str:
    return f"{value:.6f}"


def run_headless_smoke_test() -> int:
    app = AspectFixApp()
    app.update_idletasks()
    app.destroy()
    print(HEADLESS_OK_MESSAGE)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--headless-smoke-test", action="store_true")
    args = parser.parse_args()

    if args.headless_smoke_test:
        return run_headless_smoke_test()

    app = AspectFixApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
