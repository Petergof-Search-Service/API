from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI
from .config import settings


def _make_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.RAG_YANDEX_API_KEY,
        base_url="https://rest-assistant.api.cloud.yandex.net/v1",
        project=settings.RAG_YANDEX_FOLDER_ID,
    )


def _iter_valid_turns(
    dialog_history: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    if not dialog_history:
        return []

    valid_turns: list[dict[str, str]] = []

    for item in dialog_history:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = item.get("content")

        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            valid_turns.append(
                {
                    "role": role,
                    "content": content.strip(),
                }
            )

    return valid_turns


def _history_to_text(dialog_history: list[dict[str, Any]] | None) -> str:
    turns = _iter_valid_turns(dialog_history)
    if not turns:
        return ""

    lines: list[str] = []
    for t in turns:
        speaker = "Пользователь" if t["role"] == "user" else "Ассистент"
        lines.append(f"{speaker}: {t['content']}")

    return "\n".join(lines).strip()


def _has_meaningful_history(dialog_history: list[dict[str, Any]] | None) -> bool:
    return bool(_iter_valid_turns(dialog_history))


async def _model_text(
    client: AsyncOpenAI,
    instructions: str,
    input_text: str,
    temperature: float = 0.0,
) -> str:
    resp = await client.responses.create(
        model=f"gpt://{settings.RAG_YANDEX_FOLDER_ID}/{settings.RAG_YANDEX_CLOUD_MODEL}",
        instructions=instructions,
        input=input_text,
        temperature=temperature,
        store=False,
    )
    return (resp.output_text or "").strip()


async def _rewrite_query(
    client: AsyncOpenAI,
    question: str,
    dialog_history: list[dict[str, Any]] | None,
) -> str:
    if not _has_meaningful_history(dialog_history):
        return question.strip()

    history_text = _history_to_text(dialog_history)

    instructions = (
        "Твоя задача — переформулировать новый вопрос пользователя в самодостаточный "
        "поисковый запрос для поиска по векторной базе.\n"
        "Используй историю диалога только для разрешения ссылок вроде "
        "'он', 'она', 'оно', 'там', 'позже', 'второй вариант' и т.п.\n"
        "Если вопрос уже самодостаточный — верни его как есть.\n"
        "Не отвечай на вопрос. Не добавляй пояснений.\n"
        "Верни только итоговый поисковый запрос."
    )

    input_text = (
        f"ИСТОРИЯ ДИАЛОГА:\n{history_text or '[пусто]'}\n\n"
        f"НОВЫЙ ВОПРОС:\n{question}"
    )

    rewritten = await _model_text(
        client=client,
        instructions=instructions,
        input_text=input_text,
        temperature=0.0,
    )

    return rewritten or question.strip()


def _build_context_from_hits(hits: list[Any]) -> str:
    context_parts: list[str] = []

    for i, h in enumerate(hits, 1):
        txt = h.content[0].text if getattr(h, "content", None) else ""
        filename = getattr(h, "filename", "unknown")
        score = getattr(h, "score", 0.0)
        context_parts.append(
            f"Источник {i} (score={score:.4f}, файл={filename}):\n{txt}"
        )

    return "\n\n".join(context_parts)


async def get_answer(
    question: str,
    vector_store_id: str,
    dialog_history: list[dict[str, Any]] | None = None,
    temp: float = 0.2,
    k: int = 30,
    score_threshold: float = 0.0,
    prompt: str | None = None,
) -> tuple[str, str]:
    if prompt is None:
        prompt = (
            "Ты ассистируешь научного сотрудника музейного комплекса Петергоф.\n"
            "Отвечай строго ТОЛЬКО на основе текста в блоке КОНТЕКСТ.\n"
            "Блок ИСТОРИЯ ДИАЛОГА используй только для понимания того, к чему относятся "
            "местоимения, сокращённые ссылки и уточняющие вопросы.\n"
            "Ничего не выдумывай. Если ответа нет в контексте — так и скажи.\n"
            "В конце ответа обязательно укажи названия файлов и страницы, "
            "на которые опирается твой ответ."
        )

    client = _make_client()

    standalone_question = await _rewrite_query(
        client=client,
        question=question,
        dialog_history=dialog_history,
    )

    s = await client.vector_stores.search(
        vector_store_id=vector_store_id,
        query=standalone_question,
    )

    hits = list(s.data or [])
    hits = [
        h
        for h in hits
        if getattr(h, "score", None) is not None and h.score >= score_threshold
    ]
    hits.sort(key=lambda h: h.score, reverse=True)
    hits = hits[:k]

    history_text = _history_to_text(dialog_history)

    if not hits:
        return "В моей базе данных нет релевантной информации.", ""

    data_for_rag = _build_context_from_hits(hits)

    resp = await client.responses.create(
        model=f"gpt://{settings.RAG_YANDEX_FOLDER_ID}/{settings.RAG_YANDEX_CLOUD_MODEL}",
        instructions=prompt,
        input=(
            f"ИСТОРИЯ ДИАЛОГА:\n{history_text or '[пусто]'}\n\n"
            f"КОНТЕКСТ:\n{data_for_rag}\n\n"
            f"ТЕКУЩИЙ ВОПРОС:\n{question}"
        ),
        temperature=temp,
        store=False,
    )

    answer = (resp.output_text or "").strip()

    return answer, data_for_rag