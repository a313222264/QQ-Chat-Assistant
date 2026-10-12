"""语音包：MiniMax TTS 点播。

命令：
    说 一句话            合成语音发送（同一 MiniMax key，模型 speech-02-hd）
    语音帮助             可选音色列表与说明
音色在 config.yaml plugins.voice.voice_id 配置（默认青涩青年音）。
"""
import asyncio
import hashlib
import json
import time
import urllib.request
from pathlib import Path

from core import segments
from core.logger import get

log = get("voice")

VOICE_DIR = Path("data/voice")


async def tts_sync(cfg, text: str) -> Path:
    """调 MiniMax t2a_v2 合成语音，返回 mp3 文件路径。失败抛异常。"""
    import urllib.error

    api_key = cfg.get("ai.api_key", "") or ""
    base = (cfg.get("ai.base_url", "") or "https://api.minimaxi.com/v1").rstrip("/")
    body = json.dumps({
        "model": cfg.get("plugins.voice.model", "speech-02-hd"),
        "text": text[:180],  # 控制单条时长与费用
        "stream": False,
        "voice_setting": {
            "voice_id": cfg.get("plugins.voice.voice_id", "male-qn-qingse"),
            "speed": 1.0, "vol": 1.0, "pitch": 0,
        },
        "audio_setting": {"format": "mp3", "sample_rate": 32000},
    }).encode()
    req = urllib.request.Request(
        base.replace("/v1", "/v1") + "/t2a_v2", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
    status = resp.get("base_resp", {}).get("status_code")
    audio_hex = resp.get("data", {}).get("audio") or ""
    if status != 0 or not audio_hex:
        raise RuntimeError(f"TTS失败 status={status} msg={resp.get('base_resp', {}).get('status_msg')}")
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    path = VOICE_DIR / f"tts_{hashlib.md5((text + str(time.time())).encode()).hexdigest()[:10]}.mp3"
    path.write_bytes(bytes.fromhex(audio_hex))
    return path


async def on_message(bot, event) -> bool:
    if not bot.cfg.get("plugins.voice.enabled", True):
        return False
    text = segments.plain_text(event)
    if not text:
        return False

    if text.startswith("说 ") or text.startswith("念 "):
        content = text[2:].strip()
        if not content:
            await bot.send_text(event, "格式：说 一句话（180字内）")
            return True
        if not bot.cfg.get("ai.api_key", ""):
            await bot.send_text(event, "还没配置 API key，语音功能不可用")
            return True
        await bot.send_text(event, "🎙 合成中…")
        try:
            path = await asyncio.to_thread(tts_sync, bot.cfg, content)
        except Exception as e:
            log.warning("TTS失败: %s", e)
            await bot.send_text(event, f"语音合成失败：{e}")
            return True
        try:
            await bot.send_segments(event, [{"type": "record", "data": {"file": str(path.resolve())}}])
        except Exception as e:
            log.exception("语音发送失败")
            await bot.send_text(event, f"合成成功但发送失败（{e.__class__.__name__}），文件在 {path}")
        return True

    if text == "语音帮助":
        await bot.send_text(
            event,
            "🎙 发「说 xxx」我用语音说出来（180字内）\n"
            "音色可在 config.yaml plugins.voice.voice_id 更换，常用：\n"
            "male-qn-qingse 青涩青年 / female-shaonv 少女 / male-qn-jingying 精英青年 / narratoir 女主播",
        )
        return True

    return False
