"""AI 识别模块：调用智谱 GLM-4V 从照片提取题目（文字 + LaTeX 公式）。"""
import base64
import json
import os
import re
from typing import TypedDict, cast

import httpx

from .db import get_setting

API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
DEFAULT_MODEL = "glm-4v-flash"
VARIANT_MODEL = "glm-4-flash"   # 变式题生成的默认文本模型（免费）

PROMPT = """你是小学题目录入助手。请从图片中完整提取一道题目，并按以下 JSON 格式输出（不要输出任何其他文字、不要用 markdown 代码块包裹）：
{
  "content": "题干文字。数学式子用 LaTeX，行内公式用 $...$ 包裹，独立公式用 $$...$$ 包裹。如果题干含有几何图形、线段图、表格等无法用文字表达的部分，在对应位置插入占位符 [图]，稍后由用户手动裁剪图片补充。",
  "answer": "参考答案与解题过程（用 LaTeX 表示式子）",
  "knowledge": "涉及的知识点，如：分数加法、长方形周长",
  "has_figure": true 或 false（题干是否含几何图形/线段图等需要截图的部分）
}

注意：只提取图片中最主要的一道题目；数字和运算符号要准确；选择题要保留所有选项。"""


def get_api_key() -> str:
    return get_setting("api_key") or os.environ.get("GLM_API_KEY", "")


def _parse_json(text: str) -> dict[str, object]:
    """解析 AI 返回的 JSON（容忍 markdown 代码块包裹），非对象结构抛 ValueError。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    data = cast(object, json.loads(text))   # json.loads 返回 Any，先收窄再校验
    if not isinstance(data, dict):
        raise ValueError("AI 返回格式异常")
    return cast(dict[str, object], data)


def _extract_content(resp: httpx.Response) -> str:
    """从 GLM ChatCompletions 响应 JSON 中提取首个 choice 的 message.content。"""
    data = cast(dict[str, object], resp.json())   # resp.json() 返回 Any，集中收窄
    choices = cast(list[object], data["choices"])
    choice = cast(dict[str, object], choices[0])
    message = cast(dict[str, object], choice["message"])
    return cast(str, message["content"])


class Recognition(TypedDict):
    """recognize_question 的返回结构：字段类型精确，调用方取值无需再收窄。"""

    content: str      # 题干文字（含 LaTeX，可能含 [图] 占位符）
    answer: str       # 参考答案与解题过程
    knowledge: str    # 知识点标签
    has_figure: bool  # 题干是否含几何图形/线段图等需截图部分


def recognize_question(photo_bytes: bytes) -> Recognition:
    """返回 {"content","answer","knowledge","has_figure"}；失败抛异常，无 Key 抛 ValueError。"""
    api_key = get_api_key()
    if not api_key:
        raise ValueError("未配置 API Key")
    model = get_setting("model", DEFAULT_MODEL)
    b64 = base64.b64encode(photo_bytes).decode()
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
        "temperature": 0.1,
    }
    resp = httpx.post(
        API_URL,
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=90,
    )
    _ = resp.raise_for_status()
    content = _extract_content(resp)
    data = _parse_json(content)
    return {
        "content": str(data.get("content", "")).strip(),
        "answer": str(data.get("answer", "")).strip(),
        "knowledge": str(data.get("knowledge", "")).strip(),
        "has_figure": bool(data.get("has_figure", False)),
    }


def generate_variants(content: str, answer: str, knowledge: str, count: int) -> list[dict[str, str]]:
    """根据原题生成 count 道同类型变式题，返回 [{"content","answer","knowledge"}]。
    失败抛异常（无 Key 抛 ValueError；网络/解析异常原样上抛）。"""
    api_key = get_api_key()
    if not api_key:
        raise ValueError("未配置 API Key")
    model = get_setting("variant_model", VARIANT_MODEL)
    prompt = (
        "你是小学数学出题助手。请根据给定的原题，出一批考查相同知识点、解法相同的变式练习题。\n"
        "要求：\n"
        "1. 每道题与原题题型相同、解题方法一致，但改变数字、情境或叙述方式，不能与原题重复；\n"
        "2. 难度与原题相当，符合小学水平，不超纲；\n"
        "3. 答案必须是简短明确的最终结果（一个数、分数或式子），能通过文字自动判分；"
        "不要出需要画图、量角、动手操作的题；\n"
        "4. 题干中的数学式用 LaTeX，行内公式用 $...$ 包裹。\n\n"
        f"【原题】\n{content}\n\n"
        f"【原题参考答案与解析】\n{answer or '（原题未录入答案）'}\n\n"
        f"【知识点】{knowledge or '（未标注）'}\n\n"
        f"请严格按以下 JSON 格式输出 {count} 道题，不要输出任何其他文字，不要用 markdown 代码块包裹：\n"
        '{"questions": [{"content": "题干", "answer": "最终答案", "knowledge": "知识点"}]}'
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.8,
    }
    resp = httpx.post(
        API_URL,
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=90,
    )
    _ = resp.raise_for_status()
    text = _extract_content(resp)
    data = _parse_json(text)
    questions = data.get("questions")
    if not isinstance(questions, list):
        raise ValueError("AI 返回格式异常")
    items: list[dict[str, str]] = []
    for it in cast(list[object], questions):
        if not isinstance(it, dict):
            continue
        d = cast(dict[str, object], it)
        c = str(d.get("content", "")).strip()
        a = str(d.get("answer", "")).strip()
        if not c or not a:
            continue
        items.append({
            "content": c,
            "answer": a,
            "knowledge": str(d.get("knowledge", "")).strip(),
        })
    if not items:
        raise ValueError("AI 未返回有效题目")
    return items[:count]
