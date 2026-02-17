from openai import AsyncOpenAI
from .config import settings


async def get_answer(
    question: str,
    vector_store_id: str,
    temp: float = 0.2,
    k: int = 5,
    score_threshold: float = 0.8,
    prompt: str | None = None,
) -> tuple[str, str] | str:
    if prompt is None:
        prompt = (
            "Ты ассистируешь научного сотрудника музейного комплекса Петергоф.\n"
            "Отвечай строго ТОЛЬКО на основе текста в блоке КОНТЕКСТ.\n"
            "Ничего не выдумывай. Если ответа нет в контексте — так и скажи."
            "В конце ответа обязательно указывай название файлов и их страницы, на которые опирается твой ответ."
        )

    client = AsyncOpenAI(
        api_key=settings.RAG_YANDEX_API_KEY,
        base_url="https://rest-assistant.api.cloud.yandex.net/v1",
        project=settings.RAG_YANDEX_FOLDER_ID,
    )

    s = await client.vector_stores.search(
        vector_store_id=vector_store_id, query=question
    )

    hits = list(s.data or [])

    hits = [
        h
        for h in hits
        if getattr(h, "score", None) is not None and h.score >= score_threshold
    ]

    hits.sort(key=lambda h: h.score, reverse=True)

    hits = hits[:k]

    print("Filtered hits:", [(h.filename, h.score) for h in hits])

    if not hits:
        return (
            "В моей базе данных нет релевантной информации (после фильтрации по score)."
        )

    context_parts = []
    for i, h in enumerate(hits, 1):
        txt = h.content[0].text if getattr(h, "content", None) else ""
        context_parts.append(
            f"Источник {i} (score={h.score:.4f}, файл={h.filename}):\n{txt}"
        )

    context = "\n\n".join(context_parts)

    resp = await client.responses.create(
        model=f"gpt://{settings.RAG_YANDEX_FOLDER_ID}/{settings.RAG_YANDEX_CLOUD_MODEL}",
        instructions=(prompt),
        input=(f"КОНТЕКСТ:\n{context}\n\nВОПРОС:\n{question}"),
        temperature=temp,
        store=False,
    )

    return resp.output_text, context
