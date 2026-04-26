from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps


SUPPORTED_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
}

ORIENTATION_TAG = 274
IMAGE_WIDTH_TAG = 256
IMAGE_HEIGHT_TAG = 257
EXIF_PIXEL_X_DIMENSION_TAG = 40962
EXIF_PIXEL_Y_DIMENSION_TAG = 40963


@dataclass
class BatchResult:
    processed: int = 0
    skipped: int = 0
    failed: int = 0


class CropStrategy:
    def determine_crop_left(self, oriented_image: Image.Image) -> int:
        raise NotImplementedError


class FixedCropStrategy(CropStrategy):
    def __init__(self, left_ratio: float) -> None:
        self.left_ratio = left_ratio

    def determine_crop_left(self, oriented_image: Image.Image) -> int:
        return int(oriented_image.width * self.left_ratio)


class FaceGapCropStrategy(CropStrategy):
    def __init__(self, left_ratio: float, face_cascade_path: Path | None = None) -> None:
        self.left_ratio = left_ratio
        self._face_cascade_path = face_cascade_path
        self._cv2 = None
        self._np = None
        self._cascade = None

    def determine_crop_left(self, oriented_image: Image.Image) -> int:
        base_crop_left = int(oriented_image.width * self.left_ratio)
        right_face, left_face = self._detect_target_faces(oriented_image)

        if right_face is None:
            return base_crop_left

        if left_face is not None:
            gap_crop_left = int(((left_face[0] + left_face[2]) + right_face[0]) / 2)
        else:
            gap_crop_left = int(right_face[0] - (right_face[2] * 0.9))

        gap_crop_left = max(0, gap_crop_left)
        return max(base_crop_left, min(gap_crop_left, oriented_image.width - 1))

    def _detect_target_faces(self, oriented_image: Image.Image):
        cv2, np, cascade = self._load_cv_dependencies()

        gray = np.array(oriented_image.convert("L"))
        image_width, image_height = oriented_image.size
        min_face_size = max(120, int(image_width * 0.08))

        detected_faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.05,
            minNeighbors=5,
            minSize=(min_face_size, min_face_size),
        )

        filtered_faces = []
        max_face_size = int(image_width * 0.20)
        max_face_top = int(image_height * 0.42)

        for x, y, width, height in detected_faces:
            if width > max_face_size or height > max_face_size:
                continue
            if y > max_face_top:
                continue
            filtered_faces.append((int(x), int(y), int(width), int(height)))

        if not filtered_faces:
            return None, None

        filtered_faces.sort(key=lambda face: face[0] + (face[2] / 2))

        right_face = None
        for face in filtered_faces:
            center_x = face[0] + (face[2] / 2)
            if center_x >= image_width * 0.5:
                if right_face is None or center_x > right_face[0] + (right_face[2] / 2):
                    right_face = face

        if right_face is None:
            right_face = max(filtered_faces, key=lambda face: face[0] + (face[2] / 2))

        right_face_center = right_face[0] + (right_face[2] / 2)
        left_faces = [
            face
            for face in filtered_faces
            if face[0] + (face[2] / 2) < right_face_center - (image_width * 0.06)
        ]

        left_face = None
        if left_faces:
            left_face = max(left_faces, key=lambda face: face[0] + (face[2] / 2))

        return right_face, left_face

    def _load_cv_dependencies(self):
        if self._cascade is not None:
            return self._cv2, self._np, self._cascade

        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Face-gap mode requires opencv-python-headless and numpy. "
                "Install them with: python -m pip install opencv-python-headless"
            ) from exc

        cascade_source = self._resolve_cascade_source(cv2)
        cascade_path = self._prepare_ascii_cascade_path(cascade_source)
        cascade = cv2.CascadeClassifier(str(cascade_path))
        if cascade.empty():
            raise RuntimeError(f"Failed to load face cascade: {cascade_path}")

        self._cv2 = cv2
        self._np = np
        self._cascade = cascade
        return self._cv2, self._np, self._cascade

    def _resolve_cascade_source(self, cv2) -> Path:
        if self._face_cascade_path is not None:
            if not self._face_cascade_path.exists():
                raise FileNotFoundError(
                    f"Face cascade file does not exist: {self._face_cascade_path}"
                )
            return self._face_cascade_path

        default_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        if not default_path.exists():
            raise FileNotFoundError(f"OpenCV face cascade not found: {default_path}")
        return default_path

    def _prepare_ascii_cascade_path(self, source_path: Path) -> Path:
        cache_dir = Path(__file__).resolve().parent / ".runtime_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached_path = cache_dir / source_path.name

        if not cached_path.exists() or source_path.stat().st_mtime > cached_path.stat().st_mtime:
            cached_path.write_bytes(source_path.read_bytes())

        return cached_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Crop away the left side of images and keep the right-side subject. "
            "Original files are never overwritten."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Input folder that contains the original images.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output folder for cropped images.",
    )
    parser.add_argument(
        "--left-ratio",
        type=float,
        default=0.45,
        help="Ratio of the left side to discard. Default: 0.45",
    )
    parser.add_argument(
        "--mode",
        choices=("fixed", "face-gap"),
        default="fixed",
        help=(
            "Crop mode. 'fixed' uses only --left-ratio. "
            "'face-gap' nudges the crop boundary rightward based on the right-side face position."
        ),
    )
    parser.add_argument(
        "--face-cascade",
        type=Path,
        help="Optional path to an OpenCV Haar cascade XML file for face-gap mode.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files in the output folder.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not args.input.exists():
        raise FileNotFoundError(f"Input folder does not exist: {args.input}")
    if not args.input.is_dir():
        raise NotADirectoryError(f"Input path is not a folder: {args.input}")
    if not (0.0 <= args.left_ratio < 1.0):
        raise ValueError("--left-ratio must be between 0.0 and less than 1.0")

    input_resolved = args.input.resolve()
    output_resolved = args.output.resolve()
    if input_resolved == output_resolved:
        raise ValueError("Input and output folders must be different.")


def iter_image_files(input_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def normalize_exif_dimensions(exif, width: int, height: int) -> bytes | None:
    if not exif:
        return None

    exif[ORIENTATION_TAG] = 1
    exif[IMAGE_WIDTH_TAG] = width
    exif[IMAGE_HEIGHT_TAG] = height
    exif[EXIF_PIXEL_X_DIMENSION_TAG] = width
    exif[EXIF_PIXEL_Y_DIMENSION_TAG] = height
    return exif.tobytes()


def build_save_kwargs(image_format: str | None, output_image, icc_profile, exif_bytes):
    save_kwargs: dict[str, object] = {}
    if image_format:
        save_kwargs["format"] = image_format
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile
    if exif_bytes:
        save_kwargs["exif"] = exif_bytes

    if image_format == "JPEG":
        if output_image.mode not in ("RGB", "L"):
            output_image = output_image.convert("RGB")
        save_kwargs["quality"] = 95
        save_kwargs["subsampling"] = 0
        save_kwargs["optimize"] = True

    return output_image, save_kwargs


def create_crop_strategy(args: argparse.Namespace) -> CropStrategy:
    if args.mode == "face-gap":
        return FaceGapCropStrategy(
            left_ratio=args.left_ratio,
            face_cascade_path=args.face_cascade,
        )
    return FixedCropStrategy(left_ratio=args.left_ratio)


def crop_image_file(source_path: Path, output_path: Path, crop_strategy: CropStrategy) -> None:
    with Image.open(source_path) as source_image:
        image_format = source_image.format
        icc_profile = source_image.info.get("icc_profile")
        exif = source_image.getexif()

        oriented = ImageOps.exif_transpose(source_image)
        width, height = oriented.size
        crop_left = crop_strategy.determine_crop_left(oriented)

        if crop_left >= width:
            raise ValueError(
                f"Crop ratio leaves no pixels to keep for image: {source_path.name}"
            )

        cropped = oriented.crop((crop_left, 0, width, height))
        exif_bytes = normalize_exif_dimensions(exif, cropped.width, cropped.height)
        cropped_to_save, save_kwargs = build_save_kwargs(
            image_format=image_format,
            output_image=cropped,
            icc_profile=icc_profile,
            exif_bytes=exif_bytes,
        )
        cropped_to_save.save(output_path, **save_kwargs)


def run_batch(
    input_dir: Path,
    output_dir: Path,
    crop_strategy: CropStrategy,
    overwrite: bool,
) -> BatchResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    image_files = iter_image_files(input_dir)
    result = BatchResult()

    if not image_files:
        print("No supported image files were found.", file=sys.stderr)
        return result

    for image_path in image_files:
        output_path = output_dir / image_path.name
        if output_path.exists() and not overwrite:
            print(f"SKIP: output already exists: {output_path}")
            result.skipped += 1
            continue

        try:
            crop_image_file(
                source_path=image_path,
                output_path=output_path,
                crop_strategy=crop_strategy,
            )
            print(f"OK  : {image_path.name} -> {output_path.name}")
            result.processed += 1
        except Exception as exc:
            print(f"FAIL: {image_path.name}: {exc}", file=sys.stderr)
            result.failed += 1

    return result


def main() -> int:
    try:
        args = parse_args()
        validate_args(args)
        crop_strategy = create_crop_strategy(args)
        result = run_batch(
            input_dir=args.input,
            output_dir=args.output,
            crop_strategy=crop_strategy,
            overwrite=args.overwrite,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    total = result.processed + result.skipped + result.failed
    print("")
    print(f"Input folder : {args.input}")
    print(f"Output folder: {args.output}")
    print(f"Total files  : {total}")
    print(f"Processed    : {result.processed}")
    print(f"Skipped      : {result.skipped}")
    print(f"Failed       : {result.failed}")

    return 0 if result.failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
