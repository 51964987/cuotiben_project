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
        -- 错题主表：题库核心，一条记录一道错题；掌握后 status 置 mastered 但记录保留
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,      -- 题目 id，自增主键
            content TEXT NOT NULL DEFAULT '',          -- 题干（含 LaTeX 公式，KaTeX 渲染）
            answer TEXT NOT NULL DEFAULT '',           -- 标准答案与解析
            knowledge TEXT NOT NULL DEFAULT '',        -- 知识点标签（多个用顿号/逗号分隔）
            figure TEXT NOT NULL DEFAULT '',           -- 裁剪出的题目图形文件名（figures\ 下），空 = 无图
            photo TEXT NOT NULL DEFAULT '',            -- 原始拍照文件名（photos\ 下），空 = 手动录入
            wrong_count INTEGER NOT NULL DEFAULT 1,    -- 累计做错次数（组卷时错误多者优先）
            consecutive_correct INTEGER NOT NULL DEFAULT 0,  -- 连续做对次数（达到设置阈值自动置 mastered）
            status TEXT NOT NULL DEFAULT 'active',     -- 状态：active=在题库可出卷 / mastered=已掌握移出
            source TEXT NOT NULL DEFAULT '',           -- 录入来源备注（拍照识别 / 手动录入等）
            created_at TEXT NOT NULL,                  -- 录入时间（YYYY-MM-DD HH:MM:SS）
            last_wrong_at TEXT NOT NULL                -- 最近一次做错时间（间隔选题的时间基准）
        );

        -- 重做卷主表：一次组卷一条记录
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,      -- 试卷 id，自增主键
            title TEXT NOT NULL DEFAULT '',            -- 试卷标题（含日期，打印页眉用）
            strategy TEXT NOT NULL DEFAULT '{}',       -- 组卷参数 JSON（策略类型、间隔天数、勾选题 id 等）
            created_at TEXT NOT NULL,                  -- 组卷时间（YYYY-MM-DD HH:MM:SS）
            graded INTEGER NOT NULL DEFAULT 0          -- 批改状态：0=未批改 / 1=已全部批改
        );

        -- 重做卷-题目关联表：每卷每题一行，记录该题在本卷的批改结果
        CREATE TABLE IF NOT EXISTS paper_items (
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,     -- 所属试卷 id
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,  -- 题目 id
            result TEXT NOT NULL DEFAULT '',           -- 批改结果：''=未批 / right=对 / wrong=错
            PRIMARY KEY (paper_id, question_id)
        );

        -- 作答流水表：每次批改追加一条（含卷外单独批改），questions.wrong_count 等据此累计
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,      -- 记录 id，自增主键
            question_id INTEGER NOT NULL,              -- 题目 id（不设外键，删题后流水仍保留）
            paper_id INTEGER,                          -- 关联试卷 id，NULL = 不属于任何卷的批改
            result TEXT NOT NULL,                      -- 作答结果：right=对 / wrong=错
            attempted_at TEXT NOT NULL                 -- 作答时间（YYYY-MM-DD HH:MM:SS）
        );

        -- 系统配置表：键值对存储（GLM API Key、识别模型、间隔天数、连续做对阈值等）
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,                      -- 配置键，唯一
            value TEXT NOT NULL                        -- 配置值（统一存字符串）
        );

        -- 变式练习批次：挂在原错题名下，独立于重做卷体系，不入题库
        CREATE TABLE IF NOT EXISTS variant_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,      -- 批次 id，自增主键
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,  -- 原错题 id
            batch_no INTEGER NOT NULL,                 -- 第几批，从 1 递增（同一题内递增）
            status TEXT NOT NULL DEFAULT 'pending',    -- 状态：pending=待作答 / all_right=全对(终态) / has_wrong=有错(终态)
            created_at TEXT NOT NULL,                  -- 批次生成时间（YYYY-MM-DD HH:MM:SS）
            graded_at TEXT NOT NULL DEFAULT ''         -- 首次判分完成时间，空 = 未判完；家长改判不覆盖
        );

        -- 变式批次内的题目（AI 生成的同类变式题）
        CREATE TABLE IF NOT EXISTS variant_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,      -- 变式题 id，自增主键
            batch_id INTEGER NOT NULL REFERENCES variant_batches(id) ON DELETE CASCADE,  -- 所属批次 id
            seq INTEGER NOT NULL,                      -- 批内序号，从 1 开始（展示顺序）
            content TEXT NOT NULL,                     -- 变式题题干（含 LaTeX 公式）
            answer TEXT NOT NULL,                      -- 变式题标准答案（自动判分基准）
            knowledge TEXT NOT NULL DEFAULT '',        -- 知识点标签（继承原题或 AI 标注）
            result TEXT NOT NULL DEFAULT '',           -- 作答结果：''=未答 / right=对 / wrong=错
            user_answer TEXT NOT NULL DEFAULT '',      -- 用户提交的答案原文（判分展示用）
            answered_at TEXT NOT NULL DEFAULT ''       -- 提交时间，空 = 未作答（YYYY-MM-DD HH:MM:SS）
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
    "0123456789()[]{},:;.?!%+-=/*",   # 与上一串逐字符等长对位：，->, ：->: ；->; ．->. ？->? ！->! ％->% ＋->+ －->- ＝->= ／->/ ＊->*
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
