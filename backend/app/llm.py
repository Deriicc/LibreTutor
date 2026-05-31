from collections.abc import AsyncIterator

from app.user_llm import resolve_chat

ChatMessage = dict[str, str]


async def stream_chat(
    api_settings: dict | None,
    messages: list[ChatMessage],
    *,
    temperature: float | None = None,
) -> AsyncIterator[str]:
    """Stream chat completion text deltas using the user's configured LLM.
    Raises LLMNotConfigured if the user hasn't set chat key/model."""
    client, model = resolve_chat(api_settings)
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    response = await client.chat.completions.create(**kwargs)
    async for chunk in response:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        text = getattr(delta, "content", None)
        if text:
            yield text


async def complete_json(
    api_settings: dict | None, messages: list[ChatMessage]
) -> str:
    """Non-streamed JSON-mode completion using the user's configured LLM.
    Returns raw JSON string. Raises LLMNotConfigured if unset."""
    client, model = resolve_chat(api_settings)
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=False,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or ""
