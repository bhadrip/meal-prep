import json
from abc import ABC, abstractmethod
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from .config import Settings

T = TypeVar("T", bound=BaseModel)


class ModelUnavailable(RuntimeError):
    pass


class ModelProvider(ABC):
    label: str

    @abstractmethod
    async def complete_structured(
        self, *, system: str, prompt: str, response_model: type[T]
    ) -> T:
        raise NotImplementedError


class OllamaProvider(ModelProvider):
    def __init__(self, settings: Settings):
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model
        self.timeout = settings.model_timeout_seconds
        self.label = f"Ollama · {self.model}"

    async def complete_structured(
        self, *, system: str, prompt: str, response_model: type[T]
    ) -> T:
        schema = response_model.model_json_schema()
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": f"{prompt}\n\nReturn JSON matching this schema:\n{json.dumps(schema)}",
                },
            ],
            "stream": False,
            "format": schema,
            "think": False,
            "options": {"temperature": 0, "num_predict": 320},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                content = response.json()["message"]["content"]
            return response_model.model_validate_json(content)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ModelUnavailable(str(exc)) from exc


class OpenRouterProvider(ModelProvider):
    def __init__(self, settings: Settings):
        if not settings.openrouter_api_key:
            raise ModelUnavailable("OPENROUTER_API_KEY is not configured")
        self.base_url = settings.openrouter_base_url.rstrip("/")
        self.api_key = settings.openrouter_api_key
        self.model = settings.openrouter_model
        self.timeout = settings.model_timeout_seconds
        self.site_url = settings.openrouter_site_url
        self.app_name = settings.openrouter_app_name
        self.label = f"OpenRouter · {self.model}"

    async def complete_structured(
        self, *, system: str, prompt: str, response_model: type[T]
    ) -> T:
        schema = response_model.model_json_schema()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.site_url,
            "X-Title": self.app_name,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
            return response_model.model_validate_json(content)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ModelUnavailable(str(exc)) from exc


def build_provider(settings: Settings) -> ModelProvider | None:
    if not settings.model_enabled or settings.model_provider == "disabled":
        return None
    if settings.model_provider == "openrouter":
        return OpenRouterProvider(settings)
    return OllamaProvider(settings)
