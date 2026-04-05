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


def _ensure_dialog_context(dialog_context: dict[str, Any] | None) -> dict[str, Any]:
    if not dialog_context:
        return {"summary": "", "recent_turns": []}

    summary = dialog_context.get("summary", "")
    recent_turns = dialog_context.get("recent_turns", [])

    if not isinstance(summary, str):
        summary = str(summary)

    if not isinstance(recent_turns, list):
        recent_turns = []

    normalized_turns: list[dict[str, str]] = []
    for item in recent_turns:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            normalized_turns.append({"role": role, "content": content.strip()})

    return {
        "summary": summary.strip(),
        "recent_turns": normalized_turns,
    }


def _history_to_text(dialog_context: dict[str, Any]) -> str:
    parts: list[str] = []

    summary = dialog_context.get("summary", "").strip()
    if summary:
        parts.append(f"СВОДКА ДИАЛОГА:\n{summary}")

    recent_turns = dialog_context.get("recent_turns", [])
    if recent_turns:
        turns_text: list[str] = []
        for t in recent_turns:
            speaker = "Пользователь" if t["role"] == "user" else "Ассистент"
            turns_text.append(f"{speaker}: {t['content']}")
        parts.append("ПОСЛЕДНИЕ РЕПЛИКИ:\n" + "\n".join(turns_text))

    return "\n\n".join(parts).strip()


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


def _has_meaningful_history(dialog_context: dict[str, Any]) -> bool:
    summary = dialog_context.get("summary", "").strip()
    recent_turns = dialog_context.get("recent_turns", [])
    return bool(summary or recent_turns)

async def _rewrite_query(
    client: AsyncOpenAI,
    question: str,
    dialog_context: dict[str, Any],
) -> str:
    if not _has_meaningful_history(dialog_context):
        return question.strip()
    
    history_text = _history_to_text(dialog_context)

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

    return rewritten or question


async def _summarize_old_history(
    client: AsyncOpenAI,
    current_summary: str,
    old_turns: list[dict[str, str]],
) -> str:
    if not old_turns:
        return current_summary

    old_history_text: list[str] = []
    for t in old_turns:
        speaker = "Пользователь" if t["role"] == "user" else "Ассистент"
        old_history_text.append(f"{speaker}: {t['content']}")

    instructions = (
        "Сожми историю диалога в короткую, плотную, полезную для дальнейших вопросов сводку.\n"
        "Сохраняй только факты, сущности, уже обсуждённые объекты, принятые допущения, "
        "неразрешённые ссылки и важные предпочтения пользователя.\n"
        "Не добавляй ничего от себя.\n"
        "Пиши кратко."
    )

    input_text = (
        f"ТЕКУЩАЯ СВОДКА:\n{current_summary or '[пусто]'}\n\n"
        f"СТАРАЯ ЧАСТЬ ДИАЛОГА:\n" + "\n".join(old_history_text)
    )

    return await _model_text(
        client=client,
        instructions=instructions,
        input_text=input_text,
        temperature=0.0,
    )


async def _compact_dialog_context(
    client: AsyncOpenAI,
    dialog_context: dict[str, Any],
) -> dict[str, Any]:
    summary = dialog_context["summary"]
    recent_turns = dialog_context["recent_turns"]

    if len(recent_turns) <= settings.MAX_RECENT_TURNS:
        return dialog_context

    kept_turns = recent_turns[-settings.KEPT_RECENT_TURNS:]
    old_turns = recent_turns[:-settings.KEPT_RECENT_TURNS]

    new_summary = await _summarize_old_history(
        client=client,
        current_summary=summary,
        old_turns=old_turns,
    )

    return {
        "summary": new_summary,
        "recent_turns": kept_turns,
    }

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


def _append_turns(
    dialog_context: dict[str, Any],
    question: str,
    answer: str,
) -> dict[str, Any]:
    updated = {
        "summary": dialog_context["summary"],
        "recent_turns": list(dialog_context["recent_turns"]),
    }

    updated["recent_turns"].append({"role": "user", "content": question.strip()})
    updated["recent_turns"].append({"role": "assistant", "content": answer.strip()})

    return updated


async def get_answer(
    question: str,
    vector_store_id: str,
    dialog_context: dict[str, Any] | None = None,
    temp: float = 0.2,
    k: int = 30,
    score_threshold: float = 0.0,
    prompt: str | None = None,
) -> tuple[str, str, dict[str, Any]]:
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

    dialog_context = _ensure_dialog_context(dialog_context)
    dialog_context = await _compact_dialog_context(client, dialog_context)

    standalone_question = await _rewrite_query(
        client=client,
        question=question,
        dialog_context=dialog_context,
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

    history_text = _history_to_text(dialog_context)

    if not hits:
        answer = "В моей базе данных нет релевантной информации."
        updated_context = _append_turns(dialog_context, question, answer)
        updated_context = await _compact_dialog_context(client, updated_context)
        return answer, "", updated_context

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

    updated_context = _append_turns(dialog_context, question, answer)
    updated_context = await _compact_dialog_context(client, updated_context)

    return answer, data_for_rag, updated_context