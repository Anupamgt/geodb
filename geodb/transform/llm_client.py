"""
LLM client for the transform system.

Priority:
  1. Cloud API  — if GEODB_CLOUD_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY is set
  2. Ollama     — local fallback (requires `ollama serve`)

Set env vars to switch:
  GEODB_CLOUD_PROVIDER = openai | anthropic          (default: openai)
  GEODB_CLOUD_API_KEY  = sk-...  / your Anthropic key
  GEODB_CLOUD_MODEL    = gpt-4o | claude-sonnet-4-6  (default: gpt-4o-mini)

  GEODB_MODEL   = local Ollama model name             (default: qwen2.5-coder:7b)
  OLLAMA_URL    = Ollama base URL                     (default: http://localhost:11434)
"""
import time
import requests

from geodb.transform.config import (
    OLLAMA_URL, MODEL_NAME, LLM_TIMEOUT, LLM_TEMPERATURE, LLM_MAX_TOKENS,
    CLOUD_PROVIDER, CLOUD_API_KEY, CLOUD_MODEL, CLOUD_BASE_URL, CLOUD_TIMEOUT,
)


class LLMClient:
    global_tokens_used = 0


    def __init__(self, model: str = None, base_url: str = None,
                 provider: str = None, api_key: str = None):
        """
        If api_key (or the env var) is set, use the cloud API.
        Otherwise fall back to local Ollama.
        """
        self._api_key   = api_key   or CLOUD_API_KEY
        self._provider  = provider  or CLOUD_PROVIDER
        self._cloud_model = model   or CLOUD_MODEL
        self._cloud_url = base_url  or CLOUD_BASE_URL

        self._ollama_url   = OLLAMA_URL.rstrip("/")
        self._ollama_model = model or MODEL_NAME

        self.using_cloud = bool(self._api_key)

        if self.using_cloud:
            self.model = self._cloud_model
        else:
            self.model = self._ollama_model

    # ── Public interface ──────────────────────────────────────────────────────

    def generate(self, prompt: str, system: str = "",
                 temperature: float = None, max_tokens: int = None) -> str:
        if self.using_cloud:
            return self._cloud_generate(prompt, system,
                                        temperature or LLM_TEMPERATURE,
                                        max_tokens  or LLM_MAX_TOKENS)
        return self._ollama_generate(prompt, system,
                                     temperature or LLM_TEMPERATURE,
                                     max_tokens  or LLM_MAX_TOKENS)

    def is_available(self) -> bool:
        if self.using_cloud:
            return bool(self._api_key)
        try:
            return requests.get(f"{self._ollama_url}/api/tags", timeout=5).ok
        except Exception:
            return False

    # ── Cloud (OpenAI / Anthropic) ────────────────────────────────────────────

    def _cloud_generate(self, prompt, system, temperature, max_tokens):
        if self._provider == "anthropic":
            return self._call_anthropic(prompt, system, temperature, max_tokens)
        return self._call_openai(prompt, system, temperature, max_tokens)

    def _call_openai(self, prompt, system, temperature, max_tokens):
        default_url = "https://generativelanguage.googleapis.com/v1beta/openai" if self._provider == "gemini" else "https://api.openai.com/v1"
        url = (self._cloud_url or default_url).rstrip("/")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._cloud_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

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
                        "or switch model: python -m geodb.transform config --model gpt-4o-mini"
                    )
                if r.status_code == 401:
                    raise RuntimeError(
                        "OpenAI API key rejected (401). "
                        "Check your key at platform.openai.com/api-keys and re-run: "
                        "python -m geodb.transform config --api-key YOUR_KEY"
                    )
                r.raise_for_status()
                resp_json = r.json()
                usage = resp_json.get("usage", {})
                type(self).global_tokens_used += usage.get("total_tokens", 0)
                return resp_json["choices"][0]["message"]["content"].strip()
            except requests.ConnectionError:
                raise ConnectionError(f"Cannot reach OpenAI API at {url}")
            except RuntimeError:
                raise
            except Exception as e:
                raise RuntimeError(f"OpenAI error: {e}")

    def _call_anthropic(self, prompt, system, temperature, max_tokens):
        url = (self._cloud_url or "https://api.anthropic.com/v1").rstrip("/")
        payload = {
            "model": self._cloud_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        try:
            r = requests.post(f"{url}/messages",
                              json=payload, headers=headers,
                              timeout=CLOUD_TIMEOUT)
            r.raise_for_status()
            resp_json = r.json()
            usage = resp_json.get("usage", {})
            type(self).global_tokens_used += (usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
            blocks = resp_json.get("content", [])
            return "".join(b.get("text", "") for b in blocks
                           if b.get("type") == "text").strip()
        except requests.ConnectionError:
            raise ConnectionError(f"Cannot reach Anthropic API at {url}")
        except Exception as e:
            raise RuntimeError(f"Anthropic error: {e}")

    # ── Ollama (local) ────────────────────────────────────────────────────────

    def _ollama_generate(self, prompt, system, temperature, max_tokens):
        payload = {
            "model": self._ollama_model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        try:
            r = requests.post(f"{self._ollama_url}/api/generate",
                              json=payload, timeout=LLM_TIMEOUT)
            r.raise_for_status()
            return r.json().get("response", "").strip()
        except requests.ConnectionError:
            raise ConnectionError(
                f"Cannot reach Ollama at {self._ollama_url}. Run: ollama serve"
            )
        except requests.Timeout:
            raise RuntimeError(f"Ollama timed out ({LLM_TIMEOUT}s)")
        except Exception as e:
            raise RuntimeError(f"LLM error: {e}")
