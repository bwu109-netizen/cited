"""Thin LLM wrapper with one interface for many providers.
Copied from tea-review-insight/src/llm_client.py and adapted: every call returns (json, usage),
DeepSeek defaults to deepseek-flash, and `cached_complete_json` caches replies on disk.

- Gemini (Google): native API, free tier, falls back to other Flash models when busy.
- Claude (Anthropic): native Messages API.
- OpenAI, DeepSeek, Qwen, Kimi, GLM and any other OpenAI-compatible endpoint: chat/completions.

The pipeline picks the provider from .env (LLM_PROVIDER, default deepseek; fallback gemini)."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

import requests

from . import config


class LLMError(RuntimeError):
    pass


class BaseClient:
    name = "base"

    model = ""

    def complete_json(self, system: str, user: str) -> tuple[dict, dict]:
        """Return (parsed JSON, usage) where usage = {input_tokens, cached_input_tokens, output_tokens}."""
        raise NotImplementedError

    def _post(self, url: str, headers: dict, body: dict, max_retries: int = 5) -> dict:
        delay = 5.0
        for attempt in range(max_retries):
            try:
                r = requests.post(url, headers=headers, json=body, timeout=120)
            except requests.RequestException as e:
                err = str(e)
            else:
                if r.status_code == 200:
                    return r.json()
                try:
                    msg = r.json().get("error", {}).get("message", r.text)
                except ValueError:
                    msg = r.text
                err = f"HTTP {r.status_code}: {str(msg)[:200]}"
                if r.status_code in (400, 401, 403, 404):
                    raise LLMError(err)  # bad key / model name: retrying won't help
            print(f"  [{self.name}] {err} -> retry in {delay:.0f}s ({attempt + 1}/{max_retries})")
            time.sleep(delay)
            delay = min(delay * 2, 120)
        raise LLMError(f"{self.name}: gave up after {max_retries} tries")


class GeminiClient(BaseClient):
    name = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key: str = config.GEMINI_API_KEY, model: str = config.GEMINI_MODEL,
                 fallbacks: list[str] | None = None):
        if not api_key:
            raise LLMError("GEMINI_API_KEY is empty. Put it in .env")
        self.key, self.model = api_key, model
        self.fallbacks = config.GEMINI_FALLBACK_MODELS if fallbacks is None else fallbacks

    def complete_json(self, system: str, user: str) -> tuple[dict, dict]:
        """Try the main model; if it is overloaded (503/429), move on to the fallback models."""
        models = [self.model] + [m for m in self.fallbacks if m != self.model]
        last = None
        for i, model in enumerate(models):
            try:
                out = self._call(model, system, user, max_retries=3 if i < len(models) - 1 else 5)
                if model != self.model:
                    print(f"  [gemini] switched to {model} (main model busy)")
                    self.model = model  # stick with the one that works
                return out
            except LLMError as e:
                # 503/429 = busy, 404 = model retired: try the next model. Other 4xx = bad key/request.
                if "HTTP 4" in str(e) and not any(c in str(e) for c in ("429", "404")):
                    raise
                print(f"  [gemini] {model} unavailable, trying next model")
                last = e
        raise last

    def _call(self, model: str, system: str, user: str, max_retries: int) -> tuple[dict, dict]:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        data = self._post(
            f"{self.BASE}/models/{model}:generateContent",
            {"x-goog-api-key": self.key, "Content-Type": "application/json"},
            body,
            max_retries=max_retries,
        )
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise LLMError(f"Unexpected Gemini response: {json.dumps(data)[:300]}")
        um = data.get("usageMetadata", {})
        usage = {"input_tokens": um.get("promptTokenCount", 0),
                 "cached_input_tokens": um.get("cachedContentTokenCount", 0),
                 "output_tokens": um.get("candidatesTokenCount", 0) + um.get("thoughtsTokenCount", 0),
                 "model": model}
        return parse_json(text), usage

    def list_models(self) -> list[str]:
        r = requests.get(f"{self.BASE}/models", headers={"x-goog-api-key": self.key}, timeout=30)
        r.raise_for_status()
        return [
            m["name"].removeprefix("models/")
            for m in r.json().get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]


class OpenAICompatClient(BaseClient):
    """Any OpenAI-compatible chat/completions endpoint (OpenAI, DeepSeek, Qwen, Kimi, GLM...)."""

    def __init__(self, api_key: str, model: str, base_url: str, name: str = "openai-compatible"):
        if not api_key:
            raise LLMError(f"{name}: API key is empty")
        if not model:
            raise LLMError(f"{name}: model name is empty")
        self.key, self.model, self.base, self.name = api_key, model, base_url.rstrip("/"), name
        self.json_mode = True

    extra_body: dict = {}
    max_tokens = 16000

    def complete_json(self, system: str, user: str) -> tuple[dict, dict]:
        body = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            **self.extra_body,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        try:
            data = self._post(f"{self.base}/chat/completions", headers, body)
        except LLMError as e:
            # some compatible endpoints reject response_format: retry once without it
            if self.json_mode and "HTTP 400" in str(e):
                self.json_mode = False
                body.pop("response_format")
                data = self._post(f"{self.base}/chat/completions", headers, body)
            else:
                raise
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError(f"Unexpected response: {json.dumps(data)[:300]}")
        u = data.get("usage", {})
        cached = u.get("prompt_cache_hit_tokens", (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0))
        usage = {"input_tokens": u.get("prompt_tokens", 0), "cached_input_tokens": cached or 0,
                 "output_tokens": u.get("completion_tokens", 0), "model": self.model}
        return parse_json(content), usage


class DeepSeekClient(OpenAICompatClient):
    def __init__(self, api_key: str = config.DEEPSEEK_API_KEY, model: str = config.DEEPSEEK_MODEL,
                 base_url: str = "https://api.deepseek.com"):
        super().__init__(api_key, model, base_url, name="deepseek")
        # deepseek-flash reasons by default; low effort keeps extraction cheap
        self.extra_body = {"reasoning_effort": config.DEEPSEEK_EFFORT} if config.DEEPSEEK_EFFORT else {}


class AnthropicClient(BaseClient):
    name = "claude"
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise LLMError("claude: API key is empty")
        if not model:
            raise LLMError("claude: model name is empty")
        self.key, self.model = api_key, model

    def complete_json(self, system: str, user: str) -> tuple[dict, dict]:
        body = {
            "model": self.model,
            "max_tokens": 8000,
            "temperature": 0,
            "system": system + "\nReply with the JSON object only.",
            "messages": [{"role": "user", "content": user}],
        }
        headers = {"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        data = self._post(self.URL, headers, body)
        try:
            text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError):
            raise LLMError(f"Unexpected Claude response: {json.dumps(data)[:300]}")
        u = data.get("usage", {})
        usage = {"input_tokens": u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0),
                 "cached_input_tokens": u.get("cache_read_input_tokens", 0),
                 "output_tokens": u.get("output_tokens", 0), "model": self.model}
        return parse_json(text), usage


# Presets shown in the web app. Model names change often, so only the ones verified while
# building this project are pre-filled; for the others the user types the model from their console.
PROVIDERS = {
    "gemini": {"label": "Google Gemini", "kind": "gemini", "model": "gemini-3.5-flash-lite",
               "key_url": "https://aistudio.google.com"},
    "deepseek": {"label": "DeepSeek", "kind": "openai", "base_url": "https://api.deepseek.com",
                 "model": "deepseek-flash", "key_url": "https://platform.deepseek.com"},
    "openai": {"label": "OpenAI", "kind": "openai", "base_url": "https://api.openai.com/v1",
               "model": "", "key_url": "https://platform.openai.com"},
    "claude": {"label": "Anthropic Claude", "kind": "claude", "model": "",
               "key_url": "https://console.anthropic.com"},
    "qwen": {"label": "Qwen (Alibaba Cloud Model Studio)", "kind": "openai",
             "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "",
             "key_url": "https://bailian.console.aliyun.com"},
    "kimi": {"label": "Kimi (Moonshot)", "kind": "openai", "base_url": "https://api.moonshot.cn/v1",
             "model": "", "key_url": "https://platform.moonshot.cn"},
    "glm": {"label": "GLM (Zhipu)", "kind": "openai", "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "", "key_url": "https://open.bigmodel.cn"},
    "custom": {"label": "Other OpenAI-compatible", "kind": "openai", "base_url": "", "model": "",
               "key_url": ""},
}


def make_client(provider: str, api_key: str, model: str = "", base_url: str = "") -> BaseClient:
    p = PROVIDERS[provider]
    model = model.strip() or p.get("model", "")
    if p["kind"] == "gemini":
        return GeminiClient(api_key=api_key, model=model or config.GEMINI_MODEL)
    if p["kind"] == "claude":
        return AnthropicClient(api_key, model)
    url = base_url.strip() or p.get("base_url", "")
    if not url:
        raise LLMError("Base URL is empty")
    return OpenAICompatClient(api_key, model, url, name=provider)


def parse_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # models without a JSON mode sometimes add a sentence around the object
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise LLMError(f"Model did not return valid JSON: {e}; got: {text[:200]}")


def get_client(provider: str | None = None) -> BaseClient:
    provider = (provider or config.LLM_PROVIDER).lower()
    if provider == "gemini":
        return GeminiClient()
    if provider == "deepseek":
        return DeepSeekClient()
    raise LLMError(f"Unknown provider: {provider}")


# ---- cost + cache ------------------------------------------------------------

def cost_usd(usage: dict, at: datetime | None = None) -> float | None:
    """USD cost of one call from config.PRICES; None when the model has no price entry."""
    table = config.PRICES.get(usage.get("model", ""))
    if not table:
        return None
    if "flat" in table:
        p = table["flat"]
    else:
        at = at or datetime.now(timezone.utc)
        h = at.hour + at.minute / 60
        peak = at.weekday() < 5 and (1 <= h < 4 or 6 <= h < 10)
        p = table["peak" if peak else "offpeak"]
    hit = usage.get("cached_input_tokens", 0)
    miss = usage.get("input_tokens", 0) - hit
    return (hit * p["input_hit"] + miss * p["input_miss"] + usage.get("output_tokens", 0) * p["output"]) / 1e6


def cached_complete_json(system: str, user: str, providers: list[str] | None = None,
                         use_cache: bool = True) -> dict:
    """Call the first working provider; replies are cached by (provider, model, prompt) hash.

    Returns {"data", "usage", "cost_usd", "provider", "model", "from_cache"}. Cost/usage of a cache hit
    are those of the original call (reported with from_cache=True), so reruns cost nothing."""
    providers = providers or config.provider_order()
    if not providers:
        raise LLMError("No LLM API key found in .env (DEEPSEEK_API_KEY / GEMINI_API_KEY)")
    cache_dir = config.CACHE_DIR / "llm"
    cache_dir.mkdir(parents=True, exist_ok=True)
    errors = []
    for name in providers:
        client = get_client(name)
        key = hashlib.sha256(json.dumps([name, client.model, system, user]).encode()).hexdigest()
        path = cache_dir / f"{key}.json"
        if use_cache and path.exists():
            rec = json.loads(path.read_text())
            rec["from_cache"] = True
            return rec
        data = None
        for attempt in range(2):  # one retry when the reply is not valid JSON
            try:
                t0 = datetime.now(timezone.utc)
                data, usage = client.complete_json(system, user)
                break
            except LLMError as e:
                errors.append(f"{name}: {str(e)[:200]}")
                print(f"  [llm] {name} failed: {str(e)[:120]}")
                if "valid JSON" not in str(e):
                    break
        if data is None:
            continue
        rec = {"data": data, "usage": usage, "cost_usd": cost_usd(usage, t0), "provider": name,
               "model": usage.get("model", client.model), "called_at": t0.isoformat(), "from_cache": False}
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
        return rec
    raise LLMError("All providers failed: " + " | ".join(errors))
