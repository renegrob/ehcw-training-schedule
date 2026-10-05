"""Unit tests for the local sync-state file (load/save/prune)."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

import sync_state


class SyncStateTest(unittest.TestCase):
    def test_load_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            state = sync_state.load(Path(d) / "nope.json")
            self.assertEqual(
                state, {"synced": {}, "tombstones": {}, "superseded": {}}
            )

    def test_load_adds_missing_buckets_to_an_older_state_file(self):
        # State files written before the "superseded" bucket existed must keep
        # loading - and gain the bucket - rather than KeyError downstream.
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.json"
            path.write_text('{"synced": {}, "tombstones": {}}')
            self.assertEqual(sync_state.load(path)["superseded"], {})

    def test_save_then_load_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.json"
            state = {
                "synced": {"ehc-a": {"date": "2099-01-01", "summary": "x"}},
                "tombstones": {"ehc-b": {"date": "2099-01-01"}},
                "superseded": {"ehc-c": {"date": "2099-01-01", "summary": "y"}},
            }
            sync_state.save(path, state, today=date(2026, 1, 1))
            self.assertEqual(sync_state.load(path), state)

    def test_s3_uri_detection_and_split(self):
        self.assertTrue(sync_state._is_s3("s3://bucket/path/state.json"))
        self.assertFalse(sync_state._is_s3("sync-state.json"))
        self.assertEqual(
            sync_state._split_s3("s3://my-bucket/ehcw/state.json"),
            ("my-bucket", "ehcw/state.json"),
        )
        with self.assertRaises(ValueError):
            sync_state._split_s3("s3://only-bucket")

    def test_prune_drops_past_entries_only(self):
        state = {
            "synced": {
                "past": {"date": "2020-01-01"},
                "future": {"date": "2099-01-01"},
                "undated": {"summary": "no date -> kept"},
            },
            "tombstones": {"old": {"date": "2020-06-01"}},
            "superseded": {
                "gone": {"date": "2020-06-01"},
                "upcoming": {"date": "2099-01-01"},
            },
        }
        sync_state.prune_past(state, today=date(2026, 8, 29))
        self.assertEqual(set(state["synced"]), {"future", "undated"})
        self.assertEqual(state["tombstones"], {})
        self.assertEqual(set(state["superseded"]), {"upcoming"})

    def test_prune_tolerates_a_state_without_the_newer_buckets(self):
        state = {"synced": {}, "tombstones": {}}
        sync_state.prune_past(state, today=date(2026, 8, 29))  # must not raise


if __name__ == "__main__":
    unittest.main()
