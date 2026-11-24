import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app import main


class ArtworkPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_followup_prompt_does_not_block_saved_artwork_extraction(self):
        artwork_id = uuid4()
        unit_id = str(uuid4())
        unit = {"id": unit_id, "category": "VISUAL"}
        admin = SimpleNamespace(request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(http=None))),
                                token="test.admin.token", rows=AsyncMock(side_effect=[
                                    [{"description": "A red circle."}],
                                    [{"kind": kind, "version": version, "prompt": {"body": body}}
                                     for kind, version, body in (
                                         ("extraction", 3, "Saved extraction"),
                                         ("classification", 5, "Saved classification"),
                                         ("followup", 1, "Saved follow-up"),
                                     )],
                                    [],
                                    [unit],
                                ]))
        extracted = SimpleNamespace(model_dump=lambda: {"content": "A red circle."})
        classified = SimpleNamespace(model_dump=lambda: {"category": "VISUAL"})
        with patch.object(main, "extract_units", AsyncMock(return_value=([extracted], "extractor"))) as extract, \
                patch.object(main, "classify_units", AsyncMock(return_value=([classified], "classifier"))) as classify, \
                patch.object(main, "supabase", AsyncMock(return_value={"unit_ids": [unit_id], "inserted_count": 1})) as store:
            result = await main.extract_artwork_units(artwork_id, admin)
        self.assertEqual(result, {"inserted_count": 1, "units": [unit]})
        self.assertEqual(extract.await_args.args[-1], "Saved extraction")
        self.assertEqual(classify.await_args.args[-1], "Saved classification")
        payload = store.await_args.kwargs["payload"]
        self.assertEqual(store.await_args.args[2], "/rest/v1/rpc/store_prompted_artwork_extraction")
        self.assertEqual(payload["run_data"]["extraction_prompt_version"], 3)
        self.assertEqual(payload["run_data"]["classification_prompt_version"], 5)
        self.assertEqual(payload["extracted_units"], [{"content": "A red circle.", "category": "VISUAL"}])

    async def test_missing_prompt_names_the_kind_before_calling_gemini(self):
        admin = SimpleNamespace(rows=AsyncMock(side_effect=[
            [{"description": "A red circle."}],
            [{"kind": "classification", "version": 1, "prompt": {"body": "Classification"}}],
        ]))
        with patch.object(main, "run_ai_pipeline", AsyncMock()) as run:
            with self.assertRaises(HTTPException) as raised:
                await main.extract_artwork_units(uuid4(), admin)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("Unit Extraction Prompt", raised.exception.detail)
        self.assertIn("AI Settings", raised.exception.detail)
        run.assert_not_awaited()
