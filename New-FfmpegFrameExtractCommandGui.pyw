from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_TITLE = "ffmpeg フレーム抽出コマンド作成 GUI"
WINDOWS_NEWLINE = "\r\n"
VIDEO_FILETYPES = [
    ("Video files", "*.mp4 *.mkv *.mov *.avi *.wmv *.m4v"),
    ("All files", "*.*"),
]
FFMPEG_FILETYPES = [
    ("ffmpeg.exe", "ffmpeg.exe"),
    ("Executable files", "*.exe"),
    ("All files", "*.*"),
]
EXTRACT_MODES = [
    "10秒ごと",
    "5秒ごと",
    "1秒ごと",
    "指定秒ごと",
    "全フレーム",
]
IMAGE_FORMATS = ["jpg", "png"]
SETTINGS_PATH = Path(__file__).with_suffix(".settings.json")


@dataclass
class AppSettings:
    input_path: str = ""
    output_folder: str = ""
    base_name: str = "frame"
    digits: int = 6
    image_format: str = "jpg"
    jpeg_quality: int = 2
    extract_mode: str = "10秒ごと"
    custom_seconds: float = 10.0
    start_position: str = ""
    duration: str = ""
    include_mkdir: bool = True
    overwrite: bool = False
    use_ffmpeg_path: bool = False
    ffmpeg_path: str = "ffmpeg"

    @classmethod
    def from_dict(cls, raw: object) -> "AppSettings":
        data = raw if isinstance(raw, dict) else {}
        return cls(
            input_path=_safe_string(data.get("InputPath", "")),
            output_folder=_safe_string(data.get("OutputFolder", "")),
            base_name=_safe_string(data.get("BaseName", "frame")) or "frame",
            digits=_clamp(_safe_int(data.get("Digits", 6), 6), 1, 10),
            image_format=_safe_choice(data.get("ImageFormat", "jpg"), IMAGE_FORMATS, "jpg"),
            jpeg_quality=_clamp(_safe_int(data.get("JpegQuality", 2), 2), 1, 31),
            extract_mode=_safe_choice(data.get("ExtractMode", "10秒ごと"), EXTRACT_MODES, "10秒ごと"),
            custom_seconds=max(_safe_float(data.get("CustomSeconds", 10.0), 10.0), 0.001),
            start_position=_safe_string(data.get("StartPosition", "")),
            duration=_safe_string(data.get("Duration", "")),
            include_mkdir=_safe_bool(data.get("IncludeMkdir", True)),
            overwrite=_safe_bool(data.get("Overwrite", False)),
            use_ffmpeg_path=_safe_bool(data.get("UseFfmpegPath", False)),
            ffmpeg_path=_safe_string(data.get("FfmpegPath", "ffmpeg")) or "ffmpeg",
        )

    def to_dict(self) -> dict[str, object]:
        raw = asdict(self)
        return {
            "InputPath": raw["input_path"],
            "OutputFolder": raw["output_folder"],
            "BaseName": raw["base_name"],
            "Digits": raw["digits"],
            "ImageFormat": raw["image_format"],
            "JpegQuality": raw["jpeg_quality"],
            "ExtractMode": raw["extract_mode"],
            "CustomSeconds": raw["custom_seconds"],
            "StartPosition": raw["start_position"],
            "Duration": raw["duration"],
            "IncludeMkdir": raw["include_mkdir"],
            "Overwrite": raw["overwrite"],
            "UseFfmpegPath": raw["use_ffmpeg_path"],
            "FfmpegPath": raw["ffmpeg_path"],
        }


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


def build_fps_expression(settings: AppSettings) -> str | None:
    if settings.extract_mode == "10秒ごと":
        return "fps=1/10"
    if settings.extract_mode == "5秒ごと":
        return "fps=1/5"
    if settings.extract_mode == "1秒ごと":
        return "fps=1"
    if settings.extract_mode == "指定秒ごと":
        if settings.custom_seconds <= 0:
            raise ValueError("指定秒ごとの秒数は 0 より大きい値を指定してください。")

        seconds_text = format_decimal(settings.custom_seconds)
        if seconds_text == "1":
            return "fps=1"
        return f"fps=1/{seconds_text}"
    if settings.extract_mode == "全フレーム":
        return None

    raise ValueError("抽出方式の値が不正です。")


def format_decimal(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")


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


def validate_settings(settings: AppSettings) -> None:
    if not settings.input_path:
        raise ValueError("入力動画ファイルを指定してください。")
    if not Path(settings.input_path).is_file():
        raise ValueError("入力動画ファイルが存在しません。")
    if not settings.output_folder:
        raise ValueError("出力フォルダを指定してください。")
    if not settings.base_name:
        raise ValueError("連番ファイル名を入力してください。")
    if settings.extract_mode == "指定秒ごと" and settings.custom_seconds <= 0:
        raise ValueError("指定秒ごとの秒数は 0 より大きい値を指定してください。")
    if settings.use_ffmpeg_path:
        if not settings.ffmpeg_path:
            raise ValueError("ffmpeg パス指定を有効にした場合は、ffmpeg.exe のパスを入力してください。")
        if not Path(settings.ffmpeg_path).is_file():
            raise ValueError("指定された ffmpeg.exe が見つかりません。")


def build_command(settings: AppSettings) -> str:
    validate_settings(settings)
    fps_expression = build_fps_expression(settings)
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
    if settings.duration:
        parts.extend(["-t", quote_powershell_text(settings.duration)])

    parts.extend(["-i", quote_powershell_text(settings.input_path)])

    if fps_expression:
        parts.extend(["-vf", quote_powershell_text(fps_expression)])

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


class FfmpegFrameExtractCommandGui:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("1000x720")
        self.root.minsize(920, 680)

        self.input_path_var = tk.StringVar()
        self.output_folder_var = tk.StringVar()
        self.base_name_var = tk.StringVar(value="frame")
        self.digits_var = tk.IntVar(value=6)
        self.image_format_var = tk.StringVar(value="jpg")
        self.jpeg_quality_var = tk.IntVar(value=2)
        self.extract_mode_var = tk.StringVar(value="10秒ごと")
        self.custom_seconds_var = tk.StringVar(value="10")
        self.start_position_var = tk.StringVar()
        self.duration_var = tk.StringVar()
        self.include_mkdir_var = tk.BooleanVar(value=True)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.use_ffmpeg_path_var = tk.BooleanVar(value=False)
        self.ffmpeg_path_var = tk.StringVar(value="ffmpeg")
        self.status_var = tk.StringVar(value="")

        self.preview_text: tk.Text
        self.command_text: tk.Text
        self.jpeg_quality_spinbox: ttk.Spinbox
        self.custom_seconds_spinbox: ttk.Spinbox
        self.ffmpeg_path_entry: ttk.Entry
        self.ffmpeg_browse_button: ttk.Button

        self._build_layout()
        self._bind_events()
        self._apply_settings(load_settings())
        self.update_option_states()
        self.update_preview()
        self._install_context_menus()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        settings_group = ttk.LabelFrame(self.root, text="抽出条件", padding=10)
        settings_group.grid(row=0, column=0, padx=10, pady=(10, 6), sticky="nsew")
        settings_group.columnconfigure(1, weight=1)
        settings_group.columnconfigure(2, weight=0)

        ttk.Label(settings_group, text="入力動画ファイル").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(settings_group, textvariable=self.input_path_var).grid(row=0, column=1, sticky="ew", padx=(10, 8), pady=4)
        ttk.Button(settings_group, text="参照...", command=self.choose_input_file).grid(row=0, column=2, sticky="ew", pady=4)

        ttk.Label(settings_group, text="出力フォルダ").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(settings_group, textvariable=self.output_folder_var).grid(row=1, column=1, sticky="ew", padx=(10, 8), pady=4)
        ttk.Button(settings_group, text="参照...", command=self.choose_output_folder).grid(row=1, column=2, sticky="ew", pady=4)

        ttk.Label(settings_group, text="連番ファイル名").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(settings_group, textvariable=self.base_name_var).grid(row=2, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=4)

        digits_row = ttk.Frame(settings_group)
        digits_row.grid(row=3, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=4)
        ttk.Label(settings_group, text="連番桁数").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Spinbox(digits_row, from_=1, to=10, width=6, textvariable=self.digits_var).pack(side="left")
        ttk.Label(digits_row, text="例: %06d").pack(side="left", padx=(8, 0))

        format_row = ttk.Frame(settings_group)
        format_row.grid(row=4, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=4)
        ttk.Label(settings_group, text="画像形式").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Combobox(
            format_row,
            width=8,
            state="readonly",
            values=IMAGE_FORMATS,
            textvariable=self.image_format_var,
        ).pack(side="left")
        ttk.Label(format_row, text="JPG品質").pack(side="left", padx=(20, 6))
        self.jpeg_quality_spinbox = ttk.Spinbox(
            format_row,
            from_=1,
            to=31,
            width=6,
            textvariable=self.jpeg_quality_var,
        )
        self.jpeg_quality_spinbox.pack(side="left")
        ttk.Label(format_row, text="q:v は小さいほど高画質 (2 推奨)").pack(side="left", padx=(8, 0))

        extract_row = ttk.Frame(settings_group)
        extract_row.grid(row=5, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=4)
        ttk.Label(settings_group, text="抽出方式").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Combobox(
            extract_row,
            width=12,
            state="readonly",
            values=EXTRACT_MODES,
            textvariable=self.extract_mode_var,
        ).pack(side="left")
        ttk.Label(extract_row, text="指定秒").pack(side="left", padx=(20, 6))
        self.custom_seconds_spinbox = ttk.Spinbox(
            extract_row,
            from_=0.001,
            to=86400,
            increment=0.5,
            width=8,
            textvariable=self.custom_seconds_var,
        )
        self.custom_seconds_spinbox.pack(side="left")
        ttk.Label(extract_row, text="秒").pack(side="left", padx=(8, 0))

        ttk.Label(settings_group, text="開始位置").grid(row=6, column=0, sticky="w", pady=4)
        ttk.Entry(settings_group, textvariable=self.start_position_var).grid(row=6, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=4)

        ttk.Label(settings_group, text="抽出時間").grid(row=7, column=0, sticky="w", pady=4)
        ttk.Entry(settings_group, textvariable=self.duration_var).grid(row=7, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=4)

        options_row = ttk.Frame(settings_group)
        options_row.grid(row=8, column=1, columnspan=2, sticky="w", padx=(10, 0), pady=4)
        ttk.Label(settings_group, text="オプション").grid(row=8, column=0, sticky="nw", pady=4)
        ttk.Checkbutton(options_row, text="出力フォルダ作成コマンドを付ける", variable=self.include_mkdir_var).pack(side="left")
        ttk.Checkbutton(options_row, text="上書き -y を付ける", variable=self.overwrite_var).pack(side="left", padx=(16, 0))

        ffmpeg_row = ttk.Frame(settings_group)
        ffmpeg_row.grid(row=9, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=4)
        ffmpeg_row.columnconfigure(1, weight=1)
        ttk.Label(settings_group, text="ffmpeg パス").grid(row=9, column=0, sticky="w", pady=4)
        ttk.Checkbutton(
            ffmpeg_row,
            text="ffmpeg.exe のフルパスを指定する",
            variable=self.use_ffmpeg_path_var,
        ).grid(row=0, column=0, sticky="w")
        self.ffmpeg_path_entry = ttk.Entry(ffmpeg_row, textvariable=self.ffmpeg_path_var)
        self.ffmpeg_path_entry.grid(row=0, column=1, sticky="ew", padx=(10, 8))
        self.ffmpeg_browse_button = ttk.Button(ffmpeg_row, text="参照...", command=self.choose_ffmpeg_file)
        self.ffmpeg_browse_button.grid(row=0, column=2, sticky="ew")

        preview_group = ttk.LabelFrame(self.root, text="ファイル名プレビュー", padding=10)
        preview_group.grid(row=1, column=0, padx=10, pady=6, sticky="nsew")
        preview_group.columnconfigure(0, weight=1)
        preview_group.rowconfigure(0, weight=1)
        self.preview_text = tk.Text(preview_group, height=5, wrap="none", font=("Consolas", 10))
        self.preview_text.grid(row=0, column=0, sticky="nsew")
        preview_scroll = ttk.Scrollbar(preview_group, orient="vertical", command=self.preview_text.yview)
        preview_scroll.grid(row=0, column=1, sticky="ns")
        self.preview_text.configure(yscrollcommand=preview_scroll.set)

        command_group = ttk.LabelFrame(self.root, text="生成コマンド", padding=10)
        command_group.grid(row=2, column=0, padx=10, pady=6, sticky="nsew")
        command_group.columnconfigure(0, weight=1)
        command_group.rowconfigure(1, weight=1)
        ttk.Label(command_group, text="PowerShell にそのまま貼り付けて実行できる形式で出力します。").grid(
            row=0,
            column=0,
            sticky="w",
            pady=(0, 8),
        )
        self.command_text = tk.Text(command_group, wrap="none", font=("Consolas", 10))
        self.command_text.grid(row=1, column=0, sticky="nsew")
        command_y_scroll = ttk.Scrollbar(command_group, orient="vertical", command=self.command_text.yview)
        command_y_scroll.grid(row=1, column=1, sticky="ns")
        command_x_scroll = ttk.Scrollbar(command_group, orient="horizontal", command=self.command_text.xview)
        command_x_scroll.grid(row=2, column=0, sticky="ew")
        self.command_text.configure(yscrollcommand=command_y_scroll.set, xscrollcommand=command_x_scroll.set)

        bottom_frame = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        bottom_frame.grid(row=3, column=0, sticky="ew")
        bottom_frame.columnconfigure(0, weight=1)

        ttk.Label(bottom_frame, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

        button_row = ttk.Frame(bottom_frame)
        button_row.grid(row=0, column=1, sticky="e")
        ttk.Button(button_row, text="コマンド生成", command=self.generate_command).pack(side="left")
        ttk.Button(button_row, text="コピー", command=self.copy_command).pack(side="left", padx=(8, 0))
        ttk.Button(button_row, text="生成してコピー", command=self.generate_and_copy).pack(side="left", padx=(8, 0))
        ttk.Button(button_row, text="実行", command=self.execute_command).pack(side="left", padx=(8, 0))
        ttk.Button(button_row, text="クリア", command=self.clear_form).pack(side="left", padx=(8, 0))
        ttk.Button(button_row, text="閉じる", command=self.on_close).pack(side="left", padx=(8, 0))

    def _bind_events(self) -> None:
        tracked_vars = [
            self.input_path_var,
            self.output_folder_var,
            self.base_name_var,
            self.digits_var,
            self.image_format_var,
            self.extract_mode_var,
            self.custom_seconds_var,
            self.use_ffmpeg_path_var,
        ]
        for variable in tracked_vars:
            variable.trace_add("write", self._on_settings_changed)

    def _on_settings_changed(self, *_args: object) -> None:
        self.update_option_states()
        self.update_preview()

    def _apply_settings(self, settings: AppSettings) -> None:
        self.input_path_var.set(settings.input_path)
        self.output_folder_var.set(settings.output_folder)
        self.base_name_var.set(settings.base_name)
        self.digits_var.set(settings.digits)
        self.image_format_var.set(settings.image_format)
        self.jpeg_quality_var.set(settings.jpeg_quality)
        self.extract_mode_var.set(settings.extract_mode)
        self.custom_seconds_var.set(format_decimal(settings.custom_seconds))
        self.start_position_var.set(settings.start_position)
        self.duration_var.set(settings.duration)
        self.include_mkdir_var.set(settings.include_mkdir)
        self.overwrite_var.set(settings.overwrite)
        self.use_ffmpeg_path_var.set(settings.use_ffmpeg_path)
        self.ffmpeg_path_var.set(settings.ffmpeg_path)

    def collect_settings(self) -> AppSettings:
        return AppSettings(
            input_path=self.input_path_var.get().strip(),
            output_folder=self.output_folder_var.get().strip(),
            base_name=self.base_name_var.get().strip(),
            digits=_clamp(_safe_int(self.digits_var.get(), 6), 1, 10),
            image_format=_safe_choice(self.image_format_var.get(), IMAGE_FORMATS, "jpg"),
            jpeg_quality=_clamp(_safe_int(self.jpeg_quality_var.get(), 2), 1, 31),
            extract_mode=_safe_choice(self.extract_mode_var.get(), EXTRACT_MODES, "10秒ごと"),
            custom_seconds=_safe_float(self.custom_seconds_var.get(), 0.0),
            start_position=self.start_position_var.get().strip(),
            duration=self.duration_var.get().strip(),
            include_mkdir=self.include_mkdir_var.get(),
            overwrite=self.overwrite_var.get(),
            use_ffmpeg_path=self.use_ffmpeg_path_var.get(),
            ffmpeg_path=self.ffmpeg_path_var.get().strip(),
        )

    def update_option_states(self) -> None:
        jpeg_state = "normal" if self.image_format_var.get() == "jpg" else "disabled"
        custom_state = "normal" if self.extract_mode_var.get() == "指定秒ごと" else "disabled"
        ffmpeg_state = "normal" if self.use_ffmpeg_path_var.get() else "disabled"

        self.jpeg_quality_spinbox.configure(state=jpeg_state)
        self.custom_seconds_spinbox.configure(state=custom_state)
        self.ffmpeg_path_entry.configure(state=ffmpeg_state)
        self.ffmpeg_browse_button.configure(state=ffmpeg_state)

    def update_preview(self) -> None:
        settings = self.collect_settings()
        if not settings.base_name:
            settings.base_name = "frame"
        lines = build_preview_lines(settings)
        self._replace_text(self.preview_text, WINDOWS_NEWLINE.join(lines), readonly=True)

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
            title="出力フォルダを選択してください",
            initialdir=initial_dir,
            mustexist=False,
        )
        if selected:
            self.output_folder_var.set(str(Path(selected)))

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

    def generate_command(self) -> str | None:
        settings = self.collect_settings()
        if (
            settings.output_folder
            and not Path(settings.output_folder).exists()
            and not settings.include_mkdir
        ):
            proceed = messagebox.askyesno(
                "確認",
                "出力フォルダが存在しません。\n"
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
        self.status_var.set("コマンドを生成しました。")

        try:
            save_settings(settings)
        except Exception as exc:
            messagebox.showerror("設定保存", f"設定ファイルの保存に失敗しました。\n\n{exc}", parent=self.root)

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

    def _install_context_menus(self) -> None:
        self.root.bind_class("Entry", "<Button-3>", self._show_entry_context_menu, add="+")
        self.root.bind_class("TEntry", "<Button-3>", self._show_entry_context_menu, add="+")
        self.root.bind_class("TCombobox", "<Button-3>", self._show_entry_context_menu, add="+")
        self.root.bind_class("TSpinbox", "<Button-3>", self._show_entry_context_menu, add="+")
        self.root.bind_class("Text", "<Button-3>", self._show_text_context_menu, add="+")

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

    def clear_form(self) -> None:
        self._apply_settings(AppSettings())
        self._replace_text(self.command_text, "", readonly=False)
        self.update_option_states()
        self.update_preview()
        self.status_var.set("入力内容を初期値へ戻しました。")

    def on_close(self) -> None:
        try:
            save_settings(self.collect_settings())
        except Exception as exc:
            messagebox.showerror("設定保存", f"設定ファイルの保存に失敗しました。\n\n{exc}", parent=self.root)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()

    @staticmethod
    def _replace_text(widget: tk.Text, text: str, readonly: bool) -> None:
        previous_state = widget.cget("state")
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state="disabled" if readonly else "normal")
        if previous_state == "disabled" and not readonly:
            widget.configure(state="normal")

    def get_command_text(self) -> str:
        return self.command_text.get("1.0", tk.END).strip()

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


def main() -> int:
    app = FfmpegFrameExtractCommandGui()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
