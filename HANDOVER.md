# QQ聊天助手 项目交接文档

| 项 | 内容 |
|---|---|
| 文档版本 | v1.0（2026-11-17） |
| 代码基线 | main @ `b13e568`（已全部推送到 GitHub） |
| 仓库地址 | https://github.com/a313222264/QQ-Chat-Assistant （公开） |
| 本机路径 | `D:\小编程\qq-assistant` |
| 交接范围 | 全部源码、部署脚本、运行环境、账号与密钥位置、已知问题与待办 |

---

## 1. 项目概述

基于 **NapCat（OneBot 11 协议端）+ 自研 Python 框架 + MiniMax 大模型** 的 QQ 群聊机器人，昵称"东小0"。

一句话：群里能聊天（带长期记忆与工具调用）、查游戏数据（剑网3/三角洲）、发表情包、玩小游戏（积分体系）、定时推送（日报/金价/订阅）、TTS 语音、链接总结、识图吐槽；有完整的群管理命令与自愈式运维体系。

**当前状态（2026-11-17）**：机器人**未在运行**（用户手动语义：不开机自启）；服务器 7×24 方案已备好但**尚未执行**（见 §10 P0）。

---

## 2. 系统架构

```
┌──────────────────┐  OneBot 11 正向WS   ┌───────────────────────┐
│ NapCat.Shell     │ ◄────────────────► │ Python 机器人 main.py  │
│ (无头QQ,挂小号)    │   ws://127.0.0.1:3001 │ 12插件 + APScheduler   │
│ WebUI :6099      │   (事件上报/API调用)  │ SQLite + MiniMax API   │
└──────────────────┘                    └───────────────────────┘
        │                                          │
   QQ服务器                                 外部服务：MiniMax(chat/TTS)
                                              jx3api(剑网3数据)
                                              open-meteo(天气)
                                              cn.bing.com(搜索兜底)
```

两种运行形态：
- **本机 Windows（现状）**：`NapCat\Shell\launcher-user.bat` 启动协议端 + `venv\Scripts\python.exe main.py` 启动机器人；看门狗计划任务自动自愈
- **云服务器 Docker（已备好未部署）**：`deploy/docker-compose.yml`，NapCat 官方镜像 + 机器人镜像，`ws://napcat:3001` 容器内网通信

版本强耦合：**NapCat v4.18.37 ↔ QQ 9.9.33-52230**（本机 `D:\qq`）。升级必须成对，否则注入静默失败（历史踩坑，见 §9）。

---

## 3. 代码地图

```
qq-assistant/
├── main.py                     # 入口：装配 config/logger/db/dispatcher/bot/连接/调度器/健康巡检
├── config.yaml                 # ★实际配置（含密钥，已.gitignore，不入库）
├── config.example.yaml         # 配置模板（全量注释）
├── requirements.txt            # websockets/PyYAML/APScheduler/openai/httpx/qrcode[pil]
├── start_bot.bat               # 本机启动机器人（仅python，不含NapCat）
├── core/
│   ├── connection.py           # WS连接+断线重连+API回包匹配+发送失败标记(send_fail.flag)
│   ├── api.py                  # Bot对象：OneBot API封装(send_group_msg/ban/kick/...)
│   ├── dispatcher.py           # 插件链路分发：admin→msg_archive→group_manage→memes→
│   │                           #   game_data→life_assistant→media→fun→voice→digest→
│   │                           #   ai_chat→proactive_chat（on_message返True截断）
│   ├── tools.py                # AI函数调用工具注册表（@register_tool）
│   ├── ai_completion.py        # LLM客户端缓存(60s超时)+chat_once_sync+摘要搜索
│   ├── websearch.py            # 必应HTML抓取搜索兜底
│   ├── segments.py             # 消息段构造/解析(at/图片/引用/@判定)
│   ├── permission.py           # 超管/群管/白名单
│   ├── config.py               # 点路径配置 + 运行时状态(data/runtime_state.json)
│   └── logger.py               # UTF-8双输出(控制台+滚动文件)
├── plugins/                    # 插件契约：on_message(bot,event)->bool / on_notice / on_start
│   ├── ai_chat.py              # ★核心：AI聊天+函数调用循环(最多3轮)+上下文滚动摘要
│   │                           #   触发：私聊/@/名字提及(ai.name_aliases)/15%被动插嘴
│   ├── msg_archive.py          # 全量消息入SQLite + 查记录/群统计/导出CSV（含"收到消息"日志）
│   ├── group_manage.py         # 入群欢迎/退群/关键词自动回复(kv存储)/戳一戳 + 禁言踢人等管理命令
│   ├── memes.py                # 表情包图库(data/memes文件名=关键词) + send_meme工具
│   ├── game_data.py            # 剑网3(jx3api:活动/开服/公告/金价) + 三角洲(搜索) + query_jx3/web_search工具
│   ├── life_assistant.py       # 提醒/待办/记账/天气(自动定位+AI总结) + get_weather工具
│   ├── media.py                # 总结<链接> + 吐槽(ocr_image→LLM)
│   ├── fun.py                  # 签到积分/运势(确定性hash)/RPS/猜数字/成语接龙/每日一题
│   ├── voice.py                # 说xxx → MiniMax TTS(speech-02-hd) → record段发送
│   ├── digest.py               # 群日报(08:00)/金价播报(08:30)/关键词订阅(18:00) 定时任务
│   └── proactive_chat.py       # 自主插话：随机30-180min/日限5/静默23-8/防自嗨/10%带表情包
├── db/database.py              # SQLite：messages/reminders/todos/ledger/kv/points/subscriptions
├── scripts/
│   ├── mock_test.py            # ★62项回归测试（不需要QQ，改代码后必跑）
│   ├── ws_integration_test.py  # 4项WS集成测试（本地模拟NapCat服务器）
│   ├── healthcheck.py          # status/sendtest/login[qr] 三命令（启动器/看门狗共用）
│   ├── watchdog.py             # 看门狗：normal(标记自愈)/resume(唤醒自检) 两模式
│   ├── start_all.ps1           # 桌面启动器v2（菜单[1]-[6]，UTF-8需BOM）
│   ├── setup_venv.bat / run_tests.bat / _make_desktop_launcher.py（GBK bat生成器）
│   └── _download_memes.py      # 表情包下载脚本（image-search OSS直链）
├── deploy/                     # ★服务器部署套件（未执行）
│   ├── Dockerfile              # 机器人镜像 python:3.12-slim
│   ├── docker-compose.yml      # napcat(mlikiowa/napcat-docker) + bot
│   └── 服务器部署指南.md        # 小白级步骤（买机→docker→上传→扫码→验证）
├── NapCat/Shell/               # NapCat协议端本体（.gitignore）
│   ├── launcher-user.bat       # 启动（从注册表定位D:\qq\QQ.exe注入）
│   └── config/onebot11_2531285699.json  # 预写的WS服务器3001配置
├── data/                       # bot.db/memes(28张)/runtime_state.json/send_fail.flag
└── logs/                       # bot.log(滚动) / watchdog.log
```

**新增插件方法**：`plugins/` 建模块实现 `on_message`，在 `core/dispatcher.py` 的 `PLUGIN_MODULES` 按优先级插队；需要 AI 主动调用则用 `core/tools.py` 的 `@register_tool`。

---

## 4. 账号与密钥（位置说明，不含明文）

| 凭据 | 位置 | 说明 |
|---|---|---|
| MiniMax API Key | `config.yaml → ai.api_key` | chat(M3)+TTS共用，base_url 必须是 `https://api.minimaxi.com/v1`（多个i） |
| jx3api 令牌 | `config.yaml → plugins.game_data.jx3_token` | 用户付费购买，**有额度限制**（金价接口消耗） |
| NapCat WebUI token | `NapCat/Shell/config/webui.json` | 管理面板 6099 登录凭证 |
| 机器人QQ | 2531285699（东小0） | 登录靠扫码/快速登录，**密码不存于任何文件** |
| 超级管理员 | config.yaml → admin.superusers = 用户主号 | |
| 工作群 | 1093880151 风檐春秋（proactive_chat.groups / digest 推送目标） | 白名单为空=全群开放 |

⚠️ `config.yaml`、`NapCat/`、`data/`、`logs/`、`venv/` 均在 `.gitignore`，公开仓库无泄露。

---

## 5. 运行操作手册

### 5.1 本机启动/停止（当前使用方式）
- **启动**：双击桌面 `QQ机器人一键启动.bat` → 菜单回车（=[1]启动/重启）→ NapCat起来后如需扫码会自动弹二维码PNG → 机器人自动连上。验证：菜单[4]发送通道测试 retcode=0。
- **停止**：关闭 NapCat 和机器人两个黑窗口。
- 菜单全表：[1]启动/重启 [2]全面修复(只杀机器人QQ不碰用户自己的QQ) [3]自检诊断 [4]发送测试 [5]看门狗开/关 [6]保活模式(禁睡眠)

### 5.2 计划任务（Windows）
| 任务 | 状态(2026-11-17) | 作用 |
|---|---|---|
| `QQBotWatchdog` | **Disabled（用户手动关闭）** | 每30分钟巡检自愈（机器人主程序未运行时自动跳过=手动语义） |
| `QQBotWatchdog-Resume` | Ready | 睡眠唤醒事件→60秒后带发送实测自检 |

恢复巡检：启动器[5]→on，或 `schtasks /Change /TN QQBotWatchdog /ENABLE`。

### 5.3 服务器 7×24 部署（待执行）
完整步骤见 `deploy/服务器部署指南.md`。要点：轻量服务器2C2G Ubuntu → 装 docker → clone仓库 + scp传`config.yaml`和`data/memes` → `sed` 把 ws_url 改为 `ws://napcat:3001` → 改 compose 的 WEBUI_TOKEN → 6099 临时放行扫码 → WebUI 建 WS服务器3001 → `docker compose up -d --build`。
⚠️ **服务器上线后本机 NapCat 必须停**（同QQ号互踢）。

---

## 6. 测试与质量

```
scripts\run_tests.bat    # 62项mock回归(无需QQ) + 4项WS集成(模拟NapCat)
```
- **改动代码后必跑**（用户的工作习惯要求：根因修复+全面回归+不影响现有功能）
- mock测试覆盖：全部命令路径、权限校验、AI工具循环回填、摘要竞态、passive插嘴SKIP、游戏状态机、订阅去重等
- 已知测试技巧：摘要相关断言前必须等 `_running_sum`/`_pending_sum` 排空（真实异步竞态）；mock的LLM补丁点是 `ai_chat._chat_with_tools` 和各插件的 `chat_once_sync` 模块级绑定

---

## 7. 数据说明

- `data/bot.db`（SQLite）：messages（存档+自主聊天上下文来源）、reminders/todos/ledger、kv（人设/关键词/常驻城市/金价昨日值）、points（积分签到）、subscriptions（订阅）
- **内存态不落盘**：AI对话上下文与滚动摘要（`_contexts/_summaries`）、游戏进行中状态（猜数字/接龙/每日一题）、passive冷却——**机器人重启即失忆**（见 §10 P2）
- `logs/bot.log`：`收到消息: [群号] 名字: 内容` INFO 日志是排障第一入口；`健康巡检` 每10分钟一条；`⚠ 会话疑似死亡` = 连续3次巡检失败

---

## 8. 排障决策树（经验固化）

**症状：群里@机器人不回复**
1. `logs/bot.log` 尾部有没有 `收到消息`？
   - 没有 → QQ层挂了 → 查 QQ.exe 实例 / 3001端口 → 启动器[3]自检 → 大概率[2]全面修复（需扫码）
   - 有 → 继续看有无 `AI调用工具`/httpx 200 → 有则看是否发送失败 retcode 1200 → 会话假死，看门狗应在30分钟内自愈（或手动[2]）
2. **判断"在线"不能只看端口/进程/已连接，必须实测发送 retcode=0**（历史三次掉线全是"假在线"）

**历史三大故障模式（已固化自愈，原理见 §9 坑表）**：
1. QQ进程悄死留僵尸壳占端口（端口在、API假响应）
2. 会话被踢：能收不能发，retcode=1200"网络连接异常"（疑风控/多实例互踢）
3. 多套QQ实例叠跑抢数据（用户自己的QQ与机器人QQ是独立实例可并存；叠跑的是同数据目录的多套）

---

## 9. 关键踩坑速查（改代码前必读，详见 memory/qq-assistant-pitfalls.md）

| 坑 | 要点 |
|---|---|
| NapCat↔QQ版本 | 4.18.37 只配 QQ 9.9.33-52230，错配=注入静默失败 |
| 单实例锁 | 启动 NapCat 前用户自己的 QQ 必须先关一次；NapCat QQ 特征=命令行 `--enable-logging` |
| WS死锁 | connection.run() 里登录API必须在收包循环独立task之后（回包没人读会死锁） |
| MiniMax | base_url `api.minimaxi.com/v1`（多个i）；M3带`<think>`已剥离；偶发529过载（60s超时兜底）；账号无H系列/视觉模型 |
| IAB浏览器 | 对NapCat WebUI页面的Playwright/CUA点击全部无效，走HTTP API（login hash=SHA256(token+".napcat")） |
| Windows编码 | bat必须GBK（中文路径）、ps1必须UTF-8 BOM、schtasks输出GBK要decode('gbk') |
| 会话摘要竞态 | 后台摘要任务在途时清空对话会被写回，测试/操作前等任务排空 |
| GitHub直连 | 本机到 github.com 时好时坏，push失败重试即可（无代理环境） |

---

## 10. 已知问题与风险清单（★交接重点）

### P0 — 服务器迁移未执行
- **现象**：机器人仍依赖用户本机，电脑关机=机器人下线（用户的核心诉求未闭环）
- **现状**：`deploy/` 三件套+指南已就绪并推送，用户尚未购买服务器
- **建议**：陪用户走完指南（约20分钟）；上线后本机端停用；此问题即消除

### P1 — 看门狗巡检处于关闭状态
- **现象**：`QQBotWatchdog` 计划任务 Disabled（用户10月底手动关闭，可能嫌打扰/忘了）
- **影响**：本机运行期间掉线不再自动自愈，需手动启动器[2]
- **建议**：与用户确认是否重新开启（30分钟一次+最小化启动，已降噪）；上服务器后本机看门狗可永久禁用

### P1 — QQ会话周期性死亡（根因未除）
- **现象**：运行数小时后会话被踢（能收不能发，retcode 1200），10-12 当天三次
- **根因**：未定位到铁证；候选=腾讯对机器人账号的风控 / NapCat无头登录的会话保活缺陷。看门狗"杀实例重启+快速登录"是**缓解不是根治**
- **建议**：服务器部署后观察频率（Linux+Docker环境下风控特征可能不同）；若仍频繁，考虑降低主动行为频率（proactive_chat/passive参数）或换号测试对照
- **连带**：快速登录凭证时好时坏，失效时必须人工扫码（QQ侧限制，无解）

### P2 — 运行态数据不持久
- **现象**：AI对话上下文、滚动摘要、游戏进行中状态全在内存，重启丢失；SQLite只存消息/积分/kv
- **建议**：低优先级。若要做：`_contexts/_summaries` 定期落 kv 表，启动时恢复；游戏状态同理

### P2 — bing 搜索兜底脆弱
- **现象**：`core/websearch.py` 鈬 cn.bing.com 的 HTML `b_algo` 块，页面改版即失效（失效表现为AI答"搜索没有返回结果"）
- **建议**：改版时换选择器或接正式搜索API（博查等，key可配）

### P3 — 已知小额成本与功能局限
- jx3api 令牌按次计费（金价接口），额度用尽需续费；TTS 按字符计费
- 识图吐槽=OCR路线（账号无视觉模型），纯画面图只能趣味兜底
- NapCat 升级需与 QQ 版本成对验证（等 NapCat 官方适配新QQ再动）
- MiniMax 偶发 529 过载：已有60秒超时+失败兜底文案，无需处理

### 备注
- 桌面启动器/看门狗/healthcheck 的进程检测部分为 Windows 专用；服务器端 Docker 形态不依赖它们（容器 restart:always 自愈）
- `scripts/` 下 `_` 前缀脚本为一次性工具，可忽略

---

## 11. 待办事项（优先级排序）

1. 【P0】执行服务器部署（§5.3），迁移后停本机端、开启服务器端
2. 【P1】与用户确认看门狗去留；服务器上线后本机两任务可 `schtasks /Delete`
3. 【P2】上下文/摘要/游戏状态持久化（§10 P2 方案）
4. 【P2】websearch 加备用解析器或正式搜索API
5. 【P3】新群若要主动插话/日报，把群号加进 `proactive_chat.groups` / `digest.push_groups`（当前仅 1093880151）
6. 【P3】NapCat 升级跟踪（QQ强制更新时：等 NapCat 适配 → 成对升级 → 跑62项回归+真发消息验证）

---

## 12. 关键历史决策（为什么是现在这样）

| 决策 | 理由 |
|---|---|
| 自研框架不用 NoneBot2 | 用户要求代码透明可控、依赖少好排查 |
| MiniMax-M3 | 用户账号无H系列；M3实测支持并行函数调用；`<think>`已剥离 |
| 看门狗=手动语义 | 用户明确要求开机不自启：main.py没跑就看门狗绝不拉起任何东西 |
| 只杀机器人QQ实例 | 用户要求重启不影响自己日常用QQ；以 `--enable-logging` 特征区分 |
| 上下文滚动摘要 | 修"聊天断断续续"：硬截断失忆→150字摘要随身带 |
| 表情包文件名=关键词 | 完全可控、零API依赖，AI按情绪挑图 |
| Docker双容器而非单机直跑 | NapCat官方镜像免装QQ桌面端；compose内网隔离3001不暴露公网 |

---

## 13. 移交核对清单

- [ ] 源码：GitHub main@b13e568 与本机 `D:\小编程\qq-assistant` 一致（已确认 clean）
- [ ] 密钥：拿到 `config.yaml`（MiniMax key + jx3api令牌）与 WebUI token 所在文件
- [ ] 账号：机器人QQ 2531285699 的手机端登录方式（扫码用）
- [ ] 环境：本机 venv 可跑 `scripts\run_tests.bat`（62项全绿）
- [ ] 部署：读 `deploy/服务器部署指南.md`，确认理解"同号互踢"约束
- [ ] 运维：通读 §8 排障决策树与 §9 坑表
- [ ] 用户习惯：根因修复、改后全面回归、不动现有功能、输出无乱码（中文环境编码敏感）
