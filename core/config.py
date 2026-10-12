"""配置加载：全部运行配置集中在 config.yaml，支持运行中重载。

用法：
    from core import config
    config.load()                # main.py 启动时调用一次
    config.current.get("ai.model", "MiniMax-M2")
"""
import copy
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
RUNTIME_STATE_PATH = ROOT / "data" / "runtime_state.json"

current = None  # Config 实例，模块级单例


class Config:
    def __init__(self, data: dict):
        self._data = data or {}

    def get(self, dotted_path: str, default=None):
        """按 'a.b.c' 点路径取配置，取不到返回 default。"""
        node = self._data
        for part in dotted_path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def raw(self) -> dict:
        return self._data

    def reload(self) -> bool:
        """从磁盘重读 config.yaml（保留运行时状态），成功返回 True。"""
        global current
        try:
            data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            return False
        self._data = data
        current = self
        return True


def load() -> Config:
    """启动时调用。config.yaml 不存在时给出明确报错。"""
    global current
    if not CONFIG_PATH.exists():
        raise SystemExit(
            f"未找到配置文件 {CONFIG_PATH}\n"
            f"请先复制 config.example.yaml 为 config.yaml 并填写。"
        )
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    current = Config(data)
    return current


# ---------- 运行时状态（插件开关等），独立于 config.yaml，管理员改了立即生效 ----------

def load_runtime_state() -> dict:
    try:
        return json.loads(RUNTIME_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_runtime_state(state: dict):
    RUNTIME_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
