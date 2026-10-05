"""Turn bounded profile-photo uploads into fresh, metadata-free PNG thumbnails.

Pillow is optional and is imported only when a photo is submitted. This module
never changes Pillow's process-wide decoder limits or truncated-file setting;
its own image bounds apply before pixel decoding. Callers must authenticate and
bound the request body before invoking the normalizer.

Decoder guidance: https://pillow.readthedocs.io/en/stable/handbook/security.html
"""

from __future__ import annotations

import base64
import binascii
import struct
from io import BytesIO

MAX_PHOTO_UPLOAD_BYTES = 1024 * 1024
MAX_PHOTO_ENCODED_CHARS = 4 * ((MAX_PHOTO_UPLOAD_BYTES + 2) // 3)
MAX_PHOTO_DIMENSION = 4096
MAX_PHOTO_PIXELS = 12_000_000
PROFILE_PHOTO_SIZE = 256
MAX_PROFILE_PHOTO_BYTES = 250 * 1024

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_END = b"\x00\x00\x00\x00IEND\xaeB`\x82"


class ProfilePhotoError(ValueError):
    """The submitted photo is unsupported, malformed, or exceeds a limit."""


class PhotoSupportUnavailable(RuntimeError):
    """A required image decoder is missing or configured permissively."""


def _decode_upload(encoded: str) -> bytes:
    if not isinstance(encoded, str) or not encoded:
        raise ProfilePhotoError("A profile photo must contain canonical base64 image data.")
    if len(encoded) > MAX_PHOTO_ENCODED_CHARS:
        raise ProfilePhotoError("Choose a profile photo no larger than 1 MiB.")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ProfilePhotoError("A profile photo must contain canonical base64 image data.") from exc
    if not data or len(data) > MAX_PHOTO_UPLOAD_BYTES:
        raise ProfilePhotoError("Choose a profile photo no larger than 1 MiB.")
    # validate=True still permits some noncanonical padding and unused end bits.
    if base64.b64encode(data).decode("ascii") != encoded:
        raise ProfilePhotoError("A profile photo must contain canonical base64 image data.")
    return data


def _image_format(data: bytes) -> str:
    """Check fixed file signatures; all image parsing is delegated to Pillow."""
    if data.startswith(_PNG_SIGNATURE):
        # Pillow's PNG verify/load may accept a missing final IEND CRC. Requiring
        # the complete fixed terminator also excludes bytes after the image.
        if not data.endswith(_PNG_END):
            raise ProfilePhotoError("The PNG photo is incomplete or malformed.")
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        if not data.endswith(b"\xff\xd9"):
            raise ProfilePhotoError("The JPEG photo is incomplete or malformed.")
        return "JPEG"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        if int.from_bytes(data[4:8], "little") + 8 != len(data):
            raise ProfilePhotoError("The WebP photo is incomplete or malformed.")
        return "WEBP"
    raise ProfilePhotoError("Choose a PNG, JPEG, or WebP profile photo.")


def _check_image(image, expected_format: str) -> None:
    if image.format != expected_format:
        # A JPEG signature can also lead Pillow to identify a multiframe MPO.
        raise ProfilePhotoError("Choose a single PNG, JPEG, or WebP profile photo.")
    width, height = image.size
    if (width < 1 or height < 1 or width > MAX_PHOTO_DIMENSION
            or height > MAX_PHOTO_DIMENSION or width * height > MAX_PHOTO_PIXELS):
        raise ProfilePhotoError("A profile photo must be at most 4096 pixels per side and 12 MP.")
    if (getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) != 1
            or image.get_format_mimetype() == "image/apng"):
        raise ProfilePhotoError("Choose a still photo; animated or multiple-frame images cannot be used.")


def _png_bytes(image) -> bytes:
    with BytesIO() as output:
        image.save(output, format="PNG", optimize=True, exif=b"", icc_profile=None)
        return output.getvalue()


def _clean_thumbnail(image, image_module) -> bytes:
    # Pixel paste into Image.new cannot inherit EXIF/GPS, XMP, PNG text,
    # comments, ICC profiles, DPI, or other source image.info values.
    with image_module.new(image.mode, image.size) as clean:
        clean.paste(image)
        result = _png_bytes(clean)
        if len(result) > MAX_PROFILE_PHOTO_BYTES:
            # Incompressible RGBA pixels can exceed 250 KiB at 256 square.
            # Preserve their transparency while fitting the storage limit.
            side = min(240, clean.width)
            with clean.resize((side, side), image_module.Resampling.LANCZOS) as reduced:
                result = _png_bytes(reduced)
        if len(result) > MAX_PROFILE_PHOTO_BYTES:
            raise ProfilePhotoError("This photo could not be reduced to the supported size.")
        return result


def normalize_profile_photo(encoded: str) -> bytes:
    """Return a still PNG square of at most 256 pixels, without source metadata.

    ``encoded`` must be canonical standard base64, without whitespace or a data
    URL prefix. Only complete PNG, JPEG, and WebP inputs up to 1 MiB, 4096 pixels
    per side, and 12 million total pixels are accepted. EXIF orientation is
    applied before center cropping. Small images are never enlarged, and alpha
    transparency is retained. The returned PNG is at most 250 KiB.

    Raises ProfilePhotoError for invalid input, or PhotoSupportUnavailable if
    the optional Pillow dependency or strict decoding configuration is absent.
    """
    data = _decode_upload(encoded)
    image_format = _image_format(data)
    try:
        from PIL import Image, ImageFile, ImageOps
    except ImportError as exc:
        raise PhotoSupportUnavailable(
            "Profile photo processing requires Pillow>=12.3,<13. "
            "Install photo support and restart the portal."
        ) from exc
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise PhotoSupportUnavailable(
            "Profile photo processing requires strict image decoding. "
            "The portal's Pillow decoder currently allows truncated images."
        )
    try:
        # verify checks the file structure; load on a reopened stream also
        # requires the actual compressed pixel data to decode successfully.
        with BytesIO(data) as stream, Image.open(stream, formats=(image_format,)) as source:
            _check_image(source, image_format)
            source.verify()
        with BytesIO(data) as stream, Image.open(stream, formats=(image_format,)) as source:
            _check_image(source, image_format)
            source.load()
            ImageOps.exif_transpose(source, in_place=True)
            side = min(PROFILE_PHOTO_SIZE, *source.size)
            has_alpha = "A" in source.getbands() or "transparency" in source.info
            with source.convert("RGBA" if has_alpha else "RGB") as pixels:
                with ImageOps.fit(pixels, (side, side), method=Image.Resampling.LANCZOS) as fitted:
                    return _clean_thumbnail(fitted, Image)
    except ProfilePhotoError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ProfilePhotoError("The profile photo has too many pixels.") from exc
    except (OSError, ValueError, TypeError, SyntaxError, EOFError, OverflowError, struct.error) as exc:
        raise ProfilePhotoError("The profile photo could not be decoded as a complete image.") from exc
