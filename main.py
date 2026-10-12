"""QQ聊天助手入口：python main.py

启动流程：加载配置 -> 日志 -> 数据库 -> 插件 -> 调度器 -> 连接 NapCat。
Ctrl+C 优雅退出。
"""
import asyncio
import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core import config as config_mod
from core import logger as logging_mod
from core.api import Bot
from core.connection import NapCatConnection
from core.dispatcher import Dispatcher
from core.logger import get
from db.database import Database

log = get("main")


async def main():
    cfg = config_mod.load()
    logging_mod.setup(cfg)
    log.info("=" * 40)
    log.info("QQ聊天助手启动（NapCat + OneBot 11）")
    log.info("连接目标: %s", cfg.get("napcat.ws_url"))

    db = Database(cfg.get("data_dir", "data"))
    dispatcher = Dispatcher(cfg, db)
    dispatcher.load_plugins()

    bot = Bot(cfg, db, dispatcher)
    conn = NapCatConnection(cfg, bot, dispatcher)
    bot.conn = conn
    bot.started_at = time.time()

    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    bot.scheduler = scheduler

    try:
        await conn.run()
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已退出")
