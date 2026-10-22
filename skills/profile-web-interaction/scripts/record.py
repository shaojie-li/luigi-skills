"""Record a bounded Chromium interaction trace; no target-project dependencies."""
import argparse
import asyncio
import base64
import json
import math
import os
from pathlib import Path
import sys
import time
from urllib.parse import unquote, urljoin, urlparse

sys.dont_write_bytecode = True


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_scenario(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"steps"}:
        raise ValueError("场景必须是仅包含 steps 数组的 JSON 对象")
    steps = data["steps"]
    if not isinstance(steps, list) or not steps or len(steps) > 200:
        raise ValueError("steps 必须包含 1–200 个步骤")
    names = set()
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("步骤必须是对象")
        action = step.get("action")
        allowed = {"id", "action", "role", "name", "scope"}
        if action in {"fill", "press", "expect_text"}:
            allowed.add("value")
            if not isinstance(step.get("value"), str):
                raise ValueError("fill/press/expect_text 需要字符串 value")
        elif action != "click":
            raise ValueError(f"不支持的 action: {action}")
        if set(step) - allowed:
            raise ValueError(f"未知步骤字段: {set(step) - allowed}")
        for key in ("id", "role", "name"):
            if not isinstance(step.get(key), str) or not step[key]:
                raise ValueError(f"步骤需要非空字符串 {key}")
        if step["id"] in names:
            raise ValueError("步骤 id 不得重复")
        names.add(step["id"])
        if "scope" in step:
            scope = step["scope"]
            if (not isinstance(scope, dict) or set(scope) != {"role", "name"}
                    or any(not isinstance(v, str) or not v for v in scope.values())):
                raise ValueError("scope 需要 role 和 name")
    return steps


async def run_steps(page, steps, results, origin):
    from playwright.async_api import expect
    for step in steps:
        label = "skill-step:" + step["id"]
        locator = page
        if "scope" in step:
            locator = locator.get_by_role(step["scope"]["role"], name=step["scope"]["name"], exact=True)
        locator = locator.get_by_role(step["role"], name=step["name"], exact=True)
        result = {"id": step["id"], "action": step["action"], "status": "running",
                  "start_ms": round((time.monotonic() - origin) * 1000, 3)}
        results.append(result)
        await page.evaluate("name => performance.mark(name + ':start')", label)
        try:
            action = step["action"]
            if action == "click":
                await locator.click()
            elif action == "fill":
                await locator.fill(step["value"])
            elif action == "press":
                await locator.press(step["value"])
            else:
                await expect(locator).to_have_text(step["value"], timeout=5000)
            await page.evaluate("name => {performance.mark(name + ':end'); performance.measure(name, name + ':start', name + ':end');}", label)
            result["status"] = "passed"
        except BaseException:
            result["status"] = "failed"
            raise
        finally:
            result["duration_ms"] = round((time.monotonic() - origin) * 1000 - result["start_ms"], 3)


async def save_trace(session, destination, done):
    await session.send("Tracing.end")
    event = await asyncio.wait_for(done, timeout=30)
    handle = event["stream"]
    try:
        with destination.open("wb") as output:
            while True:
                chunk = await session.send("IO.read", {"handle": handle, "size": 1024 * 1024})
                output.write(base64.b64decode(chunk["data"]) if chunk.get("base64Encoded") else chunk["data"].encode())
                if chunk.get("eof"):
                    break
    finally:
        await session.send("IO.close", {"handle": handle})
    return bool(event.get("dataLossOccurred"))


async def collect_maps(context, scripts, profile, target_url, warnings):
    """Only sampled scripts, inline or same-origin maps; unresolved maps remain explicit."""
    used = {n["callFrame"]["scriptId"] for n in profile.get("nodes", [])}
    result = {}
    target = urlparse(target_url)
    for script_id in sorted(used):
        script = scripts.get(script_id)
        if not script:
            continue
        entry = {"url": script.get("url", ""), "source_map_url": script.get("sourceMapURL", "")}
        result[script_id] = entry
        reference = entry["source_map_url"]
        if not reference:
            continue
        try:
            if reference.startswith("data:"):
                header, content = reference.split(",", 1)
                raw = base64.b64decode(content) if ";base64" in header else unquote(content).encode()
                entry["map_base_url"] = entry["url"]
            else:
                url = urljoin(entry["url"], reference)
                parsed = urlparse(url)
                if (parsed.scheme, parsed.netloc) != (target.scheme, target.netloc):
                    raise ValueError("外部来源 map 未下载")
                response = await context.request.get(url, timeout=5000, max_redirects=0)
                if not response.ok:
                    raise ValueError(f"map HTTP {response.status}")
                raw = await response.body()
                entry["map_base_url"] = url
            if len(raw) > 10 * 1024 * 1024:
                raise ValueError("单个 map 超过 10 MB")
            mapping = json.loads(raw)
            # Source text is unnecessary for position mapping and can dominate output size.
            mapping.pop("sourcesContent", None)
            entry["map"] = mapping
        except Exception as exc:
            entry["map_error"] = str(exc)
            warnings.append(f"源码映射不可用: {entry['url']}: {exc}")
    return result


async def record(args, steps):
    from playwright.async_api import async_playwright
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(sys.prefix) / "browsers")
    meta = {"schema_version": 1, "status": "failed", "url": args.url,
            "requested_seconds": args.seconds, "build_label": args.build_label,
            "viewport": {"width": 1280, "height": 900}, "steps": [], "warnings": [],
            "recording": "Chromium Performance trace + sampled CPU profile (not React DevTools export)"}
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "scenario.json", {"steps": steps})
    failure = None
    try:
        async with async_playwright() as p:
            if not Path(p.chromium.executable_path).is_file():
                raise RuntimeError("缺少 Chromium；请运行本 Skill 的 scripts/setup.py --venv " + sys.prefix)
            browser = await p.chromium.launch(headless=not args.headed)
            try:
                meta["browser_version"] = browser.version
                context = await browser.new_context(viewport=meta["viewport"])
                page = await context.new_page()
                page.set_default_timeout(5000)
                await page.goto(args.url, wait_until="load", timeout=30000)
                await page.wait_for_timeout(args.warmup_ms)
                session = await context.new_cdp_session(page)
                scripts = {}
                session.on("Debugger.scriptParsed", lambda data: scripts.__setitem__(data["scriptId"], data))
                await session.send("Debugger.enable")
                await session.send("Profiler.enable")
                await session.send("Profiler.setSamplingInterval", {"interval": 1000})
                done = asyncio.get_running_loop().create_future()
                def completed(event):
                    if not done.done():
                        done.set_result(event)
                session.on("Tracing.tracingComplete", completed)
                await session.send("Tracing.start", {
                    "categories": "devtools.timeline,blink.user_timing,toplevel,disabled-by-default-devtools.timeline",
                    "transferMode": "ReturnAsStream", "streamFormat": "json"})
                profile = None
                try:
                    await session.send("Profiler.start")
                    origin = time.monotonic()
                    try:
                        await asyncio.wait_for(run_steps(page, steps, meta["steps"], origin), timeout=args.seconds)
                        await asyncio.sleep(max(0, args.seconds - (time.monotonic() - origin)))
                    except TimeoutError:
                        current = meta["steps"][-1]["id"] if meta["steps"] else "尚未开始"
                        failure = f"场景超过 {args.seconds} 秒录制窗口；未完成步骤：{current}"
                    except Exception as exc:
                        failure = f"场景失败: {type(exc).__name__}: {exc}"
                    finally:
                        meta["elapsed_seconds"] = round(time.monotonic() - origin, 3)
                        profile = (await session.send("Profiler.stop"))["profile"]
                        write_json(args.output / "cpu-profile.json", profile)
                finally:
                    meta["trace_data_loss"] = await save_trace(session, args.output / "trace.json", done)
                if meta["trace_data_loss"]:
                    raise RuntimeError("浏览器报告 trace 数据丢失，不能标记录制成功")
                if profile is not None:
                    maps = await collect_maps(context, scripts, profile, page.url, meta["warnings"])
                    write_json(args.output / "source-maps.json", maps)
                await page.screenshot(path=str(args.output / "final.png"))
                if failure:
                    raise RuntimeError(failure)
                meta["status"] = "passed"
            finally:
                await browser.close()
    except Exception as exc:
        meta["error"] = f"{type(exc).__name__}: {exc}"
        failure = meta["error"]
    finally:
        write_json(args.output / "recording.json", meta)
    if failure:
        raise RuntimeError(f"{failure}；已有产物保留在 {args.output}")
    return args.output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="必须是尚不存在的目录")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--warmup-ms", type=int, default=1000)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--build-label", default="unknown", help="例如 development / profiling；由调用者确认")
    args = parser.parse_args()
    try:
        if urlparse(args.url).scheme not in {"http", "https"}:
            raise ValueError("url 必须使用 http 或 https")
        if not math.isfinite(args.seconds) or not 0 < args.seconds <= 120:
            raise ValueError("seconds 必须在 (0, 120] 内")
        if not 0 <= args.warmup_ms <= 30000:
            raise ValueError("warmup-ms 必须在 0–30000 内")
        steps = read_scenario(args.scenario)
        print(asyncio.run(record(args, steps)))
    except ImportError:
        print("缺少 Playwright；请按 SKILL.md 在独立 Python 环境安装 requirements.txt 和 Chromium", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
