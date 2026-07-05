"""Shield GUI — Windows 桌面封装 Shield CLI.

启动 pywebview 窗口，加载 ui/index.html，注入 PythonApi 桥接对象。
"""
from __future__ import annotations

import os
import sys
import webview

# 让 ui 目录可通过相对路径找到（pywebview 加载本地文件用绝对路径）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(BASE_DIR, "ui")

# 把项目根加入 sys.path，确保包内 import 正常
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.api import PythonApi  # noqa: E402


def main() -> None:
    api = PythonApi()
    index_path = os.path.join(UI_DIR, "index.html")
    window = webview.create_window(
        title="Shield GUI — 安全隧道连接器",
        url=index_path,
        js_api=api,
        width=1280,
        height=820,
        min_size=(1024, 680),
        text_select=False,
    )
    # 暴露 window 引用给 api，便于 api 主动推消息到前端
    api.attach_window(window)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
