"""SQLite 数据库层：建表、连接、设置读写、数据目录管理。"""
import re
import sqlite3
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent / "data"
UPLOAD_DIR = BASE_DIR / "photos"    # 原始拍照
FIGURE_DIR = BASE_DIR / "figures"   # 裁剪出的题目图形
DB_PATH = BASE_DIR / "cuotiben.db"

for d in (BASE_DIR, UPLOAD_DIR, FIGURE_DIR):
    d.mkdir(parents=True, exist_ok=True)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL DEFAULT '',
            answer TEXT NOT NULL DEFAULT '',
            knowledge TEXT NOT NULL DEFAULT '',
            figure TEXT NOT NULL DEFAULT '',
            photo TEXT NOT NULL DEFAULT '',
            wrong_count INTEGER NOT NULL DEFAULT 1,
            consecutive_correct INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',   -- active / mastered
            source TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            last_wrong_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT '',
            strategy TEXT NOT NULL DEFAULT '{}',     -- 组卷参数 JSON
            created_at TEXT NOT NULL,
            graded INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS paper_items (
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            result TEXT NOT NULL DEFAULT '',          -- '' / right / wrong
            PRIMARY KEY (paper_id, question_id)
        );

        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            paper_id INTEGER,
            result TEXT NOT NULL,                     -- right / wrong
            attempted_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        -- 变式练习批次：挂在原错题名下，独立于重做卷体系，不入题库
        CREATE TABLE IF NOT EXISTS variant_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            batch_no INTEGER NOT NULL,                -- 第几批，从 1 递增
            status TEXT NOT NULL DEFAULT 'pending',   -- pending / all_right / has_wrong
            created_at TEXT NOT NULL,
            graded_at TEXT NOT NULL DEFAULT ''
        );

        -- 变式批次内的题目（AI 生成的同类变式题）
        CREATE TABLE IF NOT EXISTS variant_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL REFERENCES variant_batches(id) ON DELETE CASCADE,
            seq INTEGER NOT NULL,                     -- 批内序号，从 1 开始
            content TEXT NOT NULL,
            answer TEXT NOT NULL,
            knowledge TEXT NOT NULL DEFAULT '',
            result TEXT NOT NULL DEFAULT '',          -- '' / right / wrong
            user_answer TEXT NOT NULL DEFAULT '',
            answered_at TEXT NOT NULL DEFAULT ''
        );
        """
    )
    conn.commit()
    conn.close()


def get_setting(key: str, default: str = "") -> str:
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_dt(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def get_question(question_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
    conn.close()
    return row


def eligible_questions(days: int, limit: int = 0):
    """按间隔策略选出可重做的题：距上次做错(或录入)超过 days 天，错误多的优先。days<=0 表示不限。"""
    conn = get_db()
    rows = conn.execute("SELECT * FROM questions WHERE status='active'").fetchall()
    conn.close()
    now = datetime.now()
    out = []
    for q in rows:
        if days > 0:
            lw = parse_dt(q["last_wrong_at"]) or parse_dt(q["created_at"])
            if lw is None or (now - lw).days < days:
                continue
        out.append(q)
    out.sort(key=lambda q: (-q["wrong_count"], q["last_wrong_at"] or ""))
    return out[:limit] if limit > 0 else out


# ---------- 答案归一化判分（变式练习自动判分用，唯一实现） ----------

_FULL2HALF = str.maketrans(
    "０１２３４５６７８９（）［］｛｝，：；．？！％＋－＝／＊",
    "0123456789()[]{}:;.?!%+-=/*",
)


def normalize_answer(value: str) -> str:
    """答案归一化：全角转半角、去空白与乘除同义符、去结尾句读、统一小写。"""
    if value is None:
        return ""
    t = str(value).translate(_FULL2HALF)
    t = t.replace("×", "*").replace("÷", "/").replace("−", "-")
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"[。，,、.]+$", "", t)
    t = t.replace(",", "").replace("，", "")   # 去千分位/列表逗号，如 1,000 -> 1000
    return t.lower()


def _try_number(s: str):
    """把 '3.5' / '1/2' 之类转成数值，转不了返回 None。"""
    try:
        return float(s)
    except ValueError:
        pass
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)/(-?\d+(?:\.\d+)?)", s)
    if m and float(m.group(2)) != 0:
        return float(m.group(1)) / float(m.group(2))
    return None


def answers_equal(user_answer: str, ref_answer: str) -> bool:
    """自动判分比对：双方归一化后，数值（含 a/b 分数）按数值判等，否则文本精确比对。"""
    u, r = normalize_answer(user_answer), normalize_answer(ref_answer)
    if not u or not r:
        return False
    if u == r:
        return True
    nu, nr = _try_number(u), _try_number(r)
    if nu is not None and nr is not None:
        return abs(nu - nr) < 1e-9
    return False


# ---------- 变式练习 ----------

def has_pending_batch(question_id: int) -> bool:
    """该题是否还有待作答的变式批次（同一题同时只允许一个，硬挡重复生成）。"""
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM variant_batches WHERE question_id=? AND status='pending' LIMIT 1",
        (question_id,),
    ).fetchone()
    conn.close()
    return row is not None


def get_pending_batch(question_id: int):
    """返回该题当前的待作答批次（无则 None）。"""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM variant_batches WHERE question_id=? AND status='pending' LIMIT 1",
        (question_id,),
    ).fetchone()
    conn.close()
    return row


def next_batch_no(question_id: int) -> int:
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(MAX(batch_no), 0) + 1 AS n FROM variant_batches WHERE question_id=?",
        (question_id,),
    ).fetchone()
    conn.close()
    return row["n"]


def create_variant_batch(question_id: int, items: list) -> int:
    """创建变式批次并写入题目，返回批次 id。items: [{"content","answer","knowledge"}]。"""
    if not items:
        raise ValueError("没有可写入的变式题")
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO variant_batches(question_id, batch_no, status, created_at) "
            "VALUES(?, ?, 'pending', ?)",
            (question_id, next_batch_no(question_id), now_str()),
        )
        batch_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO variant_items(batch_id, seq, content, answer, knowledge) VALUES(?,?,?,?,?)",
            [
                (batch_id, i + 1, it["content"], it["answer"], it.get("knowledge", ""))
                for i, it in enumerate(items)
            ],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return batch_id


def get_variant_batch(batch_id: int):
    """取单个批次（连带原题的题干/答案/图形，供页面展示），无则 None。"""
    conn = get_db()
    row = conn.execute(
        """
        SELECT b.*, q.content AS q_content, q.answer AS q_answer,
               q.knowledge AS q_knowledge, q.figure AS q_figure
        FROM variant_batches b JOIN questions q ON q.id = b.question_id
        WHERE b.id=?
        """,
        (batch_id,),
    ).fetchone()
    conn.close()
    return row


def get_variant_items(batch_id: int) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM variant_items WHERE batch_id=? ORDER BY seq", (batch_id,)
    ).fetchall()
    conn.close()
    return rows


def get_variant_batches(question_id: int) -> list:
    """某题的全部批次（含对错统计），新批次在前。"""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT b.*,
               COUNT(v.id) AS item_count,
               SUM(CASE WHEN v.result='right' THEN 1 ELSE 0 END) AS right_count,
               SUM(CASE WHEN v.result='wrong' THEN 1 ELSE 0 END) AS wrong_count
        FROM variant_batches b
        LEFT JOIN variant_items v ON v.batch_id = b.id
        WHERE b.question_id=?
        GROUP BY b.id ORDER BY b.batch_no DESC
        """,
        (question_id,),
    ).fetchall()
    conn.close()
    return rows


def recompute_batch_status(batch_id: int) -> str:
    """重算批次状态并落库，返回新状态：
    全部判完且全对 -> all_right（终态，变式循环结束）；
    判完但有错     -> has_wrong；未判完 -> pending（可补答续提交）。"""
    conn = get_db()
    row = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN result='right' THEN 1 ELSE 0 END) AS rc,
               SUM(CASE WHEN result='wrong' THEN 1 ELSE 0 END) AS wc
        FROM variant_items WHERE batch_id=?
        """,
        (batch_id,),
    ).fetchone()
    total, rc, wc = row["total"], row["rc"] or 0, row["wc"] or 0
    if total > 0 and rc + wc == total:
        status = "all_right" if wc == 0 else "has_wrong"
    else:
        status = "pending"
    prev = conn.execute(
        "SELECT status, graded_at FROM variant_batches WHERE id=?", (batch_id,)
    ).fetchone()
    if prev is None:
        conn.close()
        return ""
    if status == "pending":
        conn.execute("UPDATE variant_batches SET status='pending' WHERE id=?", (batch_id,))
    elif prev["status"] == "pending" and not prev["graded_at"]:
        # 首次判分完成，记录判分时间；之后家长改判不覆盖
        conn.execute(
            "UPDATE variant_batches SET status=?, graded_at=? WHERE id=?",
            (status, now_str(), batch_id),
        )
    else:
        conn.execute("UPDATE variant_batches SET status=? WHERE id=?", (status, batch_id))
    conn.commit()
    conn.close()
    return status
