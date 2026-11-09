"""重新生成 README 里的界面截图。

用法::

    python docs/generate_screenshots.py

原理：把 ``docs/screenshot-inject.html``（模拟 ``pywebview`` js_api 的桩数据 +
禁用 CSS 入场动画）注入 ``ui/index.html``，生成临时页面，再用无头 Chrome/Edge
按路由截图。截图输出到 ``docs/screenshots/``，临时页面用完即删。

界面改版后跑一次即可刷新文档配图；桩数据是演示用的假数据，不会连接真实服务。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI_DIR = ROOT / "ui"
OUT_DIR = ROOT / "docs" / "screenshots"
INJECT_FILE = ROOT / "docs" / "screenshot-inject.html"
ROUTES = ("dashboard", "sessions", "editor", "tunnel-new")


def find_browser() -> str | None:
    candidates = [
        os.environ.get("CHROME_PATH"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
    ]
    for path in candidates:
        if path and Path(path).is_file():
            return str(path)
    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def main() -> None:
    browser = find_browser()
    if not browser:
        sys.exit("未找到 Chrome/Edge，请设置 CHROME_PATH 环境变量指向浏览器 exe")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    inject = INJECT_FILE.read_text(encoding="utf-8")
    shot_page = UI_DIR / "__screenshot__.html"
    shot_page.write_text(
        html.replace("</body>", inject + "\n</body>"), encoding="utf-8"
    )
    base_url = shot_page.resolve().as_uri()
    try:
        for route in ROUTES:
            dest = OUT_DIR / f"{route}.png"
            cmd = [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--allow-file-access-from-files",
                "--hide-scrollbars",
                "--force-device-scale-factor=1",
                "--window-size=1280,820",
                "--virtual-time-budget=7000",
                f"--screenshot={dest}",
                f"{base_url}?route={route}",
            ]
            try:
                subprocess.run(
                    cmd, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=90,
                )
            except subprocess.TimeoutExpired:
                print(f"TIMEOUT  {dest.name}")
                continue
            size = dest.stat().st_size // 1024 if dest.is_file() else 0
            print(f"{'OK     ' if size else 'FAILED '} {dest.name:<18} {size} KB")
    finally:
        shot_page.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
