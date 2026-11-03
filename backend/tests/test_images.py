"""Image upload + EXIF-strip tests.

The strip function is unit-tested directly on bytes (asserting no EXIF
remains via Pillow, since the endpoint returns JSON only and never the
stripped bytes), and the API tests assert the response shape, the
stripped flag, the OCR-unavailable path, and the rejection cases.
"""

from __future__ import annotations

import hashlib
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.routers import images
from app.services.image_pipeline import strip_exif

OCR_NOTE = "OCR unavailable on this server — type the label text."


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(images.router, prefix="/api/v1")
    yield TestClient(app)


def _jpeg_with_exif() -> bytes:
    img = Image.new("RGB", (40, 30), color="red")
    exif = Image.Exif()
    exif[271] = "TestCamera"  # Make
    exif[274] = 1  # Orientation
    exif[282] = 72.0  # XResolution
    exif[306] = "2026:01:01 00:00:00"  # DateTime
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def _png_bytes() -> bytes:
    img = Image.new("RGB", (20, 10), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_strip_exif_removes_all_exif_directly():
    original = _jpeg_with_exif()
    assert dict(Image.open(io.BytesIO(original)).getexif())
    assert b"TestCamera" in original

    stripped, info = strip_exif(original)

    assert info == {
        "width": 40,
        "height": 30,
        "format": "JPEG",
        "original_format": "JPEG",
    }
    reopened = Image.open(io.BytesIO(stripped))
    assert reopened.format == "JPEG"
    assert dict(reopened.getexif()) == {}
    assert b"TestCamera" not in stripped
    assert b"Exif" not in stripped
    assert hashlib.sha256(stripped).hexdigest() != hashlib.sha256(original).hexdigest()


def test_strip_exif_rejects_non_image_and_gif():
    with pytest.raises(ValueError):
        strip_exif(b"not an image at all")
    gif = io.BytesIO()
    Image.new("RGB", (10, 10), color="green").save(gif, format="GIF")
    with pytest.raises(ValueError):
        strip_exif(gif.getvalue())


def test_upload_png_returns_stripped_json(client):
    original = _png_bytes()
    response = client.post(
        "/api/v1/images/upload",
        files={"file": ("photo.png", original, "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stripped"] is True
    assert body["width"] == 20
    assert body["height"] == 10
    assert body["format"] == "JPEG"
    assert len(body["sha256"]) == 64
    assert body["sha256"] != hashlib.sha256(original).hexdigest()
    assert body["ocr_available"] is False
    assert body["ocr_text"] is None
    assert body["note"] == OCR_NOTE


def test_upload_exif_jpeg_is_stripped(client):
    response = client.post(
        "/api/v1/images/upload",
        files={"file": ("photo.jpg", _jpeg_with_exif(), "image/jpeg")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stripped"] is True
    assert body["format"] == "JPEG"
    assert body["ocr_available"] is False
    assert body["note"] == OCR_NOTE


def test_upload_ocr_unavailable_when_no_tesseract(client, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *args, **kwargs: None)
    response = client.post(
        "/api/v1/images/upload",
        files={"file": ("photo.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ocr_available"] is False
    assert body["ocr_text"] is None
    assert body["note"] == OCR_NOTE


def test_upload_oversize_rejected(client):
    response = client.post(
        "/api/v1/images/upload",
        files={"file": ("big.jpg", b"\xff\xd8" + b"a" * (5 * 1024 * 1024), "image/jpeg")},
    )
    assert response.status_code == 413, response.text


def test_upload_invalid_types_rejected(client):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
    response = client.post(
        "/api/v1/images/upload",
        files={"file": ("x.svg", svg, "image/svg+xml")},
    )
    assert response.status_code == 415, response.text

    gif = io.BytesIO()
    Image.new("RGB", (10, 10), color="green").save(gif, format="GIF")
    response = client.post(
        "/api/v1/images/upload",
        files={"file": ("x.gif", gif.getvalue(), "image/gif")},
    )
    assert response.status_code == 415, response.text

    response = client.post(
        "/api/v1/images/upload",
        files={"file": ("x.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 415, response.text

    # GIF bytes mislabelled as PNG: MIME passes, Pillow format check fails.
    response = client.post(
        "/api/v1/images/upload",
        files={"file": ("x.png", gif.getvalue(), "image/png")},
    )
    assert response.status_code == 422, response.text
