"""LLM client for Agent Factory — supports Ollama (local) and cloud APIs."""
import time
import requests

from geodb.agent_factory.config import (
    OLLAMA_URL, MODEL_NAME, LLM_TIMEOUT, LLM_TEMPERATURE, LLM_MAX_TOKENS,
    CLOUD_PROVIDER, CLOUD_API_KEY, CLOUD_MODEL, CLOUD_BASE_URL, CLOUD_TIMEOUT,
)


class LLMClient:

    def __init__(self, model=None, base_url=None, provider=None, api_key=None):
        self._api_key     = api_key  or CLOUD_API_KEY
        self._provider    = provider or CLOUD_PROVIDER
        self._cloud_model = model    or CLOUD_MODEL
        self._cloud_url   = base_url or CLOUD_BASE_URL

        self._ollama_url   = OLLAMA_URL.rstrip("/")
        self._ollama_model = model or MODEL_NAME

        self.using_cloud = bool(self._api_key)
        self.model = self._cloud_model if self.using_cloud else self._ollama_model

    def generate(self, prompt, system="", temperature=None, max_tokens=None):
        if self.using_cloud:
            return self._cloud(prompt, system,
                               temperature or LLM_TEMPERATURE,
                               max_tokens  or LLM_MAX_TOKENS)
        return self._ollama(prompt, system,
                            temperature or LLM_TEMPERATURE,
                            max_tokens  or LLM_MAX_TOKENS)

    def is_available(self):
        if self.using_cloud:
            return bool(self._api_key)
        try:
            return requests.get(f"{self._ollama_url}/api/tags", timeout=5).ok
        except Exception:
            return False

    # ── Cloud ─────────────────────────────────────────────────────────────────

    def _cloud(self, prompt, system, temperature, max_tokens):
        if self._provider == "anthropic":
            return self._anthropic(prompt, system, temperature, max_tokens)
        return self._openai(prompt, system, temperature, max_tokens)

    def _openai(self, prompt, system, temperature, max_tokens):
        default_url = "https://generativelanguage.googleapis.com/v1beta/openai" if self._provider == "gemini" else "https://api.openai.com/v1"
        url = (self._cloud_url or default_url).rstrip("/")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        headers = {"Authorization": f"Bearer {self._api_key}",
                   "Content-Type": "application/json"}
        payload = {"model": self._cloud_model, "messages": messages,
                   "temperature": temperature, "max_tokens": max_tokens}

        for attempt in range(5):
            try:
                r = requests.post(f"{url}/chat/completions",
                                  json=payload, headers=headers,
                                  timeout=CLOUD_TIMEOUT)
                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After", "")
                    wait = int(retry_after) if retry_after.isdigit() else min(2 ** attempt * 10, 120)
                    if attempt < 4:
                        print(f"  ⏳ Rate limited, retrying in {wait}s… (attempt {attempt+1}/5)")
                        time.sleep(wait)
                        continue
                    raise RuntimeError(
                        "OpenAI rate limit hit 5 times. "
                        "Add billing at platform.openai.com/settings/organization/billing "
                        "or switch to a different model with: "
                        "python -m geodb.transform config --model gpt-4o-mini"
                    )
                if r.status_code == 401:
                    raise RuntimeError(
                        "OpenAI API key rejected (401). "
                        "Check your key at platform.openai.com/api-keys and re-run: "
                        "python -m geodb.transform config --api-key YOUR_KEY"
                    )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"].strip()
            except (requests.ConnectionError, RuntimeError):
                raise
            except Exception as e:
                raise RuntimeError(f"OpenAI error: {e}")

    def _anthropic(self, prompt, system, temperature, max_tokens):
        url = (self._cloud_url or "https://api.anthropic.com/v1").rstrip("/")
        payload = {"model": self._cloud_model,
                   "messages": [{"role": "user", "content": prompt}],
                   "max_tokens": max_tokens, "temperature": temperature}
        if system:
            payload["system"] = system
        headers = {"x-api-key": self._api_key,
                   "anthropic-version": "2023-06-01",
                   "Content-Type": "application/json"}
        try:
            r = requests.post(f"{url}/messages",
                              json=payload, headers=headers,
                              timeout=CLOUD_TIMEOUT)
            r.raise_for_status()
            blocks = r.json().get("content", [])
            return "".join(b.get("text", "") for b in blocks
                           if b.get("type") == "text").strip()
        except Exception as e:
            raise RuntimeError(f"Anthropic error: {e}")

    # ── Ollama ────────────────────────────────────────────────────────────────

    def _ollama(self, prompt, system, temperature, max_tokens):
        payload = {"model": self._ollama_model, "prompt": prompt,
                   "system": system, "stream": False,
                   "options": {"temperature": temperature,
                               "num_predict": max_tokens}}
        try:
            r = requests.post(f"{self._ollama_url}/api/generate",
                              json=payload, timeout=LLM_TIMEOUT)
            r.raise_for_status()
            return r.json().get("response", "").strip()
        except requests.ConnectionError:
            raise ConnectionError(
                f"Cannot reach Ollama at {self._ollama_url}. Run: ollama serve")
        except Exception as e:
            raise RuntimeError(f"LLM error: {e}")
