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

    # 健康巡检：每10分钟只读检查一次，连续3次异常在日志醒目告警
    health_fails = {"n": 0}

    async def health_patrol():
        if not (bot.conn and bot.conn.connected.is_set()):
            return  # 未连接阶段由连接层处理，不算巡检失败
        try:
            info = await bot.get_login_info()
            st = await bot.get_status()
            health_fails["n"] = 0
            log.info("健康巡检: 在线=%s 账号=%s", st.get("online"), info.get("nickname"))
        except Exception as e:
            health_fails["n"] += 1
            log.warning("健康巡检失败(%d/3): %s", health_fails["n"], e.__class__.__name__)
            if health_fails["n"] >= 3:
                log.error("⚠ 会话疑似死亡（连续3次巡检失败），建议运行桌面启动器 → 全面修复")

    scheduler.add_job(health_patrol, "interval", minutes=10, id="health_patrol")
    scheduler.start()
    log.info("健康巡检已注册（每10分钟）")

    try:
        await conn.run()
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已退出")
