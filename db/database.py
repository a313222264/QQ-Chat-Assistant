"""SQLite 数据库：消息存档、提醒、待办、记账、KV。

小流量场景直接同步 sqlite3（单事件循环内调用，微秒级开销），
加线程锁兜底防止调度线程并发。
"""
import json
import sqlite3
import threading
import time
from pathlib import Path


class Database:
    def __init__(self, data_dir: str = "data"):
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(Path(data_dir) / "bot.db"), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    msg_id TEXT,
                    chat_type TEXT NOT NULL,          -- group / private
                    group_id INTEGER,
                    user_id INTEGER NOT NULL,
                    sender_name TEXT,
                    text TEXT,
                    raw TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_msg_chat_ts ON messages (chat_type, group_id, ts);
                CREATE INDEX IF NOT EXISTS idx_msg_user_ts ON messages (user_id, ts);

                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_type TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    run_at INTEGER,                   -- 一次性：触发时间戳；循环型为 NULL
                    cron TEXT,                        -- 循环型：'daily 08:30' / 'weekly 1 09:00'
                    text TEXT NOT NULL,
                    created_ts INTEGER NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS todos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_type TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_ts INTEGER NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    chat_type TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    category TEXT DEFAULT '',
                    amount REAL NOT NULL,
                    note TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS points (
                    chat_type TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    points INTEGER NOT NULL DEFAULT 0,
                    last_sign TEXT DEFAULT '',
                    sign_streak INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (chat_type, chat_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_type TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    keyword TEXT NOT NULL,
                    last_urls TEXT DEFAULT '[]',
                    created_ts INTEGER NOT NULL
                );
                """
            )

    # ---------- 积分 ----------

    def get_points_row(self, chat_type: str, chat_id, user_id) -> dict:
        rows = self.query(
            "SELECT * FROM points WHERE chat_type=? AND chat_id=? AND user_id=?",
            (chat_type, chat_id, user_id),
        )
        return dict(rows[0]) if rows else None

    def add_points(self, chat_type: str, chat_id, user_id, delta: int):
        self.execute(
            "INSERT INTO points (chat_type, chat_id, user_id, points) VALUES (?,?,?,?) "
            "ON CONFLICT(chat_type, chat_id, user_id) DO UPDATE SET points = points + ?",
            (chat_type, chat_id, user_id, delta, delta),
        )

    def do_sign(self, chat_type: str, chat_id, user_id, today: str):
        """签到。返回 (first_time_today, streak_after, gained)。"""
        row = self.get_points_row(chat_type, chat_id, user_id)
        if row and row["last_sign"] == today:
            return False, row["sign_streak"], 0
        if row and row["last_sign"]:
            try:
                from datetime import date

                prev = date.fromisoformat(row["last_sign"])
                streak = row["sign_streak"] + 1 if (date.fromisoformat(today) - prev).days == 1 else 1
            except ValueError:
                streak = 1
        else:
            streak = 1
        gained = 5 + min(streak - 1, 5)  # 连签加成，最多+5
        if row:
            self.execute(
                "UPDATE points SET points=points+?, last_sign=?, sign_streak=? "
                "WHERE chat_type=? AND chat_id=? AND user_id=?",
                (gained, today, streak, chat_type, chat_id, user_id),
            )
        else:
            self.execute(
                "INSERT INTO points (chat_type, chat_id, user_id, points, last_sign, sign_streak) "
                "VALUES (?,?,?,?,?,?)",
                (chat_type, chat_id, user_id, gained, today, streak),
            )
        return True, streak, gained

    def points_leaderboard(self, chat_type: str, chat_id, limit: int = 10) -> list:
        return self.query(
            "SELECT user_id, points FROM points WHERE chat_type=? AND chat_id=? "
            "AND points > 0 ORDER BY points DESC LIMIT ?",
            (chat_type, chat_id, limit),
        )

    # ---------- 通用 ----------

    def execute(self, sql: str, params=()):
        with self._lock, self._conn:
            return self._conn.execute(sql, params)

    def query(self, sql: str, params=()) -> list:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # ---------- KV ----------

    def kv_get(self, key: str, default=None):
        rows = self.query("SELECT value FROM kv WHERE key=?", (key,))
        if not rows:
            return default
        try:
            return json.loads(rows[0]["value"])
        except ValueError:
            return rows[0]["value"]

    def kv_set(self, key: str, value):
        self.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )

    # ---------- 消息存档 ----------

    def insert_message(self, event: dict, text: str, raw: str):
        self.execute(
            "INSERT INTO messages (ts, msg_id, chat_type, group_id, user_id, sender_name, text, raw) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                int(event.get("time") or time.time()),
                str(event.get("message_id") or ""),
                event.get("message_type", ""),
                event.get("group_id"),
                event.get("user_id"),
                (event.get("sender") or {}).get("card")
                or (event.get("sender") or {}).get("nickname")
                or "",
                text,
                raw,
            ),
        )

    def search_messages(self, chat_type: str, group_id, user_id, keyword: str, limit: int = 10) -> list:
        """在指定会话里按关键词搜（keyword 为空则取最新N条）。"""
        sql = "SELECT * FROM messages WHERE chat_type=?"
        params: list = [chat_type]
        if chat_type == "group":
            sql += " AND group_id=?"
            params.append(group_id)
        else:
            sql += " AND user_id=?"
            params.append(user_id)
        if keyword:
            sql += " AND text LIKE ?"
            params.append(f"%{keyword}%")
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        return self.query(sql, params)

    def chat_stats(self, chat_type: str, group_id, since_ts: int) -> list:
        sql = "SELECT sender_name, user_id, COUNT(*) AS cnt FROM messages WHERE chat_type=? AND ts>=?"
        params: list = [chat_type, since_ts]
        if chat_type == "group":
            sql += " AND group_id=?"
            params.append(group_id)
        sql += " GROUP BY user_id ORDER BY cnt DESC LIMIT 10"
        return self.query(sql, params)

    def export_messages(self, chat_type: str, group_id, limit: int = 2000) -> list:
        sql = "SELECT * FROM messages WHERE chat_type=?"
        params: list = [chat_type]
        if chat_type == "group":
            sql += " AND group_id=?"
            params.append(group_id)
        sql += " ORDER BY ts ASC LIMIT ?"
        params.append(limit)
        return self.query(sql, params)

    def recent_messages(self, chat_type: str, group_id, since_ts: int, limit: int = 30) -> list:
        """取某群最近的聊天记录（正序），用于自主聊天构建上下文。"""
        rows = self.query(
            "SELECT * FROM messages WHERE chat_type=? AND group_id=? AND ts>=? "
            "ORDER BY ts DESC LIMIT ?",
            (chat_type, group_id, since_ts, limit),
        )
        return list(reversed(rows))

    def last_message_from(self, chat_type: str, group_id, user_id) -> dict:
        """某人（含机器人自己）在某群的最后一条消息，用于防自嗨。"""
        rows = self.query(
            "SELECT * FROM messages WHERE chat_type=? AND group_id=? AND user_id=? "
            "ORDER BY ts DESC LIMIT 1",
            (chat_type, group_id, user_id),
        )
        return rows[0] if rows else None

    def message_count(self) -> int:
        rows = self.query("SELECT COUNT(*) AS c FROM messages")
        return rows[0]["c"] if rows else 0
