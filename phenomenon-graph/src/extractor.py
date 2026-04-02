from __future__ import annotations

import json
import re
import time
from typing import Any, AsyncGenerator, Dict, Optional

from openai import AsyncOpenAI, OpenAI

from .prompt import SYSTEM_PROMPT, build_user_prompt
from .schema import PhenomenonGraph


class LLMConfig:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.extra_headers: Dict[str, str] = extra_headers or {}


class Extractor:
    def __init__(self, config: LLMConfig, max_retries: int = 3) -> None:
        self.config = config
        self.max_retries = max_retries
        self._client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            default_headers=config.extra_headers if config.extra_headers else None,
        )

    def extract(self, text: str, source_file: Optional[str] = None) -> PhenomenonGraph:
        user_prompt = build_user_prompt(text)
        last_error: Exception = RuntimeError("No attempts made")

        for attempt in range(1, self.max_retries + 1):
            try:
                raw = self._call_llm(user_prompt)
                graph = self._parse_response(raw)
                graph.source_file = source_file
                return graph
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    wait = 2 ** (attempt - 1)
                    print(f"[extractor] Attempt {attempt} failed ({exc}); retrying in {wait}s…")
                    time.sleep(wait)

        raise RuntimeError(
            f"Extraction failed after {self.max_retries} attempts. "
            f"Last error: {last_error}"
        ) from last_error

    async def extract_stream(
        self, text: str, source_file: Optional[str] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream extraction: yields thinking chunks, then the final graph or an error."""
        user_prompt = build_user_prompt(text)
        full_content = ""

        async_client = AsyncOpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            default_headers=self.config.extra_headers if self.config.extra_headers else None,
        )

        stream = await async_client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                delta = chunk.choices[0].delta.content
                full_content += delta
                yield {"type": "thinking", "content": delta}

        try:
            graph = self._parse_response(full_content)
            graph.source_file = source_file
            yield {"type": "graph", "data": graph.model_dump(mode="json")}
        except Exception as exc:
            yield {"type": "error", "message": str(exc)}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_llm(self, user_prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("LLM returned empty content")
        return content

    def _parse_response(self, raw: str) -> PhenomenonGraph:
        # Attempt 1: direct parse
        try:
            data: Any = json.loads(raw.strip())
            return PhenomenonGraph(**data)
        except (json.JSONDecodeError, Exception):
            pass

        # Attempt 2: extract the first {...} block with regex
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                return PhenomenonGraph(**data)
            except (json.JSONDecodeError, Exception) as exc:
                raise ValueError(
                    f"JSON extracted by regex is still invalid: {exc}\nRaw content:\n{raw[:500]}"
                ) from exc

        raise ValueError(
            f"No JSON object found in LLM response.\nRaw content:\n{raw[:500]}"
        )
