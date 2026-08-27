from fractions import Fraction
import json
from pathlib import Path
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
