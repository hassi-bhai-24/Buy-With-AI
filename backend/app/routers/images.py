"""Image upload: EXIF stripping + optional OCR.

Only the STRIPPED image is ever hashed, OCR'd, or reported. The
original uploaded bytes are held in memory only, are never written to
disk, and are never returned. OCR runs only on the stripped bytes (via
a temporary file holding stripped bytes only, deleted immediately
after). When no ``tesseract`` binary is present, OCR is honestly
reported as unavailable.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..rate_limit import rate_limit
from ..services.guards import sanitize_text
from ..services.image_pipeline import PIL_AVAILABLE, strip_exif

router = APIRouter()

MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_MIME_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
OCR_UNAVAILABLE_NOTE = "OCR unavailable on this server — type the label text."


def _run_ocr(stripped_bytes: bytes) -> tuple[str | None, bool, str]:
    """Run tesseract on the stripped bytes.

    Returns (ocr_text, ocr_available, note). The binary's absence is
    reported honestly; a binary that fails yields no text.
    """
    if shutil.which("tesseract") is None:
        return None, False, OCR_UNAVAILABLE_NOTE
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".jpg", delete=False
        ) as tmp:
            tmp.write(stripped_bytes)
            tmp_path = Path(tmp.name)
        result = subprocess.run(
            ["tesseract", str(tmp_path), "stdout", "--psm", "6"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None, False, "OCR failed on this server — type the label text."
        text = sanitize_text(result.stdout or "", max_length=2000)
        if not text:
            return None, True, "EXIF stripped. No text was read from the image."
        return text, True, "EXIF stripped. OCR text was read from the stripped image."
    except Exception:
        return None, False, "OCR failed on this server — type the label text."
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass


@router.post("/images/upload")
async def upload_image(
    file: UploadFile = File(...),
    _limited: None = Depends(rate_limit),
) -> dict:
    if not PIL_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Image processing is unavailable: Pillow is not installed.",
        )
    raw = await file.read()
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413, detail="Image is larger than the 5 MB limit."
        )
    if (file.content_type or "").lower() not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Only JPEG, PNG and WebP images are accepted.",
        )
    try:
        stripped, info = strip_exif(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    # The original bytes go out of scope here; only `stripped` is used
    # from this point on (hash + OCR).
    sha256 = hashlib.sha256(stripped).hexdigest()
    ocr_text, ocr_available, note = _run_ocr(stripped)
    return {
        "stripped": True,
        "width": info["width"],
        "height": info["height"],
        "format": "JPEG",
        "sha256": sha256,
        "ocr_text": ocr_text,
        "ocr_available": ocr_available,
        "note": note,
    }
