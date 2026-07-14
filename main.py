"""Shield GUI — Windows 桌面封装 Shield CLI.

启动 pywebview 窗口，加载 ui/index.html，注入 PythonApi 桥接对象。
系统托盘（pystray）提供后台常驻与快捷操作。
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

import webview

# 让 ui 目录可通过相对路径找到（pywebview 加载本地文件用绝对路径）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(BASE_DIR, "ui")

# 把项目根加入 sys.path，确保包内 import 正常
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.api import PythonApi  # noqa: E402


class MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", wintypes.LONG),
        ("cxRightWidth", wintypes.LONG),
        ("cyTopHeight", wintypes.LONG),
        ("cyBottomHeight", wintypes.LONG),
    ]


def _suppress_dwm_border(api: PythonApi) -> None:
    """等待窗口创建后调用 DwmExtendFrameIntoClientArea 消除 DWM 边框/阴影。

    frameless 窗口在 Windows 10/11 上最大化时会因 DWM 绘制残留边框而产生空隙。
    传入零边距告诉 DWM 不预留任何边框空间。
    """
    for _ in range(50):  # 最多等 5s
        time.sleep(0.1)
        try:
            win = api._window
            if win is None:
                continue
            native = getattr(win, "native", None)
            if native is None:
                continue
            form = getattr(native, "window", None)
            if form is None:
                continue
            hwnd_int = int(str(form.handle))
            break
        except Exception:
            continue
    else:
        return  # 超时放弃
    try:
        margins = MARGINS(0, 0, 0, 0)
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
            wintypes.HWND(hwnd_int), ctypes.byref(margins)
        )
    except Exception:
        pass


# =============================================================================
# 系统托盘管理器（pystray）
# =============================================================================

class TrayManager:
    """使用 pystray 在系统托盘中创建图标与右键菜单。

    左键单击—显示窗口；右键—上下文菜单：
      - 显示/隐藏窗口
      - ──────────
      - 快速新建隧道
      - 打开 Web UI
      - ──────────
      - 检查更新
      - 关于
      - ──────────
      - 退出
    """

    def __init__(self, api: PythonApi):
        self.api = api
        self._icon = None
        self._thread = None

    def start(self) -> None:
        """启动托盘线程（守护线程，随主进程退出）。"""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止托盘图标。"""
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

    # ---- 托盘菜单回调（在 pystray 线程中执行） ----

    def _show_window(self) -> None:
        """显示窗口并前置。"""
        self.api._ensure_visible()

    def _toggle_window(self) -> None:
        self.api._toggle_window()

    def _new_tunnel(self) -> None:
        """显示窗口 + 跳转到新建隧道。"""
        self.api._ensure_visible()
        self.api.navigate_view("tunnel-new")

    def _open_web_ui(self) -> None:
        """显示窗口 + 启动 Web UI + 打开浏览器。"""
        self.api._ensure_visible()
        try:
            self.api.open_web_ui(8181)
        except Exception:
            pass

    def _check_updates(self) -> None:
        """显示窗口 + 切换到仪表盘 + 触发更新检测 + 通知。"""
        self.api._ensure_visible()
        if self.api._window:
            try:
                self.api._window.evaluate_js(
                    "navigate('dashboard');"
                    "setTimeout(() => TitleBar.checkForUpdates(), 300);"
                )
            except Exception:
                pass

    def _about(self) -> None:
        """显示窗口 + 打开应用配置页 + 滚动到「关于 Shield GUI」。"""
        self.api._ensure_visible()
        if self.api._window:
            try:
                self.api._window.evaluate_js(
                    "navigate('settings');"
                    "setTimeout(() => {"
                    "  const el = [...document.querySelectorAll('.card-title')]"
                    "    .find(t => t.textContent.includes('关于 Shield GUI'));"
                    "  if (el) el.closest('.card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });"
                    "}, 400);"
                )
            except Exception:
                pass

    def _quit(self) -> None:
        """真正退出：停止托盘 → 关闭窗口。"""
        if self._icon:
            try:
                self._icon.visible = False
                self._icon.stop()
            except Exception:
                pass
        self.api.window_quit()

    # ---- 托盘图标 ----

    def _run(self) -> None:
        """创建并运行 pystray 图标（在后台线程中阻塞）。"""
        import pystray
        from PIL import Image
        from pystray import Menu, MenuItem

        ico_path = os.path.join(BASE_DIR, "ui/assets", "app.ico")
        image = Image.open(ico_path)

        def toggle_text(_item):
            return "隐藏窗口" if self.api._window_visible else "显示窗口"

        menu = Menu(
            MenuItem(toggle_text, lambda: self._toggle_window(), default=True),
            Menu.SEPARATOR,
            MenuItem("快速新建隧道", lambda: self._new_tunnel()),
            MenuItem("打开 Web UI", lambda: self._open_web_ui()),
            Menu.SEPARATOR,
            MenuItem("检查更新", lambda: self._check_updates()),
            MenuItem("关于", lambda: self._about()),
            Menu.SEPARATOR,
            MenuItem("退出", lambda: self._quit()),
        )

        self._icon = pystray.Icon(
            "shield-gui", image, "Shield GUI", menu,
            on_left_click=lambda: self._show_window(),
        )
        self._icon.run()


# =============================================================================
# 主入口
# =============================================================================

def main() -> None:
    api = PythonApi()
    index_path = os.path.join(UI_DIR, "index.html")
    window = webview.create_window(
        title="Shield GUI",
        url=index_path,
        js_api=api,
        width=1280,
        height=820,
        min_size=(1024, 680),
        text_select=False,
        frameless=True,
        easy_drag=False,
        resizable=True,
    )
    # 暴露 window 引用给 api
    api.attach_window(window)

    # 创建系统托盘（后台线程）
    tray = TrayManager(api)
    tray.start()

    # webview.start(func) 的 func 在 GUI 循环启动后的独立线程中执行
    webview.start(func=lambda: _suppress_dwm_border(api), debug=False)


if __name__ == "__main__":
    main()
