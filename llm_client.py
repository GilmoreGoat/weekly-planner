from __future__ import annotations

"""
llm_client.py — provider-agnostic LLM wrapper.

Supported providers:
  - openai      (GPT-4o, GPT-4-turbo, etc.)
  - anthropic   (Claude Sonnet, Haiku, etc.)
  - gemini      (Gemini 1.5 Pro, Flash, etc.)
  - ollama      (local models — no API key needed)

Usage:
    client = LLMClient.from_env()          # auto-detects from env vars
    client = LLMClient("openai", "sk-...") # explicit
    response = client.chat("Your prompt here")
"""

import os
from dataclasses import dataclass, field
from typing import Any


PROVIDER_MODELS: dict[str, str] = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-6",
    "gemini": "gemini-1.5-pro",
    "ollama": "llama3",
}

PROVIDER_ENV_KEYS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "ollama": "",  # no key needed
}


@dataclass
class LLMClient:
    provider: str          # "openai" | "anthropic" | "gemini" | "ollama"
    api_key: str = ""
    model: str = ""
    base_url: str = ""     # for ollama or custom endpoints
    _client: Any = field(default=None, repr=False, init=False)

    def __post_init__(self) -> None:
        self.provider = self.provider.lower().strip()
        if not self.model:
            self.model = PROVIDER_MODELS.get(self.provider, "")
        self._client = self._build_client()

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "LLMClient":
        """
        Auto-detect provider from environment variables.
        Checks in order: OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, OLLAMA_BASE_URL.
        Raises ValueError if none are found.
        """
        provider_override = os.environ.get("LLM_PROVIDER", "").lower()
        model_override = os.environ.get("LLM_MODEL", "")

        if provider_override:
            key = os.environ.get(PROVIDER_ENV_KEYS.get(provider_override, ""), "")
            return cls(
                provider=provider_override,
                api_key=key,
                model=model_override,
                base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
            )

        # Auto-detect
        for provider, env_key in PROVIDER_ENV_KEYS.items():
            if provider == "ollama":
                if os.environ.get("OLLAMA_BASE_URL") or _ollama_running():
                    return cls(
                        provider="ollama",
                        model=model_override or PROVIDER_MODELS["ollama"],
                        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
                    )
                continue
            if env_key and os.environ.get(env_key):
                return cls(
                    provider=provider,
                    api_key=os.environ[env_key],
                    model=model_override or PROVIDER_MODELS[provider],
                )

        raise ValueError(
            "No LLM provider configured. Set one of:\n"
            "  OPENAI_API_KEY       → uses GPT-4o\n"
            "  ANTHROPIC_API_KEY    → uses Claude Sonnet\n"
            "  GEMINI_API_KEY       → uses Gemini 1.5 Pro\n"
            "  OLLAMA_BASE_URL      → uses local Ollama (no key needed)\n"
            "Or set LLM_PROVIDER + the matching key explicitly."
        )

    @classmethod
    def from_sidebar(
        cls,
        provider: str,
        api_key: str,
        model: str = "",
        ollama_url: str = "http://localhost:11434",
    ) -> "LLMClient":
        """Create from Streamlit sidebar inputs."""
        return cls(
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=ollama_url,
        )

    # ------------------------------------------------------------------
    # Client construction
    # ------------------------------------------------------------------

    def _build_client(self) -> Any:
        if self.provider == "openai":
            try:
                from openai import OpenAI
                return OpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError("Run: pip install openai")

        if self.provider == "anthropic":
            try:
                import anthropic
                return anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError("Run: pip install anthropic")

        if self.provider == "gemini":
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                return genai.GenerativeModel(self.model)
            except ImportError:
                raise ImportError("Run: pip install google-generativeai")

        if self.provider == "ollama":
            # No client object needed — we call the REST API directly
            return None

        raise ValueError(f"Unknown provider: {self.provider!r}. Choose: openai, anthropic, gemini, ollama")

    # ------------------------------------------------------------------
    # Unified chat interface
    # ------------------------------------------------------------------

    def chat(self, prompt: str, max_tokens: int = 4096, system: str = "") -> str:
        """
        Send a prompt and return the response text.
        Handles all provider differences internally.
        """
        if self.provider == "openai":
            return self._chat_openai(prompt, max_tokens, system)
        if self.provider == "anthropic":
            return self._chat_anthropic(prompt, max_tokens, system)
        if self.provider == "gemini":
            return self._chat_gemini(prompt, max_tokens, system)
        if self.provider == "ollama":
            return self._chat_ollama(prompt, max_tokens, system)
        raise ValueError(f"Unknown provider: {self.provider}")

    def _chat_openai(self, prompt: str, max_tokens: int, system: str) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=messages,
        )
        return resp.choices[0].message.content.strip()

    def _chat_anthropic(self, prompt: str, max_tokens: int, system: str) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        msg = self._client.messages.create(**kwargs)
        return msg.content[0].text.strip()

    def _chat_gemini(self, prompt: str, max_tokens: int, system: str) -> str:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        resp = self._client.generate_content(
            full_prompt,
            generation_config={"max_output_tokens": max_tokens},
        )
        return resp.text.strip()

    def _chat_ollama(self, prompt: str, max_tokens: int, system: str) -> str:
        import json as _json
        import urllib.request

        payload = {
            "model": self.model,
            "prompt": f"{system}\n\n{prompt}" if system else prompt,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        url = f"{self.base_url.rstrip('/')}/api/generate"
        req = urllib.request.Request(
            url,
            data=_json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            data = _json.loads(r.read())
        return data.get("response", "").strip()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def display_name(self) -> str:
        return f"{self.provider} / {self.model}"


def _ollama_running(url: str = "http://localhost:11434") -> bool:
    """Check if a local Ollama server is reachable."""
    import urllib.request
    try:
        urllib.request.urlopen(url, timeout=2)
        return True
    except Exception:
        return False


PROVIDER_LABELS = {
    "openai": "OpenAI (GPT-4o, GPT-4-turbo…)",
    "anthropic": "Anthropic (Claude Sonnet, Haiku…)",
    "gemini": "Google Gemini (1.5 Pro, Flash…)",
    "ollama": "Ollama (local, no API key needed)",
}

DEFAULT_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-4o", "gpt-4-turbo", "gpt-4o-mini", "gpt-3.5-turbo"],
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
    "gemini": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"],
    "ollama": ["llama3", "llama3:70b", "mistral", "phi3", "gemma2"],
}
