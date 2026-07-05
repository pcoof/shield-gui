"""配置存储：探测 Shield 官方配置目录 + JSON 兜底。

策略（用户确认：首次运行触发后探测）：
1. 启动时扫描候选路径，找到则读写其中的预设/凭证文件
2. 若未找到，标记 needs_trigger=True；首次创建连接/启动服务前实跑 `shield plugin list`
   触发 shield 生成官方目录，再重新探测
3. 找到官方文件则叠加其格式读写；格式不可解析时回退到自带 JSON 兜底
4. 凭证字段（密码/私钥）只保存引用，不另行明文落盘
"""
from __future__ import annotations

import json
import os
import threading
from typing import Optional

# 官方目录候选（按优先级）
_CANDIDATE_DIRS = [
    os.path.join(os.path.expanduser("~"), ".shield"),
    os.path.join(os.environ.get("APPDATA", ""), "ShieldCLI"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "ShieldCLI"),
    os.path.join(os.environ.get("APPDATA", ""), "yishield"),
    os.path.join(os.environ.get("APPDATA", ""), "Shield"),
]

# 兜底目录
_FALLBACK_DIR = os.path.join(os.environ.get("APPDATA", ""), "ShieldGUI")
_FALLBACK_PRESETS = "presets.json"
_FALLBACK_SETTINGS = "settings.json"

# 官方目录下常见的预设/配置文件名
_OFFICIAL_PRESET_FILES = ["apps.json", "presets.json", "connections.json"]
_OFFICIAL_CONFIG_FILES = ["config.json", "config.yaml", "shield.yaml"]


class ConfigStore:
    def __init__(self, shield_exe: str):
        self.shield_exe = shield_exe
        self._lock = threading.Lock()
        self._official_dir: Optional[str] = None
        self._fallback_dir = _FALLBACK_DIR
        self._detect()

    def _detect(self) -> None:
        """启动时扫描候选路径。"""
        for d in _CANDIDATE_DIRS:
            if d and os.path.isdir(d):
                # 目录存在且有内容（非空）才算官方目录
                try:
                    if any(os.scandir(d)):
                        self._official_dir = d
                        return
                except OSError:
                    continue
        # 未找到
        self._official_dir = None

    def ensure_triggered(self, runner_run_cli) -> str:
        """首次运行触发：跑一次 shield plugin list，重新探测。runner_run_cli 是
        ShieldRunner.run_cli 的引用。返回当前生效目录。"""
        with self._lock:
            if self._official_dir is None:
                # 触发 shield 生成目录
                runner_run_cli(["plugin", "list"], timeout=30)
                self._detect()
            effective = self._official_dir or self._fallback_dir
        # 确保目录存在
        os.makedirs(effective, exist_ok=True)
        os.makedirs(self._fallback_dir, exist_ok=True)
        return effective

    # ---------- 状态查询 ----------

    def status(self) -> dict:
        return {
            "official_dir": self._official_dir,
            "fallback_dir": self._fallback_dir,
            "needs_trigger": self._official_dir is None,
            "effective_dir": self._official_dir or self._fallback_dir,
            "candidates": [d for d in _CANDIDATE_DIRS if d],
        }

    # ---------- 预设（连接配置）CRUD ----------

    def _presets_path(self) -> str:
        # 优先官方目录下的 apps.json，否则兜底
        if self._official_dir:
            for name in _OFFICIAL_PRESET_FILES:
                p = os.path.join(self._official_dir, name)
                if os.path.isfile(p):
                    return p
            # 官方目录存在但还没预设文件 → 在官方目录新建
            return os.path.join(self._official_dir, "apps.json")
        return os.path.join(self._fallback_dir, _FALLBACK_PRESETS)

    def list_presets(self) -> list:
        path = self._presets_path()
        if not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "apps" in data:
                return data["apps"]
            if isinstance(data, list):
                return data
            return []
        except (OSError, json.JSONDecodeError):
            return []

    def save_preset(self, preset: dict) -> dict:
        path = self._presets_path()
        presets = self.list_presets()
        # 分配 id
        pid = preset.get("id")
        if not pid:
            pid = f"p_{len(presets) + 1:03d}_{int(__import__('time').time()) % 100000}"
            preset["id"] = pid
        # 替换或追加
        replaced = False
        for i, p in enumerate(presets):
            if p.get("id") == pid:
                presets[i] = preset
                replaced = True
                break
        if not replaced:
            presets.append(preset)
        self._write_presets(path, presets)
        return preset

    def del_preset(self, pid: str) -> bool:
        path = self._presets_path()
        presets = self.list_presets()
        new = [p for p in presets if p.get("id") != pid]
        if len(new) == len(presets):
            return False
        self._write_presets(path, new)
        return True

    def _write_presets(self, path: str, presets: list) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # 兼容官方 apps.json 结构：若已存在为 {"apps": [...]} 则保持
        wrapper = {"apps": presets}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict) and "apps" in raw:
                    raw["apps"] = presets
                    wrapper = raw
            except (OSError, json.JSONDecodeError):
                pass
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(wrapper, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    # ---------- 应用设置 ----------

    def load_settings(self) -> dict:
        path = os.path.join(self._fallback_dir, _FALLBACK_SETTINGS)
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def save_settings(self, settings: dict) -> bool:
        os.makedirs(self._fallback_dir, exist_ok=True)
        path = os.path.join(self._fallback_dir, _FALLBACK_SETTINGS)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return True
        except OSError:
            return False
