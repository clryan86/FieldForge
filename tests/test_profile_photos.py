"""Profile photo normalization uses generated fixtures, never personal photos."""

import base64
import random
import struct
import sys
import warnings
import zlib
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from unittest.mock import patch

import pytest

from fieldforge.online.profile_photos import (
    MAX_PHOTO_DIMENSION,
    MAX_PHOTO_ENCODED_CHARS,
    MAX_PHOTO_PIXELS,
    MAX_PHOTO_UPLOAD_BYTES,
    MAX_PROFILE_PHOTO_BYTES,
    PhotoSupportUnavailable,
    ProfilePhotoError,
    normalize_profile_photo,
)


@pytest.fixture
def pillow():
    return pytest.importorskip("PIL.Image", reason="Optional Pillow image support is not installed")


def encoded(data):
    return base64.b64encode(data).decode("ascii")


def image_bytes(image, image_format="PNG", **save_options):
    with BytesIO() as output:
        image.save(output, format=image_format, **save_options)
        return output.getvalue()


def png_chunk(kind, data):
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def png_header(width, height):
    """Huge declarations without allocating or decompressing a huge image."""
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header)
            + png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
            + png_chunk(b"IEND", b""))


@pytest.mark.parametrize("value", [None, 1, b"", b"AAAA", "", "%%%%", "Zg", "Zg===", "Zh==",
                                        " Zg==", "Zg==\n", "Zg==\x00", "Zg==é", "Zg-_=="])
def test_requires_canonical_standard_base64(value):
    with pytest.raises(ProfilePhotoError, match="canonical base64"):
        normalize_profile_photo(value)


@pytest.mark.parametrize("value", [
    b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
    b"<!doctype html><img src=x onerror=alert(1)>",
    b"%PDF-1.7\n", b"GIF89a", b"II*\x00", b"BMpretend image", b"not an image",
])
def test_rejects_unsupported_formats_before_importing_decoder(value):
    with patch.dict(sys.modules, {"PIL": None}):
        with pytest.raises(ProfilePhotoError, match="PNG, JPEG, or WebP"):
            normalize_profile_photo(encoded(value))


def test_rejects_data_urls_and_false_content_type_declarations(pillow):
    source = image_bytes(pillow.new("RGB", (16, 16), "blue"))
    for prefix in ("data:image/png;base64,", "data:image/jpeg;base64,", "data:text/html;base64,"):
        with pytest.raises(ProfilePhotoError, match="canonical base64"):
            normalize_profile_photo(prefix + encoded(source))


def test_rejects_oversized_input_before_decoding_or_loading_pillow():
    # These are distinct limits: the largest allowed base64 length can decode
    # to one or two bytes beyond the binary limit, depending on its padding.
    for value in ("A" * (MAX_PHOTO_ENCODED_CHARS + 1), encoded(b"x" * (MAX_PHOTO_UPLOAD_BYTES + 1))):
        with patch.dict(sys.modules, {"PIL": None}):
            with pytest.raises(ProfilePhotoError, match="1 MiB"):
                normalize_profile_photo(value)


def test_missing_optional_dependency_fails_clearly():
    valid_shape = encoded(png_header(1, 1))
    with patch.dict(sys.modules, {"PIL": None}):
        with pytest.raises(PhotoSupportUnavailable, match="Pillow"):
            normalize_profile_photo(valid_shape)


@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "WEBP"])
def test_supported_formats_become_bounded_center_cropped_png(pillow, image_format):
    if image_format == "WEBP":
        features = pytest.importorskip("PIL.features")
        if not features.check("webp"):
            pytest.skip("This Pillow build lacks WebP support")
    with pillow.new("RGB", (800, 400), "red") as source:
        source.paste("blue", (200, 0, 600, 400))
        result = normalize_profile_photo(encoded(image_bytes(source, image_format)))
    assert len(result) <= MAX_PROFILE_PHOTO_BYTES
    with pillow.open(BytesIO(result)) as photo:
        photo.load()
        assert photo.format == "PNG"
        assert photo.size == (256, 256)
        assert photo.mode == "RGB"
        assert not photo.is_animated
        red, green, blue = photo.getpixel((128, 128))
        assert blue > 200 and red < 30 and green < 30
        assert not photo.info
        assert not photo.getexif()


def test_small_image_is_cropped_without_upscaling_and_retains_transparency(pillow):
    with pillow.new("RGBA", (40, 20), (10, 100, 200, 64)) as source:
        result = normalize_profile_photo(encoded(image_bytes(source)))
    with pillow.open(BytesIO(result)) as photo:
        assert photo.size == (20, 20)
        assert photo.mode == "RGBA"
        red, green, blue, alpha = photo.getpixel((10, 10))
        # Resampling uses premultiplied alpha and can round RGB by one step.
        assert (red, green, blue) == pytest.approx((10, 100, 200), abs=1)
        assert alpha == 64


def test_palette_transparency_becomes_pixel_alpha(pillow):
    with pillow.new("P", (32, 32)) as source:
        source.putpalette([10, 20, 30, 200, 100, 0] + [0] * 762)
        source.paste(1, (16, 0, 32, 32))
        result = normalize_profile_photo(encoded(image_bytes(source, transparency=0)))
    with pillow.open(BytesIO(result)) as photo:
        assert photo.mode == "RGBA"
        assert photo.getpixel((0, 0))[3] == 0
        assert photo.getpixel((31, 0))[3] == 255
        assert not photo.info


def test_exif_orientation_is_applied_before_metadata_is_removed(pillow):
    # A lossless PNG makes all four expected rotated corners exact.
    with pillow.new("RGB", (4, 4), "white") as source:
        source.paste("red", (0, 0, 2, 2))
        source.paste("green", (2, 0, 4, 2))
        source.paste("blue", (0, 2, 2, 4))
        source.paste("black", (2, 2, 4, 4))
        exif = pillow.Exif()
        exif[274] = 6  # Display by rotating 90 degrees clockwise.
        exif[315] = "private photographer"
        result = normalize_profile_photo(encoded(image_bytes(source, exif=exif)))
    with pillow.open(BytesIO(result)) as photo:
        assert photo.getpixel((0, 0)) == (0, 0, 255)
        assert photo.getpixel((3, 0)) == (255, 0, 0)
        assert photo.getpixel((0, 3)) == (0, 0, 0)
        assert photo.getpixel((3, 3)) == (0, 128, 0)
        assert not photo.getexif()
        assert not photo.info


@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "WEBP"])
def test_exif_gps_icc_comments_and_text_cannot_survive_normalization(pillow, image_format):
    if image_format == "WEBP":
        features = pytest.importorskip("PIL.features")
        if not features.check("webp"):
            pytest.skip("This Pillow build lacks WebP support")
    from PIL.PngImagePlugin import PngInfo

    secret = "private-photo-location-and-owner"
    exif = pillow.Exif()
    exif[315] = secret
    exif[34853] = {1: "N", 2: (39.0, 1.0, 1.0), 3: "W", 4: (75.0, 2.0, 2.0)}
    metadata = PngInfo()
    metadata.add_text("Comment", secret)
    metadata.add_text("Description", secret, zip=True)
    metadata.add_itxt("XML:com.adobe.xmp", secret)
    with pillow.new("RGB", (24, 24), "blue") as source:
        data = image_bytes(source, image_format, exif=exif, icc_profile=secret.encode(),
                           comment=secret.encode(), xmp=secret.encode(), pnginfo=metadata,
                           dpi=(300, 300))
    with pillow.open(BytesIO(data)) as original:
        original.load()
        assert original.getexif()[315] == secret
        assert original.getexif().get_ifd(34853)[1] == "N"
        assert original.info.get("icc_profile") == secret.encode()
    result = normalize_profile_photo(encoded(data))
    assert secret.encode() not in result
    with pillow.open(BytesIO(result)) as photo:
        photo.load()
        assert not photo.info
        assert not photo.text
        assert not photo.getexif()


def test_incompressible_rgba_output_is_reduced_to_fit_byte_limit(pillow):
    noise = random.Random(200).randbytes(256 * 256 * 4)
    with pillow.frombytes("RGBA", (256, 256), noise) as source:
        data = image_bytes(source, compress_level=0)
    result = normalize_profile_photo(encoded(data))
    assert len(result) <= MAX_PROFILE_PHOTO_BYTES
    with pillow.open(BytesIO(result)) as photo:
        assert photo.size == (240, 240)
        assert photo.mode == "RGBA"


@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "WEBP"])
def test_truncated_images_are_rejected_including_missing_png_iend_crc(pillow, image_format):
    if image_format == "WEBP":
        features = pytest.importorskip("PIL.features")
        if not features.check("webp"):
            pytest.skip("This Pillow build lacks WebP support")
    with pillow.new("RGB", (24, 24), "blue") as source:
        data = image_bytes(source, image_format)
    for cut in (1, 2, 4, 12, len(data) // 2):
        with pytest.raises(ProfilePhotoError):
            normalize_profile_photo(encoded(data[:-cut]))


def test_valid_png_terminator_does_not_hide_corrupt_pixel_data(pillow):
    with pillow.new("RGB", (24, 24), "blue") as source:
        data = image_bytes(source)
    corrupted = bytearray(data)
    corrupted[data.index(b"IDAT") + 5] ^= 1
    with pytest.raises(ProfilePhotoError, match="could not be decoded"):
        normalize_profile_photo(encoded(corrupted))


def test_png_valid_crc_does_not_hide_invalid_compressed_pixel_stream(pillow):
    data = (b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 24, 24, 8, 2, 0, 0, 0))
            + png_chunk(b"IDAT", b"not a zlib pixel stream") + png_chunk(b"IEND", b""))
    with pytest.raises(ProfilePhotoError, match="could not be decoded"):
        normalize_profile_photo(encoded(data))


@pytest.mark.parametrize("image_format", ["PNG", "WEBP", "MPO"])
def test_animated_and_multiframe_images_are_rejected(pillow, image_format):
    if image_format == "WEBP":
        features = pytest.importorskip("PIL.features")
        if not features.check("webp"):
            pytest.skip("This Pillow build lacks WebP support")
    with pillow.new("RGB", (24, 24), "blue") as first, pillow.new("RGB", (24, 24), "red") as second:
        data = image_bytes(first, image_format, save_all=True, append_images=[second],
                           duration=100, loop=0)
    with pytest.raises(ProfilePhotoError):
        normalize_profile_photo(encoded(data))


def test_single_frame_apng_container_is_also_rejected(pillow):
    data = png_header(1, 1)
    animation_control = png_chunk(b"acTL", struct.pack(">II", 1, 0))
    frame_control = png_chunk(b"fcTL", struct.pack(">IIIIIHHBB", 0, 1, 1, 0, 0, 1, 1, 0, 0))
    data = data[:33] + animation_control + frame_control + data[33:]
    with pillow.open(BytesIO(data)) as original:
        assert original.get_format_mimetype() == "image/apng"
        assert original.n_frames == 1
    with pytest.raises(ProfilePhotoError, match="still photo"):
        normalize_profile_photo(encoded(data))


def test_exact_upload_byte_limit_is_accepted_and_extra_chunk_is_discarded(pillow):
    with pillow.new("RGB", (1, 1), "blue") as source:
        data = image_bytes(source)
    padding = png_chunk(b"ruSt", b"x" * (MAX_PHOTO_UPLOAD_BYTES - len(data) - 12))
    data = data[:-12] + padding + data[-12:]
    assert len(data) == MAX_PHOTO_UPLOAD_BYTES
    result = normalize_profile_photo(encoded(data))
    with pillow.open(BytesIO(result)) as photo:
        assert photo.size == (1, 1)
        assert photo.getpixel((0, 0)) == (0, 0, 255)
        assert not photo.info
    assert len(result) < 1024


def test_exact_dimension_limit_is_accepted(pillow):
    with pillow.new("RGB", (MAX_PHOTO_DIMENSION, 1), "blue") as source:
        result = normalize_profile_photo(encoded(image_bytes(source)))
    with pillow.open(BytesIO(result)) as photo:
        assert photo.size == (1, 1)
        assert photo.getpixel((0, 0)) == (0, 0, 255)


@pytest.mark.parametrize("dimensions", [(4097, 1), (1, 4097), (4000, 3001), (4096, 4096)])
def test_dimension_and_pixel_limits_are_checked_before_loading_pixels(pillow, dimensions):
    assert max(dimensions) > MAX_PHOTO_DIMENSION or dimensions[0] * dimensions[1] > MAX_PHOTO_PIXELS
    with patch.object(pillow.Image, "load", side_effect=AssertionError("must reject before load")):
        with pytest.raises(ProfilePhotoError, match="4096"):
            normalize_profile_photo(encoded(png_header(*dimensions)))


def test_pillow_decompression_bomb_error_is_a_validation_error(pillow):
    with pytest.raises(ProfilePhotoError, match="too many pixels"):
        normalize_profile_photo(encoded(png_header(1_000_000, 1_000_000)))


def test_excess_pixels_are_rejected_even_when_pillows_global_limit_is_disabled(pillow):
    with patch.object(pillow, "MAX_IMAGE_PIXELS", None):
        with pytest.raises(ProfilePhotoError, match="4096"):
            normalize_profile_photo(encoded(png_header(4096, 4096)))
        assert pillow.MAX_IMAGE_PIXELS is None


def test_compressed_png_metadata_bomb_is_rejected(pillow):
    from PIL.PngImagePlugin import MAX_TEXT_CHUNK

    # A small source with a compressed metadata field above Pillow's bound.
    data = (b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + png_chunk(b"zTXt", b"Comment\x00\x00" + zlib.compress(b"x" * (MAX_TEXT_CHUNK + 1)))
            + png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
            + png_chunk(b"IEND", b""))
    assert len(data) < MAX_PHOTO_UPLOAD_BYTES
    with pytest.raises(ProfilePhotoError):
        normalize_profile_photo(encoded(data))


def test_fake_png_signature_does_not_make_jpeg_data_acceptable(pillow):
    with pillow.new("RGB", (24, 24), "red") as source:
        jpeg = image_bytes(source, "JPEG")
    fake = b"\x89PNG\r\n\x1a\n" + jpeg + png_chunk(b"IEND", b"")
    with pytest.raises(ProfilePhotoError):
        normalize_profile_photo(encoded(fake))


def test_webp_container_length_must_match_upload(pillow):
    features = pytest.importorskip("PIL.features")
    if not features.check("webp"):
        pytest.skip("This Pillow build lacks WebP support")
    with pillow.new("RGB", (24, 24), "red") as source:
        data = image_bytes(source, "WEBP")
    for invalid in (data + b"extra", data[:4] + struct.pack("<I", 0) + data[8:]):
        with pytest.raises(ProfilePhotoError, match="WebP"):
            normalize_profile_photo(encoded(invalid))


def test_permissive_global_truncated_image_mode_fails_closed(pillow):
    from PIL import ImageFile

    with pillow.new("RGB", (24, 24), "blue") as source:
        data = encoded(image_bytes(source))
    with patch.object(ImageFile, "LOAD_TRUNCATED_IMAGES", True):
        with pytest.raises(PhotoSupportUnavailable, match="strict image decoding"):
            normalize_profile_photo(data)
        assert ImageFile.LOAD_TRUNCATED_IMAGES is True


def test_concurrent_normalization_does_not_change_decoder_settings(pillow):
    from PIL import ImageFile

    with pillow.new("RGB", (24, 24), "blue") as source:
        data = encoded(image_bytes(source))
    pixels = pillow.MAX_IMAGE_PIXELS
    truncated = ImageFile.LOAD_TRUNCATED_IMAGES
    filters = list(warnings.filters)
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(normalize_profile_photo, [data] * 12))
    assert len(set(results)) == 1
    assert pillow.MAX_IMAGE_PIXELS == pixels
    assert ImageFile.LOAD_TRUNCATED_IMAGES == truncated
    assert warnings.filters == filters
