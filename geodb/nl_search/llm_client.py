"""
Thin client for the Ollama /api/generate endpoint.
"""
import requests
from geodb.nl_search.config import (
    OLLAMA_URL, MODEL_NAME, LLM_TIMEOUT, LLM_TEMPERATURE, LLM_MAX_TOKENS,
)


class LLMClient:

    def __init__(self, model: str = None, base_url: str = None):
        self.model = model or MODEL_NAME
        self.base_url = (base_url or OLLAMA_URL).rstrip("/")

    def generate(self, prompt: str, system: str = "",
                 temperature: float = None, max_tokens: int = None) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": temperature if temperature is not None else LLM_TEMPERATURE,
                "num_predict": max_tokens or LLM_MAX_TOKENS,
            },
        }
        try:
            r = requests.post(f"{self.base_url}/api/generate",
                              json=payload, timeout=LLM_TIMEOUT)
            r.raise_for_status()
            return r.json().get("response", "").strip()
        except requests.ConnectionError:
            raise ConnectionError(
                f"Cannot reach Ollama at {self.base_url}. Run: ollama serve")
        except requests.Timeout:
            raise RuntimeError(f"Ollama timed out ({LLM_TIMEOUT}s)")
        except requests.HTTPError as e:
            raise RuntimeError(f"Ollama HTTP error: {e}")

    def is_available(self) -> bool:
        try:
            return requests.get(f"{self.base_url}/api/tags", timeout=5).ok
        except Exception:
            return False
