"""Check benchmark comparisons and plot limits without running measurements."""

import re
import unittest
from pathlib import Path

from bench import report


class ReportTests(unittest.TestCase):
    def test_result_notes_name_the_faster_tool(self):
        for ratios, expected in (
            ((0.8, 1.2), "higher geometric-mean time than simdutf; lower than Zig std.base64"),
            ((0.8, 0.9), "higher geometric-mean time than simdutf, Zig std.base64"),
            ((1.2, 1.3), "the lowest geometric-mean time among the listed rows"),
            ((1.0, 1.0), "the lowest geometric-mean time among the listed rows"),
        ):
            with self.subTest(ratios=ratios):
                rows = [
                    dict(mode="encode-memory", tool=tool, time_ratio=ratio, rss_ratio=1.0)
                    for tool, ratio in zip(("simdutf", "zig-std"), ratios, strict=True)
                ]
                self.assertIn(
                    f"- `encode-memory`: B64Z has {expected}. No listed peer has lower geometric-mean RSS.",
                    report.result_notes(rows),
                )

    def test_summary_limits_include_ratios_below_half(self):
        target = report.TARGETS["linux-x86-scalar"]
        _, rows = report.read_measurements(target.directory / "measurements.tsv")
        summary = report.build_summary(rows)
        for row in summary:
            if row["tool"] != "b64z":
                for metric in ("time", "rss"):
                    for field in ("ratio", "iqr_low", "iqr_high"):
                        row[f"{metric}_{field}"] = 0.25
        paths = {(metric, peer.id): Path("unused.dat") for metric in ("time", "rss") for peer in report.PEERS}
        script = report.summary_body(target, summary, paths, "light")
        limits = re.findall(r"set xrange \[([^:]+):([^]]+)\]", script)
        self.assertEqual(len(limits), 2)
        for low, high in limits:
            self.assertGreater(float(low), 0)
            self.assertLess(float(low), 0.25)
            self.assertGreater(float(high), 1.0)

    def test_isocost_limits_include_every_retained_case(self):
        for target in report.TARGETS.values():
            _, rows = report.read_measurements(target.directory / "measurements.tsv")
            summary = report.build_summary(rows)
            paths = {(row["mode"], row["tool"]): Path("unused.dat") for row in summary}
            script = report.isocost_body(rows, summary, paths, paths, "light")
            for axis, metric in (("x", "wall_ns"), ("y", "rss_bytes")):
                limits = re.findall(rf"set {axis}range \[([^:]+):([^]]+)\]", script)
                for mode, (low, high) in zip(report.MODES, limits, strict=True):
                    with self.subTest(target=target.id, mode=mode, axis=axis):
                        group = [row for row in rows if row["mode"] == mode]
                        b64z = {row["case_id"]: row for row in group if row["tool"] == "b64z"}
                        ratios = [float(row[metric]) / float(b64z[row["case_id"]][metric]) for row in group]
                        self.assertGreater(float(low), 0)
                        self.assertLess(float(low), min(ratios))
                        self.assertGreater(float(high), max(ratios))


if __name__ == "__main__":
    unittest.main()
