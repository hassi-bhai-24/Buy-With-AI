"""EXIF-stripping image pipeline (spec doc 09, section 3.2).

The uploaded bytes are never stored and never written to disk. They are
opened with Pillow in memory, the pixels are copied into a FRESH image
(so no EXIF/GPS/camera metadata survives), and the fresh image is
re-encoded as RGB JPEG quality 85. The choice of JPEG re-encode for
photos follows the spec's reference pipeline; PNG/WebP uploads are
likewise normalised to JPEG so the stripped output provably carries no
EXIF segment. Only the stripped bytes are ever forwarded (to OCR) or
hashed for the response.

Orientation: any EXIF orientation tag is applied to the pixels
(``ImageOps.exif_transpose``) *before* the fresh-image copy, so the
stripped image is upright without needing the tag.
"""

from __future__ import annotations

import io

try:
    from PIL import Image, ImageOps

    _PIL_AVAILABLE = True
except ImportError:  # pragma: no cover - Pillow is a declared dependency
    Image = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False

PIL_AVAILABLE = _PIL_AVAILABLE

# Formats the upload endpoint accepts, verified from the decoded image
# itself (not just the claimed MIME type).
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def strip_exif(image_bytes: bytes) -> tuple[bytes, dict]:
    """Strip all EXIF/GPS metadata; return (stripped_bytes, info).

    ``info`` is ``{"width", "height", "format": "JPEG",
    "original_format"}``. Raises ``ValueError`` for data Pillow cannot
    decode as an image, and ``RuntimeError`` when Pillow is unavailable.
    """
    if not _PIL_AVAILABLE:
        raise RuntimeError(
            "Pillow is not installed: image stripping is unavailable."
        )
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except Exception as exc:
        raise ValueError("Uploaded file could not be decoded as an image.") from exc
    original_format = image.format
    if original_format not in ALLOWED_FORMATS:
        raise ValueError(f"Unsupported image format: {original_format}")

    # Apply EXIF orientation to the pixels, then discard every tag by
    # rebuilding the pixels into a brand-new image (frombytes carries
    # no info/EXIF dict at all).
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        rgb = background
    elif image.mode == "P":
        rgb = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(rgb, mask=rgb.split()[-1])
        rgb = background
    else:
        rgb = image.convert("RGB")
    clean = Image.frombytes("RGB", rgb.size, rgb.tobytes())
    output = io.BytesIO()
    # exif=b"" makes the absence of metadata explicit in the encoder.
    clean.save(output, format="JPEG", quality=85, exif=b"")
    stripped = output.getvalue()
    return stripped, {
        "width": clean.width,
        "height": clean.height,
        "format": "JPEG",
        "original_format": original_format,
    }
