from fractions import Fraction
import json
from pathlib import Path
import tempfile
import unittest

from scripts.preflight_path_a import (
    GIB,
    MIN_FREE_DISK_BYTES,
    MIN_RAM_BYTES,
    capacity_sufficient,
    existing_ancestor,
    format_gib,
    normalize_commit,
    parse_linux_meminfo,
    uv_version_matches,
)
from upper_engine import WITNESS_SCALE, build_graph, run, sha256_file
from verify_lueker_table import reproduce


class CleanCloneReproductionTests(unittest.TestCase):
    def _bounded_run(self, root: Path) -> dict[str, str]:
        graph_dir = root / "graphs" / "h3"
        checkpoint_dir = root / "checkpoints" / "h3"
        log_path = root / "logs" / "h3.log"
        log_path.parent.mkdir(parents=True)
        manifest = build_graph(3, graph_dir)
        run(
            graph_dir=graph_dir,
            checkpoint_dir=checkpoint_dir,
            z=Fraction(2422, 10000),
            max_iterations=8,
            tolerance_units=0,
            target_numerator=839250,
            target_denominator=1000000,
            log_path=log_path,
            threads=2,
            witness_scale=WITNESS_SCALE,
        )
        latest = json.loads((checkpoint_dir / "latest.json").read_text(encoding="utf-8"))
        return {
            "states": manifest["states_sha256"],
            "transitions": manifest["transitions_sha256"],
            "witness": latest["state_sha256"],
            "witness_bytes": sha256_file(checkpoint_dir / latest["state_file"]),
        }

    def test_two_fresh_bounded_runs_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self._bounded_run(root / "first")
            second = self._bounded_run(root / "second")
            self.assertEqual(first, second)

    def test_lueker_table_ii_through_history_four(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [
                reproduce(
                    history,
                    root,
                    max_iterations=400,
                    tolerance_units=256,
                    threads=2,
                    witness_scale=WITNESS_SCALE,
                )
                for history in range(2, 5)
            ]
            self.assertEqual([row["history"] for row in rows], [2, 3, 4])
            self.assertTrue(all(row["status"] == "PASS" for row in rows))
            self.assertTrue(all(row["states_match"] for row in rows))
            self.assertTrue(all(row["agrees_to_printed_six_decimals"] for row in rows))


class PathAPreflightTests(unittest.TestCase):
    def test_resource_floors_are_conservative_binary_gibibytes(self):
        self.assertEqual(MIN_FREE_DISK_BYTES, 80 * GIB)
        self.assertEqual(MIN_RAM_BYTES, 64 * GIB)
        self.assertTrue(capacity_sufficient(80 * GIB, MIN_FREE_DISK_BYTES))
        self.assertFalse(capacity_sufficient(80 * GIB - 1, MIN_FREE_DISK_BYTES))
        self.assertTrue(uv_version_matches("uv 0.10.2 (a788db7e5 2026-02-10)"))
        self.assertFalse(uv_version_matches("uv 0.10.3"))

    def test_full_commit_is_required_and_normalized(self):
        commit = "A" * 40
        self.assertEqual(normalize_commit(commit), "a" * 40)
        for invalid in ("a" * 39, "a" * 41, "main", "g" * 40):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_commit(invalid)

    def test_linux_meminfo_is_parsed_in_bytes(self):
        self.assertEqual(
            parse_linux_meminfo("MemTotal:       67108864 kB\nMemFree: 10 kB\n"),
            64 * GIB,
        )
        with self.assertRaises(ValueError):
            parse_linux_meminfo("MemFree: 10 kB\n")

    def test_existing_ancestor_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "new" / "path-a"
            self.assertEqual(existing_ancestor(destination), root)
            self.assertFalse(destination.exists())

    def test_gib_format_is_explicit(self):
        self.assertEqual(format_gib(64 * GIB), "64.00 GiB")

    def test_pending_release_gate_matches_fetch_witness_pins(self):
        root = Path(__file__).resolve().parent
        gate = (root / "docs/RELEASE_V1.1.0_GATE.md").read_text(encoding="utf-8")
        fetch = (root / "scripts/fetch_witness.sh").read_text(encoding="utf-8")
        notes = (root / "release-notes-v1.1.0.md").read_text(encoding="utf-8")
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        assets = {
            "upper-h10-state-0.npy": (
                "6501dd40a1894cfc4c8cd6cf2023078693ebe16a3e3158130e87d23f62afb6ba"
            ),
            "upper-h10-q31-state-1.npy": (
                "e146da77cfb3f37bd00cdfe864abad17741d29a628bf13bd75a0195b91361436"
            ),
        }
        self.assertEqual((root / "VERSION").read_text(encoding="utf-8"), "1.1.0\n")
        self.assertIn("## [1.1.0] — Release candidate (unreleased)", changelog)
        self.assertIn("Path A has not run", notes)
        self.assertIn("## Status: PENDING", gate)
        self.assertIn("15,209,626,046", gate)
        self.assertIn(
            "https://github.com/svemyh/chvatal-sankoff-upper-bound/releases/tag/v1.0.0",
            notes,
        )
        for asset, digest in assets.items():
            with self.subTest(asset=asset):
                for document in (gate, notes):
                    self.assertIn("1,601,013,396", document)
                    self.assertIn(asset, document)
                    self.assertIn(digest, document)
                self.assertIn(asset, fetch)
                self.assertIn(digest, fetch)


if __name__ == "__main__":
    unittest.main()
