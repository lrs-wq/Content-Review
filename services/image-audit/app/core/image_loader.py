"""Image loading and validation utilities."""

from __future__ import annotations

import base64
import hashlib
import urllib.request
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from app.core.config import Settings
from app.schemas.moderation import ImageMetadata, ImageModerationRequest


SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP", "BMP"}
FORMAT_TO_MIME = {
    # Pillow format names are normalized to MIME strings for the API response.
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "BMP": "image/bmp",
}


@dataclass(frozen=True)
class LoadedImage:
    """Decoded image plus raw bytes and immutable metadata."""

    bytes_data: bytes
    pil_image: Image.Image
    metadata: ImageMetadata


class ImageLoadError(ValueError):
    """Raised when an upload cannot be safely decoded or accepted."""

    pass


class ImageLoader:
    """Reads image bytes from upload/base64/URL and validates limits before model work."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def load(self, payload: ImageModerationRequest) -> LoadedImage:
        """Decode and validate one image request."""

        raw = self._read_bytes(payload)
        if len(raw) > self.settings.max_image_bytes:
            raise ImageLoadError(f"image_too_large:{len(raw)}>{self.settings.max_image_bytes}")
        if not raw:
            raise ImageLoadError("image_empty")

        try:
            with Image.open(BytesIO(raw)) as image:
                image.load()
                image_format = (image.format or "").upper()
                if image_format not in SUPPORTED_FORMATS:
                    raise ImageLoadError(f"unsupported_image_format:{image_format or 'unknown'}")
                width, height = image.size
                if width <= 0 or height <= 0:
                    raise ImageLoadError("invalid_image_dimensions")
                if width * height > self.settings.max_image_pixels:
                    raise ImageLoadError(f"image_pixels_too_large:{width * height}>{self.settings.max_image_pixels}")

                # Convert once so downstream OpenCV, PIL, and model pipelines see a stable format.
                converted = image.convert("RGB")
                metadata = ImageMetadata(
                    width=width,
                    height=height,
                    format=image_format,
                    mode=image.mode,
                    mime_type=payload.image_mime or FORMAT_TO_MIME.get(image_format, "application/octet-stream"),
                    bytes=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest(),
                )
                return LoadedImage(bytes_data=raw, pil_image=converted, metadata=metadata)
        except UnidentifiedImageError as exc:
            raise ImageLoadError("image_decode_failed") from exc

    def _read_bytes(self, payload: ImageModerationRequest) -> bytes:
        """Choose the first available image source from the request payload."""

        if payload.image_bytes:
            return payload.image_bytes
        if payload.image_base64:
            return self._decode_base64(payload.image_base64)
        if payload.image_url:
            return self._download(payload.image_url)
        raise ImageLoadError("missing_image_source")

    @staticmethod
    def _decode_base64(value: str) -> bytes:
        """Decode raw base64 or a data URL payload."""

        source = value.strip()
        if "," in source and source.lower().startswith("data:"):
            source = source.split(",", 1)[1]
        try:
            return base64.b64decode(source, validate=True)
        except Exception as exc:
            raise ImageLoadError("invalid_image_base64") from exc

    def _download(self, url: str) -> bytes:
        """Download a remote image while respecting the configured byte limit."""

        request = urllib.request.Request(url, headers={"User-Agent": "ContentReviewImageAudit/1.0"})
        with urllib.request.urlopen(request, timeout=10) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > self.settings.max_image_bytes:
                raise ImageLoadError(f"image_too_large:{content_length}>{self.settings.max_image_bytes}")
            return response.read(self.settings.max_image_bytes + 1)
