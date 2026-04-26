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


def crop_image_file(source_path: Path, output_path: Path, left_ratio: float) -> None:
    with Image.open(source_path) as source_image:
        image_format = source_image.format
        icc_profile = source_image.info.get("icc_profile")
        exif = source_image.getexif()

        oriented = ImageOps.exif_transpose(source_image)
        width, height = oriented.size
        crop_left = int(width * left_ratio)

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


def run_batch(input_dir: Path, output_dir: Path, left_ratio: float, overwrite: bool) -> BatchResult:
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
                left_ratio=left_ratio,
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
        result = run_batch(
            input_dir=args.input,
            output_dir=args.output,
            left_ratio=args.left_ratio,
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
