import asyncio
import base64
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import httpx
from fastapi.testclient import TestClient

from app import main


ADMIN = "00000000-0000-0000-0000-000000000001"
EXHIBITION = "00000000-0000-0000-0000-000000000002"
ARTWORK = "00000000-0000-0000-0000-000000000003"
PNG = (Path(__file__).resolve().parents[2] / "frontend/src/pages/visitor/matisse-daisies.png").read_bytes()
WEBP = base64.b64decode("UklGRjoAAABXRUJQVlA4IC4AAADwAQCdASoCAAEAAUAmJaACdLoB+AAETAAA/q4X/z0zXmD/Jz/6nH5OPycf1lAA")


class CatalogImageTests(unittest.TestCase):
    def setUp(self):
        self.config = main.Settings(_env_file=None, supabase_url="https://storage.test",
                                    supabase_publishable_key="test-key", visitor_image_bucket="catalog")
        self.objects = {}
        self.public = True
        self.exhibition = {"id": EXHIBITION, "name": "Exhibition", "code": "code", "description": "Description"}
        self.artwork = {"id": ARTWORK, "name": "Artwork", "exhibition_id": EXHIBITION, "artist": "", "year": ""}
        self.outbound = []
        config = patch.object(main, "_cached_settings", return_value=self.config)
        config.start()
        self.addCleanup(config.stop)

        async def authenticated_admin(request: main.Request):
            return main.Admin(request, "test.curator.token", {"id": str(UUID(ADMIN))})

        main.app.dependency_overrides[main.require_admin] = authenticated_admin
        self.addCleanup(main.app.dependency_overrides.pop, main.require_admin)
        self.upstream = httpx.AsyncClient(transport=httpx.MockTransport(self.supabase))
        self.addCleanup(lambda: asyncio.run(self.upstream.aclose()))
        self.client = TestClient(main.app)

    def supabase(self, request):
        self.outbound.append(request)
        path = request.url.path
        public_prefix = "/storage/v1/object/public/catalog/"
        upload_prefix = "/storage/v1/object/catalog/"
        if path.startswith(public_prefix):
            stored = self.objects.get(path.removeprefix(public_prefix))
            return httpx.Response(200, content=stored) if self.public and stored else httpx.Response(404)
        if path.startswith(upload_prefix) and request.method == "POST":
            self.assertEqual(request.headers["Authorization"], "Bearer test.curator.token")
            key = path.removeprefix(upload_prefix)
            if key in self.objects:
                return httpx.Response(409)
            self.objects[key] = request.content
            return httpx.Response(201)
        if path in ("/rest/v1/exhibitions", "/rest/v1/artworks"):
            row = self.exhibition if path.endswith("exhibitions") else self.artwork
            if request.method == "PATCH":
                row.update(json.loads(request.content))
            return httpx.Response(200, json=[row])
        if path == "/rest/v1/rpc/visitor_exhibitions":
            return httpx.Response(200, json=[{**self.exhibition, "image_object_key": self.exhibition.get("cover_object_key")}])
        if path == "/rest/v1/rpc/visitor_exhibition":
            return httpx.Response(200, json={**self.exhibition, "image_object_key": self.exhibition.get("cover_object_key"),
                                             "artworks": [self.artwork]})
        if path == "/rest/v1/rpc/visitor_artwork":
            return httpx.Response(200, json={**self.artwork, "exhibition": self.exhibition, "units": []})
        self.fail(f"Unexpected upstream request: {request.method} {path}")

    def upload(self, client, image, mime):
        return client.post("/api/admin/catalog-images", content=image, headers={"Content-Type": mime})

    def test_upload_replace_and_read_the_same_stored_images(self):
        with self.client:
            main.app.state.http = self.upstream
            png = self.upload(self.client, PNG, "image/png")
            self.assertEqual(png.status_code, 201, png.text)
            png_key = png.json()["key"]
            self.assertEqual(self.objects[png_key], PNG)
            exhibition_saved = self.client.put(f"/api/admin/exhibitions/{EXHIBITION}",
                                               json={"name": "Exhibition", "cover_object_key": png_key})
            self.assertEqual(exhibition_saved.status_code, 200, exhibition_saved.text)
            webp = self.upload(self.client, WEBP, "image/webp")
            self.assertEqual(webp.status_code, 201, webp.text)
            webp_key = webp.json()["key"]
            self.assertEqual(self.objects[webp_key], WEBP)
            artwork_path = f"/api/admin/artworks/{ARTWORK}"
            for key in (png_key, webp_key):
                response = self.client.put(artwork_path, json={"name": "Artwork", "exhibition_id": EXHIBITION,
                                                               "image_object_key": key})
                self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(self.upload(self.client, WEBP, "image/webp").json()["key"], webp_key)
        with TestClient(main.app) as reopened:
            main.app.state.http = self.upstream
            admin_cover = reopened.get("/api/admin/exhibitions").json()[0]["image_url"]
            admin_art = reopened.get("/api/admin/artworks").json()[0]["image_url"]
            visitor_catalog = "/api/visitor/exhibitions"
            self.assertEqual(reopened.get(visitor_catalog).json()[0]["image_url"], admin_cover)
            detail = reopened.get(f"{visitor_catalog}/{EXHIBITION}").json()
            self.assertEqual(detail["image_url"], admin_cover)
            self.assertEqual(detail["artworks"][0]["image_url"], admin_art)
            self.assertEqual(reopened.get(f"{visitor_catalog}/{EXHIBITION}/artworks/{ARTWORK}").json()["image_url"], admin_art)
            self.assertTrue(admin_art.endswith(webp_key))

    def test_unconfigured_invalid_and_unreadable_uploads_fail(self):
        with self.client:
            main.app.state.http = self.upstream
            self.config.visitor_image_bucket = " "
            failure = self.upload(self.client, PNG, "image/png")
            self.assertEqual(failure.status_code, 503)
            self.assertIn("VISITOR_IMAGE_BUCKET", failure.json()["detail"])
            self.config.visitor_image_bucket = "catalog"
            self.assertEqual(self.upload(self.client, b"RIFFnot-a-webp", "image/webp").status_code, 422)
            self.assertEqual(self.outbound, [])
            saved = self.upload(self.client, WEBP, "image/webp")
            self.assertEqual(saved.status_code, 201, saved.text)
            key = saved.json()["key"]
            response = self.client.put(f"/api/admin/exhibitions/{EXHIBITION}",
                                       json={"name": "Exhibition", "cover_object_key": key})
            self.assertEqual(response.status_code, 200, response.text)
            self.public = False
            failure = self.upload(self.client, PNG, "image/png")
            self.assertEqual(failure.status_code, 502)
            self.assertNotIn("key", failure.json())
            self.assertEqual(self.exhibition["cover_object_key"], key)
