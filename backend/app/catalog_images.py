from urllib.parse import quote


def public_catalog_image(config, key: str | None) -> str | None:
    if not key or not config.visitor_image_bucket or any(part in ("", ".", "..") for part in key.split("/")):
        return None
    bucket = quote(config.visitor_image_bucket, safe="")
    return f"{config.supabase_url.rstrip('/')}/storage/v1/object/public/{bucket}/{quote(key, safe='/')}"
