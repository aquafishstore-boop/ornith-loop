"""Minimal Ollama HTTP client with tools / chat support."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self, host: str, model: str, keep_alive: str = "5m", timeout: float = 300.0):
        self.host = host.rstrip("/")
        self.model = model
        self.keep_alive = keep_alive
        self.timeout = timeout
        self._client = httpx.Client(base_url=self.host, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OllamaClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        format: dict[str, Any] | str | None = None,
        think: bool | None = None,
        temperature: float = 0.4,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": temperature},
        }
        if tools is not None:
            payload["tools"] = tools
        if format is not None:
            payload["format"] = format
        if think is not None:
            payload["think"] = think

        log.debug("ollama chat model=%s msgs=%d tools=%s", self.model, len(messages), bool(tools))
        r = self._client.post("/api/chat", json=payload)
        r.raise_for_status()
        return r.json()

    def unload(self) -> None:
        """Free VRAM so other Ollama clients are not starved."""
        try:
            self._client.post(
                "/api/generate",
                json={"model": self.model, "prompt": "", "keep_alive": 0},
            )
            log.info("unloaded model %s", self.model)
        except Exception as e:  # noqa: BLE001
            log.warning("unload failed: %s", e)

    def message_content(self, response: dict[str, Any]) -> str:
        msg = response.get("message") or {}
        content = msg.get("content") or ""
        return content.strip()

    def message_tool_calls(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        msg = response.get("message") or {}
        return list(msg.get("tool_calls") or [])

    def extract_json(self, text: str) -> Any:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            # drop fence lines
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
            raise
