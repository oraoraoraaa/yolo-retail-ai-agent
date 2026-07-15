"""Retail agent reasoning.

Wraps an OpenAI-compatible chat endpoint for the conversational agent and the
audit narrative. When no API key is configured every method degrades to a
deterministic, offline-friendly response so the frontend always gets useful
content.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.schemas.chat import ChatMessage
from app.services.detector import GapDetectionResult

SYSTEM_PROMPT = (
    "You are a smart retail inventory agent. You reason about shelf audits, "
    "phantom inventory, misplaced products, and restocking. Answer concisely "
    "and suggest concrete next steps for store staff."
)


class RetailAgent:
    """Conversational + audit reasoning backed by an optional LLM."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # -- Chat ---------------------------------------------------------------

    def chat(
        self,
        message: str,
        history: list[ChatMessage],
        attachment_names: list[str] | None = None,
    ) -> str:
        """Produce a reply to the user's message."""
        attachment_names = attachment_names or []
        if not self._settings.llm_enabled:
            return self._mock_chat_reply(message, attachment_names)

        try:
            return self._llm_chat(message, history, attachment_names)
        except Exception as exc:  # pragma: no cover - network dependent
            return (
                "The agent could not reach the language model "
                f"({exc}). Showing an offline summary instead.\n\n"
                + self._mock_chat_reply(message, attachment_names)
            )

    def _mock_chat_reply(self, message: str, attachment_names: list[str]) -> str:
        parts: list[str] = []
        if message:
            parts.append(f'You asked: "{message}".')
        if attachment_names:
            joined = ", ".join(attachment_names)
            parts.append(f"I received {len(attachment_names)} attachment(s): {joined}.")
        parts.append(
            "LLM access is not configured (set OPENAI_API_KEY to enable real "
            "reasoning). Meanwhile: run a shelf audit to detect gaps, then I can "
            "cross-reference the planogram to flag out-of-stock SKUs."
        )
        return " ".join(parts)

    def _llm_chat(
        self,
        message: str,
        history: list[ChatMessage],
        attachment_names: list[str],
    ) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in history:
            if item.role in ("user", "assistant", "system"):
                messages.append({"role": item.role, "content": item.content})

        user_content = message
        if attachment_names:
            user_content += "\n\n[Attached images: " + ", ".join(attachment_names) + "]"
        # The latest user message is already the tail of `history` from the
        # frontend; only append when it is missing to avoid duplication.
        if not history or history[-1].role != "user" or history[-1].content != message:
            messages.append({"role": "user", "content": user_content})
        elif attachment_names:
            messages[-1]["content"] = user_content

        return self._call_completion(messages)

    # -- Audit narrative ----------------------------------------------------

    def summarize_audit(self, result: GapDetectionResult) -> tuple[str, str]:
        """Return ``(suggested_action, explanation)`` for an audit result."""
        if not result.available:
            reason = result.unavailable_reason or "Detector is unavailable."
            return (
                "Enable the detector",
                "Shelf-gap detection is not running yet. "
                f"{reason} Once weights are available, this panel will report "
                "detected gaps and the recommended restocking action.",
            )

        gaps = result.gap_count
        products = result.product_count
        facts = (
            f"Detected {gaps} gap(s) and {products} product facing(s) "
            f"across {result.total} region(s)."
        )

        if not self._settings.llm_enabled:
            if gaps == 0:
                return (
                    "No action needed",
                    f"{facts} The shelf appears fully stocked; no empty slots were found.",
                )
            return (
                f"Restock {gaps} gap(s)",
                f"{facts} Cross-reference each gap coordinate with the planogram to "
                "identify the missing SKU, then dispatch staff to replenish from the "
                "backroom or trigger a reorder.",
            )

        try:
            prompt = (
                f"A shelf audit produced these detections: {facts} "
                "Give a short suggested action (max 6 words) on the first line, "
                "then a blank line, then a 2-3 sentence explanation for store staff."
            )
            reply = self._call_completion(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
            )
            action, _, explanation = reply.partition("\n")
            action = action.strip() or (f"Restock {gaps} gap(s)" if gaps else "No action needed")
            explanation = explanation.strip() or facts
            return action, explanation
        except Exception:  # pragma: no cover - network dependent
            fallback_action = f"Restock {gaps} gap(s)" if gaps else "No action needed"
            return fallback_action, facts

    # -- OpenAI-compatible transport ---------------------------------------

    def _call_completion(self, messages: list[dict[str, str]]) -> str:
        import httpx

        url = f"{self._settings.openai_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._settings.openai_model,
            "messages": messages,
            "temperature": 0.3,
        }
        with httpx.Client(timeout=60) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"].strip()


_agent: RetailAgent | None = None


def get_agent() -> RetailAgent:
    """Return the process-wide agent singleton."""
    global _agent
    if _agent is None:
        _agent = RetailAgent(get_settings())
    return _agent
