"""日志：控制台 + 文件双输出，全部 UTF-8，避免中文乱码。"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_initialized = False


def setup(cfg):
    global _initialized
    level_name = cfg.get("log.level", "INFO")
    log_dir = Path(cfg.get("log.dir", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    root = logging.getLogger()
    root.setLevel(getattr(logging, level_name, logging.INFO))
    for h in list(root.handlers):
        root.removeHandler(h)

    # 控制台：强制 UTF-8（Windows 默认 GBK 会导致中文乱码/报错）
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # 文件：滚动日志，最大 5MB 保留 3 份
    fh = RotatingFileHandler(
        log_dir / "bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # httpx/openai 等第三方库日志降噪
    for noisy in ("httpx", "httpcore", "openai", "websockets", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _initialized = True


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
