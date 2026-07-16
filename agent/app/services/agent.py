"""Retail agent reasoning.

Wraps an OpenAI-compatible chat endpoint for the conversational agent and the
audit narrative. When no API key is configured every method degrades to a
deterministic, offline-friendly response so the frontend always gets useful
content.
"""

from __future__ import annotations

import json
import os
from typing import Any

from app.config import Settings, get_settings
from app.schemas.chat import ChatMessage
from app.services.detector import GapDetectionResult

SYSTEM_PROMPT = (
    "You are a smart retail inventory agent. You reason about shelf audits, "
    "phantom inventory, misplaced products, and restocking. Answer concisely "
    "and suggest concrete next steps for store staff."
)

PROXY_ENV_NAMES = (
    "HTTPS_PROXY",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
)


def _openai_proxy_url() -> str | None:
    """Return a normalized proxy URL for the OpenAI-compatible client."""
    for name in PROXY_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if not value:
            continue
        if value.lower().startswith("socks://"):
            return "socks5://" + value[len("socks://") :]
        return value
    return None


def _reply_instruction(language: str) -> str:
    if language == "zh":
        return "\n\nReply in Chinese."
    return ""


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
        language: str = "en",
    ) -> str:
        """Produce a reply to the user's message."""
        attachment_names = attachment_names or []
        if not self._settings.llm_enabled:
            return self._mock_chat_reply(message, attachment_names, language)

        try:
            return self._llm_chat(message, history, attachment_names, language)
        except Exception as exc:  # pragma: no cover - network dependent
            return self._offline_chat_fallback(
                message, attachment_names, language, str(exc)
            )

    def _offline_chat_fallback(
        self,
        message: str,
        attachment_names: list[str],
        language: str,
        error: str,
    ) -> str:
        if language == "zh":
            return (
                "智能体无法连接到语言模型 "
                f"({error})。以下是离线摘要。\n\n"
                + self._mock_chat_reply(message, attachment_names, language)
            )

        return (
            "The agent could not reach the language model "
            f"({error}). Showing an offline summary instead.\n\n"
            + self._mock_chat_reply(message, attachment_names, language)
        )

    def _mock_chat_reply(
        self, message: str, attachment_names: list[str], language: str
    ) -> str:
        parts: list[str] = []
        if message:
            if language == "zh":
                parts.append(f'你提问的是："{message}"。')
            else:
                parts.append(f'You asked: "{message}".')
        if attachment_names:
            joined = ", ".join(attachment_names)
            if language == "zh":
                parts.append(f"我收到了 {len(attachment_names)} 个附件：{joined}。")
            else:
                parts.append(
                    f"I received {len(attachment_names)} attachment(s): {joined}."
                )
        if self._settings.llm_enabled:
            if language == "zh":
                parts.append(
                    "已配置 LLM，但当前暂时不可用。与此同时：先运行货架巡检检测空位，"
                    "然后我可以交叉比对计划图来标记缺货 SKU。"
                )
            else:
                parts.append(
                    "LLM access is configured but temporarily unavailable. Meanwhile: "
                    "run a shelf audit to detect gaps, then I can cross-reference the "
                    "planogram to flag out-of-stock SKUs."
                )
        else:
            if language == "zh":
                parts.append(
                    "LLM 访问尚未配置（设置 OPENAI_API_KEY 可启用真实推理）。与此同时："
                    "先运行货架巡检检测空位，然后我可以交叉比对计划图来标记缺货 SKU。"
                )
            else:
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
        language: str,
    ) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in history:
            if item.role in ("user", "assistant", "system"):
                messages.append({"role": item.role, "content": item.content})

        user_content = message
        if attachment_names:
            user_content += "\n\n[Attached images: " + ", ".join(attachment_names) + "]"
        user_content += _reply_instruction(language)
        # The latest user message is already the tail of `history` from the
        # frontend; only append when it is missing to avoid duplication.
        if not history or history[-1].role != "user" or history[-1].content != message:
            messages.append({"role": "user", "content": user_content})
        elif attachment_names:
            messages[-1]["content"] = user_content

        return self._call_completion(messages)

    # -- Audit narrative ----------------------------------------------------

    def summarize_audit(
        self,
        result: GapDetectionResult,
        language: str = "en",
    ) -> tuple[str, str]:
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
            prompt += _reply_instruction(language)

            reply = self._call_completion(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
            )
            action, _, explanation = reply.partition("\n")
            action = action.strip() or (
                f"Restock {gaps} gap(s)" if gaps else "No action needed"
            )
            explanation = explanation.strip() or facts
            return action, explanation
        except Exception:  # pragma: no cover - network dependent
            fallback_action = f"Restock {gaps} gap(s)" if gaps else "No action needed"
            return fallback_action, facts

    def summarize_detection_json(
        self,
        vision_model_response: dict[str, Any],
        planogram_response: dict[str, Any] | None,
        language: str = "en",
    ) -> tuple[str, str]:
        """Analyze local detector JSON, optionally enriched by Planogram data."""
        summary = vision_model_response.get("summary", {})
        detections = vision_model_response.get("detections", [])
        total = int(summary.get("total") or len(detections))
        gaps = int(summary.get("gapCount") or 0)
        products = int(summary.get("productCount") or max(0, total - gaps))

        if not self._settings.llm_enabled:
            return self._mock_detection_json_reply(total, gaps, products, language)

        try:
            prompt = (
                "A local shelf vision model produced this JSON response. "
                "Use it to recommend the next store-staff action. "
                "If Planogram data is null or empty, explicitly treat the planogram lookup as unavailable. "
                "Return a short suggested action (max 8 words) on the first line, "
                "then a blank line, then a concise explanation.\n\n"
                "Vision model JSON:\n"
                f"{json.dumps(vision_model_response, ensure_ascii=False)}\n\n"
                "Planogram response:\n"
                f"{json.dumps(planogram_response, ensure_ascii=False)}"
            )
            prompt += _reply_instruction(language)

            reply = self._call_completion(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
            )
            action, _, explanation = reply.partition("\n")
            action = action.strip() or self._offline_detection_action(
                gaps, total, language
            )
            explanation = explanation.strip() or self._offline_detection_explanation(
                total, gaps, products, language
            )
            return action, explanation
        except Exception:  # pragma: no cover - network dependent
            return self._mock_detection_json_reply(total, gaps, products, language)

    def _mock_detection_json_reply(
        self,
        total: int,
        gaps: int,
        products: int,
        language: str,
    ) -> tuple[str, str]:
        return (
            self._offline_detection_action(gaps, total, language),
            self._offline_detection_explanation(total, gaps, products, language),
        )

    def _offline_detection_explanation(
        self,
        total: int,
        gaps: int,
        products: int,
        language: str,
    ) -> str:
        if language == "zh":
            if total == 0:
                return (
                    "本地视觉模型没有检测到商品或货架空位。请在继续使用此巡检结果前，"
                    "检查摄像头角度、光照和货架可见性。"
                )
            if gaps == 0:
                return (
                    f"本地视觉模型检测到 {products} 个商品候选，没有发现空位候选。"
                    "计划图查询尚未实现，因此当前离线建议只基于检测器输出。"
                )
            return (
                f"本地视觉模型检测到 {gaps} 个空位候选和 {products} 个商品候选。"
                "计划图查询尚未实现，因此门店人员应在补货前人工核对空位位置。"
            )

        if total == 0:
            return (
                "The local vision model did not detect products or shelf gaps. "
                "Verify the camera angle, lighting, and shelf visibility before relying on this audit."
            )
        if gaps == 0:
            return (
                f"The local vision model detected {products} product candidate(s) and no gap candidates. "
                "Planogram lookup is not implemented yet, so this offline recommendation is based only on detector output."
            )
        return (
            f"The local vision model detected {gaps} gap candidate(s) and {products} product candidate(s). "
            "Planogram lookup is not implemented yet, so staff should verify the gap locations manually before restocking."
        )

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
        proxy_url = _openai_proxy_url()
        client_kwargs = {"timeout": 60, "trust_env": False}
        if proxy_url:
            client_kwargs["proxy"] = proxy_url

        with httpx.Client(**client_kwargs) as client:
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
