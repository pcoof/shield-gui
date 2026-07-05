"""端到端冒烟测试：启动 GUI，自动调用 JS 桥接 API 并把结果写到日志后退出。

非交互式验证 pywebview 窗口内 JS↔Python 桥接是否真的工作。
"""
import os
import sys
import threading
import time
import webview

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from core.api import PythonApi  # noqa: E402

RESULTS = []
DONE = threading.Event()


def _record(name, ok, detail=""):
    RESULTS.append({"name": name, "ok": ok, "detail": detail})


def _js_test_runner(window):
    """窗口加载后注入自检脚本。

    pywebview 的 js_api 方法在 JS 端返回 Promise，evaluate_js 同步求值拿不到
    await 后的值。解决：在 JS 端跑一个 async IIFE，把每个测试结果塞到
    window.__TEST__ 数组，Python 轮询读取。
    """
    # 等 pywebview 注入 API
    for _ in range(80):
        ready = window.evaluate_js("!!(window.pywebview && window.pywebview.api)")
        if ready:
            break
        time.sleep(0.1)
    else:
        _record("api_injected", False, "window.pywebview.api 未注入")
        DONE.set()
        return

    _record("api_injected", True, "window.pywebview.api 就绪")

    # 注入异步测试套件
    test_js = r"""
    (async () => {
      window.__TEST__ = window.__TEST__ || [];
      const T = window.__TEST__;
      const safe = async (name, fn) => {
        try { const v = await fn(); T.push({name, ok:true, detail:String(v).slice(0,180)}); }
        catch(e) { T.push({name, ok:false, detail:'ERR '+e.message}); }
      };
      await safe('echo', () => window.pywebview.api.echo('hi'));
      await safe('get_env', () => window.pywebview.api.get_env());
      await safe('list_presets', () => window.pywebview.api.list_presets());
      await safe('list_sessions', () => window.pywebview.api.list_sessions());
      await safe('plugin_list', () => window.pywebview.api.plugin_list());
      await safe('service_status', () => window.pywebview.api.service_status());
      await safe('build_argv', () => window.pywebview.api.build_argv({protocol:'ssh',target:'127.0.0.1:22'}));
      await safe('load_settings', () => window.pywebview.api.load_settings());
      window.__TEST_DONE__ = true;
    })();
    """
    window.evaluate_js(test_js)

    # 轮询等 JS 端跑完
    for _ in range(100):
        done = window.evaluate_js("!!window.__TEST_DONE__")
        if done:
            break
        time.sleep(0.15)
    else:
        _record("js_async_suite", False, "JS 测试套件超时未完成")
        DONE.set()
        return

    # 取结果
    raw = window.evaluate_js("JSON.stringify(window.__TEST__||[])")
    import json as _json
    try:
        results = _json.loads(raw) if raw else []
    except Exception:
        results = []
    for r in results:
        _record(r.get("name", "?"), bool(r.get("ok")), str(r.get("detail", ""))[:160])

    # 验证 DOM 是否渲染（仪表盘标题）
    try:
        title = window.evaluate_js(
            "document.querySelector('.view-title') ? document.querySelector('.view-title').textContent : ''"
        )
        _record("dom_rendered", bool(title), f"view-title={title!r}")
    except Exception as exc:
        _record("dom_rendered", False, str(exc))

    # 验证导航项数量
    try:
        nav_count = window.evaluate_js("document.querySelectorAll('.nav-item').length")
        _record("nav_items", nav_count and int(nav_count) >= 8, f"count={nav_count}")
    except Exception as exc:
        _record("nav_items", False, str(exc))

    # 验证导航是否可切换（点 tunnel-new 看标题变化）
    try:
        window.evaluate_js(
            "document.querySelector('[data-route=\"tunnel-new\"]').click()"
        )
        time.sleep(0.4)
        title2 = window.evaluate_js(
            "document.getElementById('topbar-title').textContent"
        )
        _record("nav_switch", title2 == "新建隧道", f"切换后标题={title2!r}")
    except Exception as exc:
        _record("nav_switch", False, str(exc))

    DONE.set()


def main():
    api = PythonApi()
    index_path = os.path.join(BASE_DIR, "ui", "index.html")
    window = webview.create_window(
        title="Shield GUI 自检",
        url=index_path,
        js_api=api,
        width=1280,
        height=820,
        hidden=False,
    )
    api.attach_window(window)
    # 窗口加载完成后启动测试
    def _on_loaded():
        threading.Thread(target=_js_test_runner, args=(window,), daemon=True).start()
    window.events.loaded += _on_loaded

    # 后台等待测试完成后关闭窗口
    def _closer():
        DONE.wait(timeout=45)
        time.sleep(1)
        try:
            window.destroy()
        except Exception:
            pass
    threading.Thread(target=_closer, daemon=True).start()

    webview.start()

    # 输出结果
    print("\n" + "=" * 60)
    print("Shield GUI 端到端自检结果")
    print("=" * 60)
    passed = sum(1 for r in RESULTS if r["ok"])
    for r in RESULTS:
        mark = "✓" if r["ok"] else "✗"
        print(f"  {mark} {r['name']:20s} {r['detail']}")
    print("-" * 60)
    print(f"  通过 {passed}/{len(RESULTS)}")
    print("=" * 60)
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
