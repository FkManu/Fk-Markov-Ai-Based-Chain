from __future__ import annotations

_SAFE_CHUNK = 4000  # sotto il limite Telegram di 4096


def split_message(text: str) -> list[str]:
    """Divide testo lungo in chunk <= _SAFE_CHUNK, spezzando su newline o spazio."""
    if len(text) <= _SAFE_CHUNK:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= _SAFE_CHUNK:
            chunks.append(text)
            break
        cut = text[:_SAFE_CHUNK].rfind("\n")
        if cut < _SAFE_CHUNK // 2:
            cut = text[:_SAFE_CHUNK].rfind(" ")
        if cut <= 0:
            cut = _SAFE_CHUNK
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()

    return chunks
