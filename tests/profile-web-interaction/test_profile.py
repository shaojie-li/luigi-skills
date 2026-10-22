import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[2] / "skills/profile-web-interaction/scripts"
sys.path.insert(0, str(SCRIPTS))
from record import read_scenario
from source_maps import SourceMap, Resolver, decode_vlq
from summarize import compact_report, cpu_summary, spans, summarize, union_us


class SourceMapTests(unittest.TestCase):
    def test_original_position_is_one_based(self):
        mapping = SourceMap({"version": 3, "sources": ["src/Calculator.tsx"],
                             "mappings": "AAAA,KACE"}, "http://localhost:5173/app.js.map")
        self.assertEqual(mapping.lookup(0, 7), {
            "source": "http://localhost:5173/src/Calculator.tsx", "line": 2, "column": 3, "mapped": True})

    def test_unmapped_segment_does_not_reuse_previous_mapping(self):
        mapping = SourceMap({"version": 3, "sources": ["x.ts"], "mappings": "AAAA,K"}, "http://localhost/x.js")
        self.assertIsNone(mapping.lookup(0, 8))
        self.assertIsNone(mapping.lookup(4, 0))

    def test_indexed_map_explicitly_falls_back(self):
        resolver = Resolver({"1": {"url": "x.js", "map": {"version": 3, "sections": []}}})
        result = resolver.resolve({"scriptId": "1", "url": "x.js", "lineNumber": 5, "columnNumber": 0})
        self.assertFalse(result["mapped"])
        self.assertEqual(result["line"], 6)
        self.assertTrue(resolver.warnings)

    def test_incomplete_vlq_is_rejected(self):
        with self.assertRaises(ValueError):
            decode_vlq("g")


class ProfileTests(unittest.TestCase):
    def profile(self):
        return {"startTime": 0, "endTime": 10000, "nodes": [
            {"id": 1, "callFrame": {"functionName": "(root)"}, "children": [2]},
            {"id": 2, "callFrame": {"functionName": "parent", "url": "http://local/app.js"}, "children": [3]},
            {"id": 3, "callFrame": {"functionName": "child", "url": "http://local/app.js"}}],
            "samples": [3, 2], "timeDeltas": [2000, 1000]}

    def test_self_and_inclusive_do_not_double_count(self):
        summary, _ = cpu_summary(self.profile(), Resolver({}), 15)
        rows = {r["function"]: r for r in summary["hotspots"]}
        self.assertEqual(rows["parent"]["self_ms"], 1)
        self.assertEqual(rows["parent"]["inclusive_ms"], 3)
        self.assertEqual(sum(r["self_ms"] for r in rows.values()), 3)
        self.assertEqual(len(summary["application_hotspots"]), 2)

    def test_out_of_order_samples_are_sorted_and_disclosed(self):
        profile = self.profile()
        profile["samples"] = [3, 2, 3]
        profile["timeDeltas"] = [2000, -1000, 2000]
        summary, timeline = cpu_summary(profile, Resolver({}), 15)
        self.assertEqual(summary["out_of_order_samples"], 1)
        self.assertEqual([t[0] for t in timeline], [1000, 2000, 3000])
        self.assertEqual(sum(t[1] for t in timeline), 3000)

    def test_invalid_sample_cannot_be_success(self):
        profile = self.profile()
        profile["samples"][0] = 99
        with self.assertRaises(ValueError):
            cpu_summary(profile, Resolver({}), 15)

    def test_nested_intervals_use_union(self):
        self.assertEqual(union_us([(0, 10), (2, 8), (9, 14), (20, 25)]), 19)

    def test_async_ids_are_scoped_to_process(self):
        events = [
            {"ph": "b", "pid": 1, "id": 1, "name": "A", "ts": 10},
            {"ph": "b", "pid": 2, "id": 1, "name": "A", "ts": 11},
            {"ph": "e", "pid": 1, "id": 1, "name": "A", "ts": 20},
            {"ph": "e", "pid": 2, "id": 1, "name": "A", "ts": 31}]
        self.assertEqual([s["dur"] for s in spans(events)], [10, 20])

    def test_report_filters_other_threads_and_outer_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = {"schema_version": 1, "status": "passed", "build_label": "test", "steps": []}
            events = [{"ph": "X", "pid": 1, "tid": 1, "name": name, "ts": 0, "dur": duration}
                      for name, duration in [("skill-step:click", 100000), ("RunTask", 60000), ("ThreadControllerImpl::RunTask", 61000)]]
            events.append({"ph": "X", "pid": 2, "tid": 1, "name": "RunTask", "ts": 0, "dur": 999999})
            for filename, data in [("recording.json", metadata), ("trace.json", {"traceEvents": events}),
                                   ("cpu-profile.json", self.profile()), ("source-maps.json", {})]:
                (root / filename).write_text(json.dumps(data))
            report = summarize(root)
            self.assertEqual(report["long_tasks"]["count"], 1)
            self.assertEqual(report["long_tasks"]["top"][0]["duration_ms"], 60)
            self.assertFalse(report["react"]["available"])
            self.assertTrue(report["warnings"])
            report["recording"]["steps"] = [{"id": f"step-{i}", "action": "click", "status": "passed", "start_ms": i * 5, "duration_ms": 5} for i in range(200)]
            report["actions"] = [{"id": f"step-{i}", "automation_interval_ms": 5, "evidence": {"file": "trace.json", "event_index": i}} for i in range(200)]
            compact = compact_report(report)
            self.assertEqual(compact["steps"]["count"], 200)
            self.assertEqual(compact["steps"]["operation_count"], 200)
            self.assertEqual(len(compact["steps"]["slowest"]), 3)
            self.assertNotIn("steps", compact["recording"])
            self.assertNotIn("generated_location", compact["cpu"]["hotspots"][0])
            self.assertLess(len(json.dumps(compact, ensure_ascii=False).encode()), 10000)


class ScenarioTests(unittest.TestCase):
    def test_duplicate_step_and_unknown_action_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scenario.json"
            step = {"id": "a", "action": "click", "role": "button", "name": "保存"}
            path.write_text(json.dumps({"steps": [step, step]}))
            with self.assertRaises(ValueError):
                read_scenario(path)
            step["action"] = "evaluate"
            path.write_text(json.dumps({"steps": [step]}))
            with self.assertRaises(ValueError):
                read_scenario(path)

    def test_first_use_without_dependencies_fails_without_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scenario.json"
            path.write_text(json.dumps({"steps": [{"id": "click", "action": "click", "role": "button", "name": "保存"}]}))
            output = Path(tmp) / "recording"
            result = subprocess.run([sys.executable, "-S", str(SCRIPTS / "record.py"), "--url", "http://localhost:5173/", "--scenario", str(path), "--output", str(output)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("缺少 Playwright", result.stderr)
            self.assertFalse(output.exists())

    def test_setup_refuses_existing_non_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "keep.txt"
            marker.write_text("keep")
            result = subprocess.run([sys.executable, str(SCRIPTS / "setup.py"), "--venv", tmp], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("拒绝覆盖", result.stderr)
            self.assertEqual(marker.read_text(), "keep")
            self.assertEqual(list(Path(tmp).iterdir()), [marker])

    def test_scoped_assertion_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scenario.json"
            data = {"steps": [{"id": "verify", "action": "expect_text", "role": "status", "name": "结果", "value": "15", "scope": {"role": "region", "name": "计算器"}}]}
            path.write_text(json.dumps(data))
            self.assertEqual(read_scenario(path), data["steps"])


if __name__ == "__main__":
    unittest.main()
