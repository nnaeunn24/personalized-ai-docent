from urllib.parse import quote


CATALOG_IMAGE_FORMATS = {
    "image/jpeg": ("jpg", b"\xff\xd8\xff"),
    "image/png": ("png", b"\x89PNG\r\n\x1a\n"),
    "image/webp": ("webp", b"RIFF"),
}


def catalog_image_extension(media_type: str, image: bytes | bytearray) -> str | None:
    extension, signature = CATALOG_IMAGE_FORMATS[media_type]
    if not image.startswith(signature):
        return None
    if extension == "webp" and (
        image[8:12] != b"WEBP" or image[12:16] not in (b"VP8 ", b"VP8L", b"VP8X")
        or int.from_bytes(image[4:8], "little") + 8 != len(image)
    ):
        return None
    return extension


def public_catalog_image(config, key: str | None) -> str | None:
    if not key or not config.visitor_image_bucket.strip() or not config.supabase_url or any(
        part in ("", ".", "..") for part in key.split("/")
    ):
        return None
    bucket = quote(config.visitor_image_bucket.strip(), safe="")
    return f"{config.supabase_url.rstrip('/')}/storage/v1/object/public/{bucket}/{quote(key, safe='/')}"
