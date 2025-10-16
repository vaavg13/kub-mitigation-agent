#!/usr/bin/env python3
from typing import Any
from .config import KubernetesAgentConfig


def get_llm(cfg: KubernetesAgentConfig) -> Any:
    """
    Return a LangChain chat model instance matching the provider.
    """
    # Lazy imports to avoid optional deps when not needed
    if cfg.provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=cfg.model,
            api_key=cfg.openai_api_key,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            timeout=cfg.request_timeout
        )
    if cfg.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=cfg.model,
            api_key=cfg.anthropic_api_key,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            timeout=cfg.request_timeout
        )
    if cfg.provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=cfg.model,
            google_api_key=cfg.google_api_key,
            temperature=cfg.temperature,
            max_output_tokens=cfg.max_tokens,
            timeout=cfg.request_timeout
        )
    if cfg.provider == "xai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=cfg.model,
            api_key=cfg.xai_api_key,
            base_url=cfg.xai_base_url,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            timeout=cfg.request_timeout
        )
    raise ValueError(f"Unsupported provider: {cfg.provider}")


