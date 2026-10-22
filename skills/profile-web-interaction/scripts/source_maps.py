"""Minimal source-map v3 position lookup. Unsupported maps are reported, not guessed."""
from bisect import bisect_right
from functools import lru_cache
from urllib.parse import urljoin

BASE64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def decode_vlq(segment):
    values = []
    value = shift = 0
    for char in segment:
        digit = BASE64.index(char)
        value |= (digit & 31) << shift
        if digit & 32:
            shift += 5
            if shift > 50:
                raise ValueError("VLQ 数值过大")
        else:
            values.append(-(value >> 1) if value & 1 else value >> 1)
            value = shift = 0
    if shift:
        raise ValueError("不完整的 VLQ")
    return values


class SourceMap:
    def __init__(self, data, base_url):
        if data.get("version") != 3 or "sections" in data:
            raise ValueError("仅支持普通 source-map v3；indexed map 不解析")
        self.sources = data["sources"]
        self.root = data.get("sourceRoot", "")
        self.base_url = base_url
        self.lines = []
        source = line = column = name = 0
        for encoded_line in data["mappings"].split(";"):
            generated_column = 0
            mappings = []
            for segment in encoded_line.split(","):
                if not segment:
                    continue
                values = decode_vlq(segment)
                if len(values) not in (1, 4, 5):
                    raise ValueError("非法 source-map segment")
                generated_column += values[0]
                location = None
                if len(values) >= 4:
                    source += values[1]
                    line += values[2]
                    column += values[3]
                    if not 0 <= source < len(self.sources) or line < 0 or column < 0:
                        raise ValueError("source-map 位置越界")
                    location = (source, line, column)
                if len(values) == 5:
                    name += values[4]
                mappings.append((generated_column, location))
            if mappings != sorted(mappings, key=lambda item: item[0]):
                raise ValueError("source-map 列未排序")
            self.lines.append(mappings)

    def lookup(self, line, column):
        if not 0 <= line < len(self.lines):
            return None
        mappings = self.lines[line]
        index = bisect_right([item[0] for item in mappings], column) - 1
        if index < 0 or mappings[index][1] is None:
            return None
        source, original_line, original_column = mappings[index][1]
        path = self.sources[source]
        if self.root:
            path = self.root.rstrip("/") + "/" + path
        resolved = urljoin(self.base_url, path)
        # Custom bundler schemes (webpack:// etc.) do not resolve through urljoin.
        return {"source": resolved or path, "line": original_line + 1,
                "column": original_column + 1, "mapped": True}


class Resolver:
    def __init__(self, scripts):
        self.scripts = scripts
        self.warnings = set()

    @lru_cache(maxsize=256)
    def mapper(self, script_id):
        script = self.scripts.get(script_id, {})
        if "map" not in script:
            return None
        try:
            return SourceMap(script["map"], script.get("map_base_url", script.get("url", "")))
        except (ValueError, KeyError, TypeError) as exc:
            self.warnings.add(f"map 解析失败 {script.get('url', script_id)}: {exc}")
            return None

    def resolve(self, frame):
        mapper = self.mapper(str(frame.get("scriptId", "")))
        line, column = frame.get("lineNumber", -1), frame.get("columnNumber", -1)
        if mapper and line >= 0 and column >= 0:
            position = mapper.lookup(line, column)
            if position:
                return position
        return {"source": frame.get("url", ""), "line": line + 1 if line >= 0 else None,
                "column": column + 1 if column >= 0 else None, "mapped": False}
