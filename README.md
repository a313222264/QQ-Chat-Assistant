# QQ聊天助手（NapCat + Python + MiniMax）

基于 [NapCat](https://napneko.github.io/)（OneBot 11 协议端）+ 轻量自研 Python 框架的 QQ 聊天助手。

## 功能一览

| 插件 | 功能 |
|------|------|
| **ai_chat** | AI智能聊天（MiniMax-M3 + 函数调用）：私聊直接聊、群聊@触发、引用回复追问、多轮上下文、人设可随时改、防刷屏冷却/每日上限；**可自主调用工具**（搜索网页/查剑网3数据/发表情包），数据类回答强制注明来源和时间 |
| **memes** | 表情包：`data/memes/` 图库（文件名=关键词），命令 表情包[关键词]/表情包列表/刷新表情包/收藏表情；AI 按聊天语境自主发图 |
| **game_data** | 游戏数据：剑网3 接 jx3api（活动/开服/公告/骚话免token，金价需注册token）；三角洲行动走网页实时检索+AI整理（注明来源） |
| **proactive_chat** | 自主聊天：模拟群员按随机间隔自然插话（默认30~180分钟一次、每天5条上限、23:00-08:00静默、没人聊就不插话），10%概率带表情包 |
| **msg_archive** | 消息存档：全量群聊/私聊入 SQLite，支持 查记录/群统计/导出CSV到群文件 |
| **group_manage** | 群管理：入群欢迎、退群提示、关键词自动回复（群内命令增删）、戳一戳互动 |
| **life_assistant** | 生活助手：定时提醒（支持 30分钟后/明天9点/每天8:30/每周一9:00）、待办、记账、天气（open-meteo 免费无key）、每日播报 |
| **admin** | 管理命令：状态、插件开关、广播、重载配置、设置人设、禁言/踢人/全员禁言/精华/公告/撤回 |

群里发 **帮助** 可查看全部命令。

## 部署步骤（Windows）

### 1. 安装 NapCat（协议端，负责登录QQ收发消息）

已下载解压到本仓库 `NapCat/` 文件夹：

1. 双击 `NapCat/NapCatInstaller.exe`（一键安装，未装QQ会自动下载QQ）
2. 安装完成后进入 `NapCat.XXXX.Shell` 目录，双击 `napcat.bat` 启动
3. 按控制台提示用**QQ小号**扫码登录（⚠️ 一定用小号，有封号风险）
4. 浏览器打开控制台提示的 WebUI 地址（默认 `http://127.0.0.1:6099`，token 见控制台）

### 2. NapCat WebUI 里开正向 WebSocket

WebUI → 网络配置 → 新建 → **WebSocket服务器**：
- 端口填 `3001`（和下面 config.yaml 对应）
- 其他默认，保存启用

### 3. 配置本助手

编辑 `config.yaml`：
- `admin.superusers`: 改成你自己的QQ号（超级管理员）
- `ai.api_key`: 填 MiniMax 密钥（在 [platform.minimaxi.com](https://platform.minimaxi.com) 注册创建；base_url 以你账号后台文档为准）
- `napcat.ws_url`: 默认 `ws://127.0.0.1:3001`，与上一步一致

### 4. 启动

```
start_bot.bat
```

看到 `已连接 NapCat` 和 `机器人账号：xxx` 即成功。给机器人QQ发条私聊试试。

> 首次部署/换机器：先运行 `scripts/setup_venv.bat` 建立环境。

## 常用命令速查

```
帮助                      所有命令说明
查记录 关键词 [条数]       搜索会话记录
群统计                    今日发言排行
导出记录                  (群管理员) 导出CSV到群文件
表情包 / 表情包 关键词     发表情包（图库在 data/memes，文件名=关键词）
表情包列表 / 刷新表情包    查看关键词 / 重建索引
收藏表情                  发小号收藏的QQ表情
剑网3 活动 / 开服 / 公告 / 骚话    剑网3数据（免token，带数据时间）
剑网3 金价 [区服]          金价行情（需 config 填 jx3_token）
三角洲 关键词             三角洲行动实时检索+AI整理（注明来源）
提醒我 30分钟后 喝水
提醒我 每天8:30 打卡
添加待办 买菜 / 看待办 / 完成待办 1
记账 午饭 25 / 查账 今日|本月
天气 北京
添加关键词 触发词=回复     (群管理员)
禁言 @某人 10             (群管理员，0为解除)
踢人 @某人 / 全员禁言 开|关 / 公告 内容 / 设精华 / 撤回   (群管理员)
状态 / 插件列表 / 关闭插件 ai_chat / 开启插件 ai_chat     (超级用户)
设置人设 你是...          (超级用户) 修改AI人设
广播 群号 内容            (超级用户)
重载配置                  (超级用户) 改完 config.yaml 免重启
清空对话                  清空当前会话AI记忆
```

## AI 自主调用工具说明

AI（MiniMax-M3）支持函数调用，群里@它说自然语言即可，比如：
- "帮我查下剑网3现在的金价" / "今天剑网3有什么活动" → 自动调 jx3api
- "搜一下三角洲行动新赛季的改动" → 自动网页检索并整理，回答带来源链接
- "来个表情包" / 聊天氛围适合时 → 自动发图库里的表情包

数据类回答只依据检索结果并标注来源和时间，查不到会明说，不编造。

## 目录结构

```
qq-assistant/
├── main.py                  # 入口
├── config.yaml              # 实际配置（含密钥，勿外传）
├── config.example.yaml      # 配置模板（全量可配置项带注释）
├── start_bot.bat            # 启动
├── core/                    # 框架：WS连接(自动重连)/API封装/分发/权限/日志
├── plugins/                 # 五个功能插件，插件契约见 core/dispatcher.py
├── db/database.py           # SQLite（消息/提醒/待办/记账/KV）
├── scripts/                 # 测试与环境脚本
│   ├── mock_test.py         # 26项回归测试（不需要QQ）
│   └── ws_integration_test.py  # 模拟NapCat的WS集成测试
├── NapCat/                  # NapCat安装包（一键安装用）
├── data/                    # 运行数据：bot.db、导出文件、运行时状态
└── logs/                    # 滚动日志 bot.log
```

## 开发自测

```
scripts\run_tests.bat
```

## 常见问题

- **连不上 NapCat**：确认 NapCat 在运行、WebUI 里 WebSocket服务器 已启用且端口一致、token 填了（如果设了）。
- **AI不回复**：私聊会提示原因；群里静默。查 `logs/bot.log`。常见：api_key 没填、模型名不对、触发被冷却/上限拦住。
- **改了配置生效**：超级用户发 `重载配置`，或重启 start_bot.bat。
- ** NapCat 更新后 QQ 掉了**：重跑 NapCat 目录的安装器更新，NapCat 有自动跟随更新机制。
- **安全**：config.yaml 含 API key，不要截图/上传；机器人只用小号；白名单群建议先填自己的群试跑（`admin.whitelist_groups`）。
