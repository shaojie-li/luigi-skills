"""Reduce a recording to bounded, evidence-linked JSON/Markdown using only stdlib."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import median
import sys

sys.dont_write_bytecode = True
from source_maps import Resolver


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def spans(events):
    """Normalize complete, sync and nestable-async spans, preserving raw indices."""
    stacks = defaultdict(list)
    for index, event in enumerate(events):
        phase = event.get("ph")
        if phase == "X" and event.get("dur", 0) >= 0:
            yield {**event, "raw_index": index}
        elif phase in {"B", "b"}:
            key = (event.get("pid"), event.get("tid"), "sync") if phase == "B" else (
                event.get("pid"), event.get("cat"), json.dumps(event.get("id2", event.get("id")), sort_keys=True), event.get("name"))
            stacks[key].append((index, event))
        elif phase in {"E", "e"}:
            key = (event.get("pid"), event.get("tid"), "sync") if phase == "E" else (
                event.get("pid"), event.get("cat"), json.dumps(event.get("id2", event.get("id")), sort_keys=True), event.get("name"))
            if stacks[key]:
                start_index, start = stacks[key].pop()
                duration = event["ts"] - start["ts"]
                if duration >= 0:
                    yield {**start, "dur": duration, "raw_index": start_index}


def union_us(intervals):
    end = None
    total = 0
    for start, stop in sorted(intervals):
        if end is None or start > end:
            total += stop - start
        elif stop > end:
            total += stop - end
        end = max(end or stop, stop)
    return total


def cpu_summary(profile, resolver, top):
    nodes = {node["id"]: node for node in profile["nodes"]}
    parents = {}
    for node in nodes.values():
        for child in node.get("children", []):
            if child in parents:
                raise ValueError("CPU profile 不是树")
            parents[child] = node["id"]
    samples, deltas = profile.get("samples", []), profile.get("timeDeltas", [])
    if len(samples) != len(deltas):
        raise ValueError("CPU samples/timeDeltas 长度不一致")
    own, inclusive, counts = Counter(), Counter(), Counter()
    timeline = []
    timestamp = profile["startTime"]
    stamped = []
    for sample, delta in zip(samples, deltas):
        if sample not in nodes:
            raise ValueError("非法 CPU sample")
        timestamp += delta
        if not profile["startTime"] <= timestamp <= profile["endTime"]:
            raise ValueError("CPU sample 时间越界")
        stamped.append((timestamp, sample))
    previous = profile["startTime"]
    for timestamp, sample in sorted(stamped, key=lambda item: item[0]):
        delta = timestamp - previous
        previous = timestamp
        own[sample] += delta
        counts[sample] += 1
        timeline.append((timestamp, delta, nodes[sample]["callFrame"]["functionName"]))
        current, visited = sample, set()
        while current is not None:
            if current in visited:
                raise ValueError("CPU profile 出现父节点循环")
            visited.add(current)
            inclusive[current] += delta
            current = parents.get(current)
    rows = []
    for node_id in sorted(inclusive, key=lambda key: (own[key], inclusive[key]), reverse=True):
        cost = own[node_id]
        frame = nodes[node_id]["callFrame"]
        if frame["functionName"] in {"(idle)", "(root)", "(program)"}:
            continue
        rows.append({"function": frame["functionName"] or "(anonymous)",
                     "self_ms": round(cost / 1000, 3),
                     "inclusive_ms": round(inclusive[node_id] / 1000, 3),
                     "sample_count": counts[node_id], "location": resolver.resolve(frame),
                     "evidence": {"file": "cpu-profile.json", "node_id": node_id},
                     "generated_location": frame})
    return {"sample_count": len(samples), "sampled_ms": round(sum(deltas) / 1000, 3),
            "hotspots": rows[:top], "hotspot_count": len(rows),
            "application_hotspots": [row for row in rows if row["generated_location"].get("url", "").startswith(("http://", "https://")) and "/node_modules/" not in row["generated_location"]["url"]][:top],
            "out_of_order_samples": sum(delta < 0 for delta in deltas)}, timeline


def react_metadata(event):
    args = event.get("args", {})
    data = args.get("data", args)
    detail = data.get("detail", {}) if isinstance(data, dict) else {}
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except ValueError:
            return {}
    return detail.get("devtools", {}) if isinstance(detail, dict) else {}


def summarize(directory, top=5):
    meta = read_json(directory / "recording.json")
    if meta.get("schema_version") != 1:
        raise ValueError("不支持的 recording schema")
    trace = read_json(directory / "trace.json")
    events = trace["traceEvents"]
    resolver = Resolver(read_json(directory / "source-maps.json"))
    cpu, timeline = cpu_summary(read_json(directory / "cpu-profile.json"), resolver, top)
    durations = list(spans(events))
    action_spans = [e for e in durations if e.get("name", "").startswith("skill-step:")]
    main_threads = {(e.get("pid"), e.get("tid")) for e in events
                    if e.get("name", "").startswith("skill-step:") and "user_timing" in e.get("cat", "")}
    # Synthetic complete spans used by offline fixtures also identify the thread.
    main_threads.update((e.get("pid"), e.get("tid")) for e in action_spans)
    # Do not accidentally count renderer threads from unrelated tabs as this page.
    selected = [e for e in durations if (e.get("pid"), e.get("tid")) in main_threads]
    task_name = "RunTask" if any(e.get("name") == "RunTask" for e in selected) else "ThreadControllerImpl::RunTask"
    long_tasks = [e for e in selected if e.get("name") == task_name and e["dur"] >= 50000]
    task_rows = [{"duration_ms": round(e["dur"] / 1000, 3), "timestamp_us": e["ts"],
                  "evidence": {"file": "trace.json", "event_index": e["raw_index"]}}
                 for e in sorted(long_tasks, key=lambda e: e["dur"], reverse=True)[:top]]
    phases = {}
    for name in ("Layout", "UpdateLayoutTree", "Paint"):
        matching = [e for e in selected if e.get("name") == name]
        phases[name] = {"count": len(matching), "union_ms": round(union_us(
            [(e["ts"], e["ts"] + e["dur"]) for e in matching]) / 1000, 3)}
    actions = []
    for event in sorted(action_spans, key=lambda e: e["ts"]):
        start, end = event["ts"], event["ts"] + event["dur"]
        actions.append({"id": event["name"].removeprefix("skill-step:"),
                        "automation_interval_ms": round(event["dur"] / 1000, 3),
                        "sampled_active_ms": round(sum(d for ts, d, name in timeline
                            if start <= ts <= end and name not in {"(idle)", "(root)"}) / 1000, 3),
                        "evidence": {"file": "trace.json", "event_index": event["raw_index"]}})
    react = []
    for event in selected:
        detail = react_metadata(event)
        if str(detail.get("trackGroup", "")).startswith("Components") or str(detail.get("track", "")).startswith("Components"):
            react.append({"name": event["name"], "duration_ms": round(event["dur"] / 1000, 3),
                          "track": detail.get("track"), "properties": detail.get("properties", [])[:8],
                          "evidence": {"file": "trace.json", "event_index": event["raw_index"]}})
    warnings = list(meta.get("warnings", [])) + sorted(resolver.warnings)
    if cpu["out_of_order_samples"]:
        warnings.append("CPU 存在乱序采样时间，已按累计时间排序估计耗时；原始数据保留。")
    if not main_threads:
        warnings.append("未找到完整步骤标记；主线程阶段和长任务统计不可用，不能解读为零成本")
    if not react:
        warnings.append("未识别到 React Components 轨道；不能据此推断组件渲染次数或跳过渲染")
    if meta["status"] != "passed":
        warnings.append("录制/场景失败；该摘要只用于排障，不可作为正常基线")
    return {"schema_version": 1, "recording": meta, "cpu": cpu,
            "main_thread_identified": bool(main_threads), "phases": phases,
            "long_tasks": {"count": len(long_tasks), "top": task_rows},
            "actions": actions, "react": {"available": bool(react), "span_count": len(react),
                "median_span_ms": round(median(row["duration_ms"] for row in react), 3) if react else None,
                "max_span_ms": max((row["duration_ms"] for row in react), default=None),
                "slowest_spans": sorted(react, key=lambda row: row["duration_ms"], reverse=True)[:top]},
            "warnings": warnings,
            "limitations": ["CPU 为约 1 ms 间隔采样估计；采样次数不是调用或渲染次数。",
                "组件/函数 inclusive 耗时包含后代，禁止父子相加；React span 不是提交计数。",
                "步骤区间包含 Playwright 等待和往返，不是 INP 或纯浏览器响应延迟。",
                "步骤结束后的异步工作可能未归入该步骤；源码位置来自采样调用帧，不一定是根因。",
                "开发构建与录制有额外开销；单次 10 秒样本不能代表生产性能。"]}


def compact_report(report):
    """Default AI payload: totals and bounded evidence, never a copy of every step."""
    meta = report["recording"]
    steps = meta["steps"]
    durations = [step["duration_ms"] for step in steps if "duration_ms" in step]
    operations = [step for step in steps if step["action"] != "expect_text"]
    active_ms = max((step["start_ms"] + step.get("duration_ms", 0) for step in operations), default=0) - min((step["start_ms"] for step in operations), default=0)
    nodes = {}
    for row in report["cpu"]["hotspots"] + report["cpu"]["application_hotspots"]:
        node_id = row["evidence"]["node_id"]
        nodes[node_id] = {"node_id": node_id, "function": row["function"],
                          "self_ms": row["self_ms"], "inclusive_ms": row["inclusive_ms"],
                          "samples": row["sample_count"], "location": row["location"]}
    app_ids = [row["evidence"]["node_id"] for row in report["cpu"]["application_hotspots"]]
    react = report["react"]
    result = {
        "schema_version": 1,
        "recording": {key: meta[key] for key in ("status", "url", "build_label", "browser_version", "viewport", "requested_seconds", "elapsed_seconds", "error") if key in meta},
        "steps": {"count": len(steps), "passed": sum(step["status"] == "passed" for step in steps),
                  "failed_ids": [step["id"] for step in steps if step["status"] != "passed"][:5],
                  "operation_count": len(operations), "active_window_ms": round(active_ms, 3),
                  "operations_per_second": round(len(operations) * 1000 / active_ms, 2) if active_ms else None,
                  "automation_median_ms": round(median(durations), 3) if durations else None,
                  "automation_max_ms": max(durations, default=None),
                  "slowest": [{"id": step["id"], "automation_ms": step["automation_interval_ms"],
                               "trace_event_index": step["evidence"]["event_index"]}
                              for step in sorted(report["actions"], key=lambda row: row["automation_interval_ms"], reverse=True)[:3]]},
        "cpu": {"sample_count": report["cpu"]["sample_count"], "sampled_ms": report["cpu"]["sampled_ms"],
                "out_of_order_samples": report["cpu"]["out_of_order_samples"],
                "hotspots": list(nodes.values()), "application_node_ids": app_ids},
        "main_thread_identified": report["main_thread_identified"], "phases": report["phases"],
        "long_tasks": {"count": report["long_tasks"]["count"], "top": report["long_tasks"]["top"][:3]},
        "react": {"available": react["available"], "span_count": react["span_count"],
                  "median_span_ms": react["median_span_ms"], "max_span_ms": react["max_span_ms"],
                  "slowest": [{"name": row["name"], "inclusive_ms": row["duration_ms"],
                               "trace_event_index": row["evidence"]["event_index"]}
                              for row in react["slowest_spans"][:3]]},
        "warnings": report["warnings"][:10], "warning_count": len(report["warnings"]),
        "limitations": report["limitations"],
        "evidence": {"trace_event_index": "trace.json → traceEvents[index]", "node_id": "cpu-profile.json → nodes[id]",
                     "all_steps": "recording.json → steps", "mapping_details": "source-maps.json"},
    }
    if len(report["warnings"]) > 10:
        result["warnings"].append("其余映射限制请按 source-maps.json 和 recording.json 定向复核。")
    return result


def markdown(report):
    recording = report["recording"]
    task_count = report["long_tasks"]["count"] if report["main_thread_identified"] else "不可用"
    lines = ["# 交互性能摘要", "", f"- 状态：{recording['status']}；构建：{recording['build_label']}",
             f"- 时长：{recording.get('elapsed_seconds', '?')} 秒；步骤：{report['steps']['passed']}/{report['steps']['count']} 通过",
             f"- 操作：{report['steps']['operation_count']} 次；执行区间：{report['steps']['active_window_ms']} ms（不等于渲染耗时）",
             f"- 主线程长任务：{task_count}；React 轨道：{report['react']['span_count']} 条（不等于 commit 数）",
             "", "## CPU 热点（采样估计）", "", "| 函数 | Self ms | Inclusive ms | 位置 |", "| --- | ---: | ---: | --- |"]
    for row in report["cpu"]["hotspots"]:
        location = row["location"]
        source = f"{location['source']}:{location['line']}:{location['column']}"
        if not location["mapped"]:
            source += "（未映射）"
        lines.append(f"| {row['function'].replace('|', '/')} | {row['self_ms']} | {row['inclusive_ms']} | {source.replace('|', '%7C')} |")
    lines += ["", "## 限制与缺失", ""] + ["- " + warning for warning in report["warnings"] + report["limitations"]]
    lines += ["", "统计与原始证据索引见 summary.json；逐步明细和轨道详情保留在原始文件中。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()
    try:
        if not 1 <= args.top <= 100:
            raise ValueError("top 必须为 1–100")
        destinations = [args.recording / "summary.json", args.recording / "summary.md"]
        if any(path.exists() for path in destinations):
            raise ValueError("摘要已存在；请另存录制目录或显式移走旧摘要后重试")
        report = compact_report(summarize(args.recording, args.top))
        destinations[0].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        destinations[1].write_text(markdown(report), encoding="utf-8")
        print(destinations[1])
        return 0 if report["recording"]["status"] == "passed" else 1
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
