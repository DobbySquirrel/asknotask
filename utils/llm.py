"""LLM client. Defaults to a local OpenAI-compatible server at :8000.

Set LLM_PRESET to load configs/llm.yaml (or LLM_CONFIG). Use LLM_PRESET=env
with OPENAI_API_KEY and OPENAI_BASE_URL for a remote endpoint.
"""
from __future__ import annotations

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

import httpx

LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:8000/v1")
DEFAULT_MAX_TOKENS = 2048
CONTEXT_LIMIT = 32768


def _room_for_completion(message: str) -> int | None:
    """上下文不够放下 max_tokens 时，返回还能生成的长度。"""
    import re

    match = re.search(r"request has (\d+) input tokens", message or "")
    if not match:
        return None
    room = CONTEXT_LIMIT - int(match.group(1)) - 32
    if room < 256:
        return None
    return room
_REPO = Path(__file__).resolve().parents[1]
DEFAULT_PRESET = "local"


def _config_yaml() -> Path:
    env = (os.environ.get("LLM_CONFIG") or "").strip()
    if env:
        return Path(env)
    return _REPO / "configs" / "llm.yaml"


class LLM:
    def __init__(
        self,
        url: str = LLM_URL,
        model: Optional[str] = None,
        timeout: int = 300,
        api_key: str = "EMPTY",
        extra_body: Optional[dict] = None,
    ):
        from openai import OpenAI

        self.url = url
        self.api_key = api_key
        http_timeout = httpx.Timeout(connect=15.0, read=float(timeout), write=30.0, pool=15.0)
        self.client = OpenAI(api_key=api_key, base_url=url, timeout=http_timeout, max_retries=0)
        if model:
            self.model = model
        else:
            probe = OpenAI(api_key=api_key, base_url=url, timeout=httpx.Timeout(10.0), max_retries=0)
            self.model = probe.models.list().data[0].id
        self.extra_body = extra_body if extra_body is not None else {"enable_thinking": False}
        self.traces: list[str] = []
        self._trace_lock = threading.Lock()

    @classmethod
    def from_env(cls, timeout: int = 300) -> "LLM":
        """OPENAI_API_KEY + OPENAI_BASE_URL（可带 /v1/chat/completions）。不写 key 进 yaml。"""
        key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        url = (os.environ.get("OPENAI_BASE_URL") or os.environ.get("LLM_URL") or "").strip()
        if not key or not url:
            raise ValueError("from_env 需要 OPENAI_API_KEY 和 OPENAI_BASE_URL")
        url = url.rstrip("/")
        if url.endswith("/chat/completions"):
            url = url[: -len("/chat/completions")]
        model = (os.environ.get("OPENAI_MODEL") or "gpt-4o").strip()
        extra = {}
        if "qwen" in model.lower() or "dashscope" in url.lower() or "yi-zhan" in url.lower():
            extra = {"enable_thinking": False}
        return cls(url=url, model=model, api_key=key, extra_body=extra, timeout=timeout)

    @classmethod
    def from_preset(cls, name: Optional[str] = None, timeout: int = 300) -> "LLM":
        import yaml

        preset = name or os.environ.get("LLM_PRESET")
        if preset in {"env", "openai_env"}:
            return cls.from_env(timeout=timeout)
        if not preset:
            return cls(timeout=timeout)
        cfg_path = _config_yaml()
        if not cfg_path.is_file():
            raise SystemExit(
                f"LLM preset {preset!r} needs {cfg_path}. "
                "Copy configs/llm.yaml.example to configs/llm.yaml, or set LLM_CONFIG."
            )
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["llm_presets"][preset]
        extra = None
        if cfg.get("enable_thinking") is False:
            extra = {"enable_thinking": False}
        return cls(
            url=cfg["base_url"],
            model=cfg["model"],
            api_key=cfg["api_key"],
            extra_body=extra,
            timeout=timeout,
        )

    def complete(self, prompt: str, tries: int = 3, temperature: float = 0) -> str:
        with self._trace_lock:
            self.traces.append(prompt)
        last: Exception | None = None
        max_tokens = DEFAULT_MAX_TOKENS
        override = (os.environ.get("LLM_MAX_TOKENS") or os.environ.get("PAPER_EXP_LLM_MAX_TOKENS") or "").strip()
        if override:
            max_tokens = int(override)
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        fixed_seed = (os.environ.get("LLM_SEED_VALUE") or os.environ.get("PAPER_EXP_LLM_SEED_VALUE") or "").strip()
        if fixed_seed:
            kwargs["seed"] = int(fixed_seed)
        elif os.environ.get("LLM_SEED") or os.environ.get("PAPER_EXP_LLM_SEED"):
            import zlib

            kwargs["seed"] = zlib.crc32(prompt.encode("utf-8")) & 0x7FFFFFFF
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body
        for i in range(tries):
            try:
                resp = self.client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content or ""
            except Exception as e:
                last = e
                room = _room_for_completion(str(e))
                if room is not None and room < int(kwargs.get("max_tokens") or 0):
                    kwargs["max_tokens"] = room
                    print(f"[llm] shrink max_tokens to {room}", flush=True)
                    continue
                print(f"[llm] try {i + 1}/{tries} {type(e).__name__}: {e}", flush=True)
                time.sleep(2 * (i + 1))
        print(f"[llm] give up after {tries}: {type(last).__name__}: {last}", flush=True)
        return ""

    def complete_many(
        self,
        prompts: list[str],
        tries: int = 3,
        temperature: float = 0,
        max_workers: int = 8,
    ) -> list[str]:
        """并发打同一 vLLM（continuous batching）。单条仍走 complete。"""
        if not prompts:
            return []
        if len(prompts) == 1:
            return [self.complete(prompts[0], tries=tries, temperature=temperature)]
        out = [""] * len(prompts)

        def _one(i: int, p: str) -> tuple[int, str]:
            return i, self.complete(p, tries=tries, temperature=temperature)

        n = min(max(1, max_workers), len(prompts))
        with ThreadPoolExecutor(max_workers=n) as pool:
            futs = [pool.submit(_one, i, p) for i, p in enumerate(prompts)]
            for fut in as_completed(futs):
                i, text = fut.result()
                out[i] = text
        return out


def _last_json_dict(blob: str) -> dict[str, Any]:
    """从左到右扫 `{`，留下最后一个能 raw_decode 的对象。CLEAR 原文也是从围栏里取 JSON。"""
    import json

    blob = (blob or "").replace("True", "true").replace("False", "false").replace("None", "null")
    dec = json.JSONDecoder()
    last: dict[str, Any] = {}
    i = 0
    while True:
        j = blob.find("{", i)
        if j < 0:
            break
        try:
            obj, end = dec.raw_decode(blob, j)
            if isinstance(obj, dict) and obj:
                last = obj
            i = max(end, j + 1)
        except json.JSONDecodeError:
            i = j + 1
    return last


def parse_json_obj(text: str) -> dict[str, Any]:
    raw = text or ""
    chunks: list[str] = []
    if "```json" in raw.lower() or "```" in raw:
        parts = re.split(r"```(?:json)?", raw, flags=re.I)
        for i, part in enumerate(parts):
            if i % 2 == 1:
                chunks.append(part.strip())
    chunks.append(raw)
    for blob in reversed(chunks):
        obj = _last_json_dict(blob)
        if obj:
            return obj
    return {}


JSON_ONLY_RETRY = (
    "\n\nReturn ONLY one JSON object inside a ```json fence. "
    "No chain-of-thought, no markdown besides that fence."
)


def parse_sql(text: str) -> str:
    raw = text or ""
    m = re.search(r"<result>\s*(.*?)\s*</result>", raw, flags=re.S | re.I)
    if m:
        raw = m.group(1)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 1)[1]
        if raw.startswith("sql"):
            raw = raw[3:]
        raw = raw.split("```", 1)[0]
    raw = raw.strip().strip("`").strip()
    for line in raw.splitlines():
        if line.strip().lower().startswith(("select", "with")):
            start = raw.lower().find(line.strip().lower()[:6])
            raw = raw[start:] if start >= 0 else raw
            break
    return raw.strip().rstrip(";").strip()
