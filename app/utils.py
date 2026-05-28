from __future__ import annotations


def money_vnd(amount: int) -> str:
    return f"{amount:,}".replace(",", ".") + "đ"


def html_escape(text: str | None) -> str:
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
