from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from solar.config import settings
from solar.database import (
    financial_formulas,
    init_db,
    save_ratio_snapshot,
)
from solar.routes.web import router


class FormulaRouteTests(unittest.TestCase):
    def setUp(self):
        self.old_db_path = settings.db_path
        self.old_secret = settings.app_secret
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        settings.db_path = self.db_path
        settings.app_secret = "test-dashboard-token"
        asyncio.run(init_db())
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        settings.db_path = self.old_db_path
        settings.app_secret = self.old_secret
        os.unlink(self.db_path)

    def test_formula_dashboard_requires_authentication(self):
        response = self.client.get("/solar/formulas")
        self.assertEqual(response.status_code, 403)

    def test_authenticated_formula_dashboard_renders_saved_formulas(self):
        response = self.client.get(
            "/solar/formulas?token=test-dashboard-token"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("operating_cf - capex", response.text)
        self.assertIn("Only arithmetic is accepted", response.text)

    def test_authenticated_formula_update_persists(self):
        response = self.client.post(
            "/solar/formulas",
            data={
                "token": "test-dashboard-token",
                "formula_key": "free_cash_flow",
                "expression": "operating_cf - capex + 1",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        formulas = asyncio.run(financial_formulas())
        saved = {formula["key"]: formula["expression"] for formula in formulas}
        self.assertEqual(saved["free_cash_flow"], "operating_cf - capex + 1")

    def test_unsafe_formula_is_not_saved(self):
        response = self.client.post(
            "/solar/formulas",
            data={
                "token": "test-dashboard-token",
                "formula_key": "fcff",
                "expression": "__import__('os').system('id')",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        formulas = asyncio.run(financial_formulas())
        saved = {formula["key"]: formula["expression"] for formula in formulas}
        self.assertNotIn("__import__", saved["fcff"])

    def test_source_metadata_is_persisted_in_ratio_snapshot(self):
        row = {
            "ticker": "TESTSOLAR.NS",
            "name": "Test Solar",
            "statement_date": "31-03-2026",
            "data_source_url": "https://example.com/official-filing.pdf",
            "cross_check_status": "Verified against official filing",
        }
        asyncio.run(save_ratio_snapshot(row))

        async def load_snapshot() -> dict:
            import aiosqlite

            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "SELECT ratios_json FROM ratio_snapshots WHERE ticker=?",
                    ("TESTSOLAR.NS",),
                )
                stored = await cursor.fetchone()
            return json.loads(stored[0])

        saved = asyncio.run(load_snapshot())
        self.assertEqual(
            saved["data_source_url"],
            "https://example.com/official-filing.pdf",
        )
        self.assertEqual(
            saved["cross_check_status"],
            "Verified against official filing",
        )


if __name__ == "__main__":
    unittest.main()
