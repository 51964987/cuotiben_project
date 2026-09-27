"""错题本 - FastAPI 主应用。"""
import base64
import json
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .ai import DEFAULT_MODEL, generate_variants, get_api_key, recognize_question
from .db import (
    FIGURE_DIR,
    UPLOAD_DIR,
    _i,
    _s,
    answers_equal,
    create_paper,
    create_question,
    create_variant_batch,
    delete_paper_cascade,
    delete_question_cascade,
    eligible_questions,
    get_paper,
    get_paper_items,
    get_paper_question_ids,
    get_pending_batch,
    get_question,
    get_questions_by_ids,
    get_setting,
    get_stats,
    get_variant_batch,
    get_variant_batches,
    get_variant_items,
    has_pending_batch,
    init_db,
    list_papers_summary,
    list_questions,
    override_variant_item,
    recompute_batch_status,
    record_variant_answer,
    save_paper_grades,
    set_setting,
    update_question_fields,
    update_recognition,
)

@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用生命周期：服务启动时确保建表（init_db 幂等，可重复执行）。"""
    init_db()
    yield


app = FastAPI(title="错题本", lifespan=lifespan)
init_db()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.mount("/photos", StaticFiles(directory=str(UPLOAD_DIR)), name="photos")
app.mount("/figures", StaticFiles(directory=str(FIGURE_DIR)), name="figures")


# ---------- 首页 ----------

@app.get("/")
def index(request: Request):
    stats = get_stats()
    days = int(get_setting("default_days", "7") or 7)
    due = len(eligible_questions(days))
    return templates.TemplateResponse(request, "index.html", {
        "active": stats["active"], "mastered": stats["mastered"], "papers": stats["papers"],
        "due": due, "days": days,
    })


# ---------- 拍照录入 ----------

@app.get("/upload")
def upload_page(request: Request):
    has_key = bool(get_api_key())
    return templates.TemplateResponse(request, "upload.html", {"has_key": has_key})


@app.post("/upload")
async def upload_photo(photo: UploadFile = File(...)):
    data = await photo.read()
    if not data:
        return RedirectResponse("/upload", status_code=303)
    fname = f"{datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:6]}.jpg"
    _ = (UPLOAD_DIR / fname).write_bytes(data)

    qid = create_question(fname)

    # AI 识别（失败不阻塞，可在编辑页手动录入）
    try:
        result = recognize_question(data)
        update_recognition(qid, result["content"], result["answer"], result["knowledge"])
    except Exception:
        pass
    return RedirectResponse(f"/questions/{qid}/edit?from_photo=1", status_code=303)


# ---------- 题库 ----------

@app.get("/questions")
def questions_page(request: Request, status: str = "active", q: str = ""):
    rows = list_questions(status, q)
    return templates.TemplateResponse(request, "questions.html", {
        "rows": rows, "status": status, "q": q,
    })


@app.get("/questions/{qid}/edit")
def edit_page(request: Request, qid: int, from_photo: int = 0):
    row = get_question(qid)
    if not row:
        return RedirectResponse("/questions", status_code=303)
    return templates.TemplateResponse(request, "edit.html", {
        "q": row, "from_photo": from_photo,
    })


@app.post("/questions/{qid}/edit")
async def edit_save(
    qid: int,
    content: str = Form(""),
    answer: str = Form(""),
    knowledge: str = Form(""),
    source: str = Form(""),
    status: str = Form("active"),
    figure_data: str = Form(""),
):
    figure = ""
    if figure_data.startswith("data:image/"):
        b64 = figure_data.split(",", 1)[1]
        figure = f"fig_{qid}_{datetime.now():%Y%m%d%H%M%S}.png"
        _ = (FIGURE_DIR / figure).write_bytes(base64.b64decode(b64))
    update_question_fields(qid, content, answer, knowledge, source, status, figure)
    return RedirectResponse("/questions", status_code=303)


@app.post("/questions/{qid}/delete")
def delete_question(qid: int):
    delete_question_cascade(qid)
    return RedirectResponse("/questions", status_code=303)


# ---------- 组卷 ----------

@app.get("/paper/new")
def paper_new_page(request: Request):
    # 间隔天数只认设置页的 default_days，不接收查询参数（原 days/max_count 形参从未被使用，已删）
    days = int(get_setting("default_days", "7") or 7)
    eligible = eligible_questions(days)
    return templates.TemplateResponse(request, "paper_new.html", {
        "days": days, "eligible_count": len(eligible),
        "total_active": len(eligible_questions(0)),
    })


@app.post("/paper/create")
async def paper_create(request: Request):
    form = await request.form()
    mode = str(form.get("mode") or "smart")
    days_raw = str(form.get("days") or "")
    # 空值用默认间隔，显式 0 表示不限（form.get 返回 UploadFile | str，先收窄为 str 再转 int）
    days = int(days_raw) if days_raw else int(get_setting("default_days", "7") or 7)
    max_count = int(str(form.get("max_count") or "0"))

    if mode == "manual":
        ids = [int(str(x)) for x in form.getlist("question_ids")]
        rows = get_questions_by_ids(ids)
    elif mode == "all":
        rows = eligible_questions(0, max_count)
    else:  # smart: 间隔到期 + 重复出错优先
        rows = eligible_questions(days, max_count)

    if not rows:
        return RedirectResponse("/paper/new", status_code=303)

    question_ids = [_i(r, "id") for r in rows]
    title = f"错题重做卷 {datetime.now():%Y-%m-%d}"
    pid = create_paper(
        title, json.dumps({"mode": mode, "days": days, "max_count": max_count}), question_ids
    )
    return RedirectResponse(f"/papers/{pid}", status_code=303)


@app.get("/papers")
def papers_page(request: Request):
    return templates.TemplateResponse(request, "papers.html", {"rows": list_papers_summary()})


@app.get("/papers/{pid}")
def paper_view(request: Request, pid: int):
    paper = get_paper(pid)
    if not paper:
        return RedirectResponse("/papers", status_code=303)
    return templates.TemplateResponse(request, "paper_view.html", {
        "paper": paper, "items": get_paper_items(pid),
    })


@app.post("/papers/{pid}/delete")
def paper_delete(pid: int):
    delete_paper_cascade(pid)
    return RedirectResponse("/papers", status_code=303)


# ---------- 批改 ----------

@app.get("/papers/{pid}/grade")
def grade_page(request: Request, pid: int):
    paper = get_paper(pid)
    if not paper:
        return RedirectResponse("/papers", status_code=303)
    threshold = int(get_setting("master_threshold", "2") or 2)
    return templates.TemplateResponse(request, "grade.html", {
        "paper": paper, "items": get_paper_items(pid), "threshold": threshold,
    })


@app.post("/papers/{pid}/grade")
async def grade_save(request: Request, pid: int):
    """收集表单中的有效判分（right/wrong），整体落库交给 db 层。"""
    form = await request.form()
    threshold = int(get_setting("master_threshold", "2") or 2)
    results: dict[int, str] = {}
    for qid in get_paper_question_ids(pid):
        r = str(form.get(f"result_{qid}") or "").strip()
        if r in ("right", "wrong"):
            results[qid] = r
    save_paper_grades(pid, results, threshold)
    return RedirectResponse(f"/papers/{pid}/grade", status_code=303)


# ---------- 变式练习 ----------

def _figure_question(q: sqlite3.Row) -> bool:
    """图形题（有附图或题干含 [图] 占位）暂不支持生成变式。"""
    return bool(_s(q, "figure")) or "[图]" in _s(q, "content")


def _variant_count() -> int:
    """每批变式题数（设置页可配，1-10，默认 5）。"""
    try:
        n = int(get_setting("variant_count", "5"))
    except (TypeError, ValueError):
        n = 5
    return min(10, max(1, n))


def _generate_variant_batch(question_id: int, count: int) -> int:
    """为题目生成一批变式题，返回批次 id。校验失败 / AI 失败抛 ValueError。"""
    q = get_question(question_id)
    if not q:
        raise ValueError("题目不存在")
    if _figure_question(q):
        raise ValueError("图形题暂不支持生成变式")
    if has_pending_batch(question_id):
        raise ValueError("该题已有待作答的变式批次，请先完成作答")
    items = generate_variants(_s(q, "content"), _s(q, "answer"), _s(q, "knowledge"), count)
    return create_variant_batch(question_id, items)


@app.get("/questions/{qid}/variants")
def variants_page(request: Request, qid: int, err: str = ""):
    q = get_question(qid)
    if not q:
        return RedirectResponse("/questions", status_code=303)
    return templates.TemplateResponse(request, "variants.html", {
        "q": q,
        "batches": get_variant_batches(qid),
        "pending": get_pending_batch(qid),
        "count": _variant_count(),
        "figure": _figure_question(q),
        "err": err,
    })


@app.post("/questions/{qid}/variants/generate")
def variants_generate(qid: int, count: int = Form(0)):
    """生成一批变式题；成功跳转作答页，失败带 err 回列表页。"""
    n = count if 1 <= count <= 10 else _variant_count()
    try:
        bid = _generate_variant_batch(qid, n)
    except ValueError as e:
        return RedirectResponse(
            f"/questions/{qid}/variants?err={quote(str(e))}", status_code=303
        )
    except Exception:
        return RedirectResponse(
            f"/questions/{qid}/variants?err={quote('生成失败，请检查网络或 API Key 后重试')}",
            status_code=303,
        )
    return RedirectResponse(f"/batches/{bid}", status_code=303)


@app.get("/batches/{bid}")
def batch_page(request: Request, bid: int, err: str = ""):
    """变式批次页：未判分时作答，判分后看结果与改判。"""
    b = get_variant_batch(bid)
    if not b:
        return RedirectResponse("/questions", status_code=303)
    return templates.TemplateResponse(request, "batch.html", {
        "b": b,
        "items": get_variant_items(bid),
        "graded": _s(b, "status") != "pending",
        "pending": get_pending_batch(_i(b, "question_id")),
        "auto_next": get_setting("variant_auto_next", "manual"),
        "err": err,
    })


@app.post("/batches/{bid}/submit")
async def batch_submit(bid: int, request: Request):
    """提交本批答案：逐题归一化自动判分；未填的题不判分，可稍后补答。
    批改后若模式为 auto 且有错，自动生成下一批。"""
    b = get_variant_batch(bid)
    if not b or _s(b, "status") != "pending":
        return RedirectResponse(f"/batches/{bid}", status_code=303)
    form = await request.form()
    for it in get_variant_items(bid):
        raw = str(form.get(f"answer_{_i(it, 'id')}") or "").strip()
        if not raw:
            continue
        result = "right" if answers_equal(raw, _s(it, "answer")) else "wrong"
        record_variant_answer(_i(it, "id"), result, raw)
    status = recompute_batch_status(bid)
    if status == "has_wrong" and get_setting("variant_auto_next", "manual") == "auto":
        try:
            _ = _generate_variant_batch(_i(b, "question_id"), _variant_count())
        except Exception:
            pass  # 自动续批失败则留在本批结果页，家长可手动点「再来一批」
    return RedirectResponse(f"/batches/{bid}", status_code=303)


@app.post("/batches/{bid}/override/{item_id}")
async def batch_override(bid: int, item_id: int, request: Request):
    """家长人工改判单题（自动判分有误差，这是闭环的安全阀）。
    result 取 right / wrong / 空（撤销判分，恢复待作答）。"""
    form = await request.form()
    result = str(form.get("result") or "").strip()
    if result not in ("right", "wrong"):
        result = ""
    override_variant_item(bid, item_id, result)
    _ = recompute_batch_status(bid)
    return RedirectResponse(f"/batches/{bid}", status_code=303)


# ---------- 设置 ----------

@app.get("/settings")
def settings_page(request: Request):
    return templates.TemplateResponse(request, "settings.html", {
        "api_key": get_setting("api_key"),
        "model": get_setting("model", DEFAULT_MODEL),
        "default_days": get_setting("default_days", "7"),
        "master_threshold": get_setting("master_threshold", "2"),
        "variant_count": get_setting("variant_count", "5"),
        "variant_auto_next": get_setting("variant_auto_next", "manual"),
    })


@app.post("/settings")
async def settings_save(
    api_key: str = Form(""),
    model: str = Form(DEFAULT_MODEL),
    default_days: int = Form(7),
    master_threshold: int = Form(2),
    variant_count: int = Form(5),
    variant_auto_next: str = Form("manual"),
):
    set_setting("api_key", api_key.strip())
    set_setting("model", model.strip() or DEFAULT_MODEL)
    set_setting("default_days", str(max(0, default_days)))
    set_setting("master_threshold", str(max(1, master_threshold)))
    set_setting("variant_count", str(min(10, max(1, variant_count))))
    set_setting("variant_auto_next", "auto" if variant_auto_next == "auto" else "manual")
    return RedirectResponse("/settings", status_code=303)
