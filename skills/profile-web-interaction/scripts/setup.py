"""Prepare an isolated Python + Chromium environment without touching a target project."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import venv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", type=Path, required=True)
    args = parser.parse_args()
    root = args.venv.expanduser().resolve()
    skill = Path(__file__).resolve().parents[1]
    try:
        if root == skill or skill in root.parents:
            raise ValueError("虚拟环境必须位于 Skill 目录之外")
        if root.exists() and not (root / "pyvenv.cfg").is_file():
            raise ValueError("目标目录已存在且不是虚拟环境，拒绝覆盖")
        if not root.exists():
            venv.EnvBuilder(with_pip=True).create(root)
        python = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(root / "browsers"), "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(skill / "requirements.txt")], env=env, check=True)
        subprocess.run([str(python), "-m", "playwright", "install", "chromium"], env=env, check=True)
        print(f"环境就绪：{python}\n浏览器：{root / 'browsers'}")
        return 0
    except Exception as exc:
        print(f"环境准备失败：{exc}。已有环境保留，可用相同命令重试。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
