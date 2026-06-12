"""
Cloud LLM Client — uses OpenAI-compatible APIs (GPT, Claude, etc.)
for high-quality knowledge generation in Phase 0.

The cloud model generates knowledge patterns that guide the local 7B model.
"""
import os
import json


# ── Configuration ────────────────────────────────────────────────────────────

CLOUD_PROVIDER = os.environ.get("GEODB_CLOUD_PROVIDER", "openai")  # openai | anthropic
CLOUD_API_KEY = os.environ.get("GEODB_CLOUD_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
CLOUD_MODEL = os.environ.get("GEODB_CLOUD_MODEL", "gpt-4o-mini")
CLOUD_BASE_URL = os.environ.get("GEODB_CLOUD_BASE_URL", "")  # custom endpoint override
CLOUD_TIMEOUT = int(os.environ.get("GEODB_CLOUD_TIMEOUT", "60"))
CLOUD_MAX_TOKENS = int(os.environ.get("GEODB_CLOUD_MAX_TOKENS", "4000"))


class CloudLLMClient:
    """
    Calls a cloud LLM (GPT, Claude, etc.) via their REST API.
    Used only for Phase 0 knowledge generation — not for step code.
    """

    def __init__(self, provider=None, api_key=None, model=None, base_url=None):
        self.provider = provider or CLOUD_PROVIDER
        self.api_key = api_key or CLOUD_API_KEY
        self.model = model or CLOUD_MODEL
        self.base_url = base_url or CLOUD_BASE_URL
        self.timeout = CLOUD_TIMEOUT

        if not self.api_key:
            raise ValueError(
                "No cloud API key found. Set GEODB_CLOUD_API_KEY or OPENAI_API_KEY "
                "environment variable."
            )

    def generate(self, prompt, system="", temperature=0.1, max_tokens=None):
        """
        Generate a response from the cloud LLM.
        Supports OpenAI and Anthropic APIs.
        """
        max_tokens = max_tokens or CLOUD_MAX_TOKENS

        if self.provider == "anthropic":
            return self._call_anthropic(prompt, system, temperature, max_tokens)
        else:
            return self._call_openai(prompt, system, temperature, max_tokens)

    def _call_openai(self, prompt, system, temperature, max_tokens):
        """Call OpenAI-compatible API (works with GPT, local proxies, etc.)."""
        import requests

        url = self.base_url or "https://api.openai.com/v1"
        url = url.rstrip("/")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        import time
        max_retries = 3
        for attempt in range(max_retries):
            try:
                r = requests.post(
                    f"{url}/chat/completions",
                    json=payload, headers=headers, timeout=self.timeout
                )
                if r.status_code == 429:
                    wait = min(2 ** attempt * 5, 30)  # 5s, 10s, 20s
                    retry_after = r.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        wait = min(int(retry_after), 60)
                    if attempt < max_retries - 1:
                        print(f"  ⏳ Rate limited, waiting {wait}s… (attempt {attempt+1}/{max_retries})")
                        time.sleep(wait)
                        continue
                    else:
                        raise RuntimeError(
                            f"OpenAI rate limit (429) after {max_retries} retries. "
                            f"Check billing at https://platform.openai.com/settings/organization/billing/overview"
                        )
                r.raise_for_status()
                data = r.json()
                return data["choices"][0]["message"]["content"].strip()
            except requests.ConnectionError:
                raise ConnectionError(f"Cannot reach OpenAI API at {url}")
            except RuntimeError:
                raise
            except Exception as e:
                raise RuntimeError(f"Cloud LLM error ({self.provider}): {e}")

    def _call_anthropic(self, prompt, system, temperature, max_tokens):
        """Call Anthropic Claude API."""
        import requests

        url = self.base_url or "https://api.anthropic.com/v1"
        url = url.rstrip("/")

        messages = [{"role": "user", "content": prompt}]

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        try:
            r = requests.post(
                f"{url}/messages",
                json=payload, headers=headers, timeout=self.timeout
            )
            r.raise_for_status()
            data = r.json()
            # Anthropic returns content as a list of blocks
            content_blocks = data.get("content", [])
            text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
            return text.strip()
        except requests.ConnectionError:
            raise ConnectionError(f"Cannot reach Anthropic API at {url}")
        except Exception as e:
            raise RuntimeError(f"Cloud LLM error ({self.provider}): {e}")

    def is_available(self):
        """Check if cloud API is reachable and key is set."""
        if not self.api_key:
            return False
        try:
            # Lightweight check — just verify connectivity
            import requests
            if self.provider == "anthropic":
                url = (self.base_url or "https://api.anthropic.com/v1").rstrip("/")
                r = requests.get(url, timeout=5)
                return r.status_code in (200, 401, 404)  # any response = reachable
            else:
                url = (self.base_url or "https://api.openai.com/v1").rstrip("/")
                r = requests.get(f"{url}/models", headers={
                    "Authorization": f"Bearer {self.api_key}"
                }, timeout=5)
                return r.status_code in (200, 401)
        except Exception:
            return False
