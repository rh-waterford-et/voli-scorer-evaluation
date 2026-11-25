"""Run series grouping (metadata + API) without a live cluster."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "dashboard" / "backend")]

from bench import RunParams
from store import RunStore, normalize_series
import app as dashboard_app
from fastapi import HTTPException
from pydantic import ValidationError


class NormalizeTests(unittest.TestCase):
    def test_trim_collapse_and_empty(self):
        self.assertEqual(normalize_series(None), None)
        self.assertEqual(normalize_series(""), None)
        self.assertEqual(normalize_series("   "), None)
        self.assertEqual(normalize_series("  praxis  gateway "), "praxis gateway")
        # Line breaks collapse so labels always render on one line.
        self.assertEqual(normalize_series("praxis\ngateway"), "praxis gateway")
        with self.assertRaises(ValueError):
            normalize_series("x" * 81)
        self.assertEqual(normalize_series("x" * 80), "x" * 80)


class StoreTests(unittest.TestCase):
    def test_create_set_and_list_series(self):
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp))
            run = store.create("run-a", "first", {"model": "m"}, series="  alpha series ")
            self.assertEqual(run["series"], "alpha series")
            # Runs without a series simply lack the field.
            plain = store.create("run-b", "second", {"model": "m"})
            self.assertNotIn("series", plain)

            # Assign, reassign and clear.
            meta = store.set_series("run-b", "beta")
            self.assertEqual(meta["series"], "beta")
            self.assertEqual(store.set_series("run-b", "alpha series")["series"], "alpha series")
            self.assertIsNone(store.set_series("run-b", None)["series"])
            self.assertIsNone(store.set_series("run-b", "   ")["series"])

            # Unknown runs are distinguished from invalid input.
            self.assertIsNone(store.set_series("missing", "x"))
            with self.assertRaises(ValueError):
                store.set_series("run-a", "y" * 81)

            # The distinct-series list follows the stored runs.
            self.assertEqual(store.list_series(), ["alpha series"])
            store.set_series("run-b", "alpha series")
            self.assertEqual(store.list_series(), ["alpha series"])
            store.delete("run-a")
            self.assertEqual(store.list_series(), ["alpha series"])
            store.delete("run-b")
            self.assertEqual(store.list_series(), [])


class ManagerTests(unittest.TestCase):
    def test_create_carries_series_and_live_meta_stays_in_sync(self):
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp))

            # Mirrors RunManager's contract (store.create + in-memory meta)
            # without spawning benchmark subprocesses.
            class Live:
                def __init__(self, meta):
                    self.meta = meta
                    self.run_id = meta["id"]

            class Manager:
                def __init__(self):
                    self.live = {}

                def plan(self, params, run_id=None):
                    return run_id or "20261125-fixed", []

                def create(self, name, params, run_id=None, series=None):
                    meta = store.create(run_id or "run-x", name or "label",
                                        params.model_dump(), series=series)
                    self.live[meta["id"]] = Live(meta)
                    return self.live[meta["id"]]

                def get(self, run_id):
                    return self.live.get(run_id)

            manager = Manager()
            params = RunParams(endpoint="/v1/embeddings", model="m", profiles=["default"])
            run = manager.create("named", params, series="chat vs tts")
            self.assertEqual(run.meta["series"], "chat vs tts")

            # A live run's meta stays in sync when the series is changed, so a
            # later status save cannot restore the stale value.
            with patch.object(dashboard_app, "store", store), patch.object(
                dashboard_app, "manager", manager
            ):
                result = dashboard_app.set_run_series(
                    run.run_id, dashboard_app.SeriesRequest(series="renamed series")
                )
            self.assertEqual(result["series"], "renamed series")
            self.assertEqual(manager.get(run.run_id).meta["series"], "renamed series")


class ApiTests(unittest.TestCase):
    def test_endpoints(self):
        with tempfile.TemporaryDirectory() as temp:
            store = RunStore(Path(temp))

            class Manager:
                def __init__(self):
                    self.live = {}

                def get(self, run_id):
                    return self.live.get(run_id)

            manager = Manager()
            params = RunParams(endpoint="/v1/embeddings", model="m", profiles=["default"])
            run = store.create("run-one", "named", params.model_dump(), series="one")
            other = store.create("run-two", None, params.model_dump())
            manager.live[run["id"]] = type("Run", (), {"run_id": run["id"], "meta": run})()
            with patch.object(dashboard_app, "store", store), patch.object(
                dashboard_app, "manager", manager
            ):
                listed = dashboard_app.series_list()
                self.assertEqual(listed, {"series": ["one"]})

                result = dashboard_app.set_run_series(
                    other["id"], dashboard_app.SeriesRequest(series="two")
                )
                self.assertEqual(result, {"id": other["id"], "series": "two"})
                self.assertEqual(dashboard_app.series_list(), {"series": ["one", "two"]})

                cleared = dashboard_app.set_run_series(
                    other["id"], dashboard_app.SeriesRequest(series="")
                )
                self.assertIsNone(cleared["series"])

                with self.assertRaises(HTTPException) as caught:
                    dashboard_app.set_run_series(
                        "missing", dashboard_app.SeriesRequest(series="x")
                    )
                self.assertEqual(caught.exception.status_code, 404)
                with self.assertRaises(HTTPException) as caught:
                    dashboard_app.set_run_series(
                        run["id"], dashboard_app.SeriesRequest(series="z" * 81)
                    )
                self.assertEqual(caught.exception.status_code, 400)

                items = dashboard_app.list_runs(include_reports=False)
                by_id = {item["id"]: item for item in items}
                self.assertEqual(by_id[run["id"]]["series"], "one")
                self.assertIsNone(by_id[other["id"]]["series"])

    def test_create_request_accepts_series(self):
        # The series rides alongside params and never becomes one.
        request = dashboard_app.CreateRunRequest.model_validate(
            {"series": "  spaced name ", "params": {"endpoint": "/v1/embeddings", "profiles": ["default"]}}
        )
        self.assertEqual(request.series, "  spaced name ")
        self.assertNotIn("series", request.params.model_dump())
        with self.assertRaises(ValidationError):
            dashboard_app.CreateRunRequest.model_validate(
                {"series": 5, "params": {"endpoint": "/v1/embeddings", "profiles": ["default"]}}
            )


if __name__ == "__main__":
    unittest.main()
