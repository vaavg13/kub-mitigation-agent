from __future__ import annotations
import os
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class KubernetesAgentConfig(BaseModel):
    """Central configuration for the Kubernetes agent and LLM provider."""
    # Provider / model settings
    provider: str = Field(default="openai")
    model: str = Field(default="gpt-4.1")
    temperature: float = Field(default=0.2)
    max_tokens: int = Field(default=4096)
    request_timeout: int = Field(default=120)

    # API keys / endpoints (ingested from environment at instantiation time)
    openai_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    anthropic_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    google_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("GOOGLE_API_KEY"))
    xai_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("XAI_API_KEY"))
    xai_base_url: Optional[str] = Field(default_factory=lambda: os.getenv("XAI_BASE_URL"))

    # Agent behavior
    enabled: bool = Field(default=True)
    max_rounds: int = Field(default=10)
    agent_timeout: int = Field(default=120)
    recursion_limit: int = Field(default=100)
    full_output: bool = Field(default=True)
    # MCP
    mcp_server_command: str = Field(default="node --no-deprecation ./mcp-server-kubernetes/dist/index.js")
    mcp_timeout_seconds: int = Field(default=180)

    @classmethod
    def from_yaml_dict(cls, y: Dict[str, Any]) -> "KubernetesAgentConfig":
        """Construct config from a nested YAML dict while reading API keys from env."""
        y = y or {}
        llm = y.get("llm", {})
        agent = y.get("agent", {})
        mcp = y.get("mcp", {})

        server_cmd_raw = mcp.get("server_command")
        if isinstance(server_cmd_raw, list):
            raise ValueError("mcp.server_command must be a single string, not a list")
        if isinstance(server_cmd_raw, str) and server_cmd_raw.strip():
            server_cmd = server_cmd_raw.strip()
        else:
            server_cmd = "node --no-deprecation ./mcp-server-kubernetes/dist/index.js"

        return cls(
            # LLM - use YAML values, fall back to defaults if not present
            provider=llm.get("provider", "openai"),
            model=llm.get("model", "gpt-4.1"),
            temperature=llm.get("temperature", 0.2),
            max_tokens=llm.get("max_tokens", 4096),
            request_timeout=llm.get("request_timeout", 120),

            # Agent behavior - use YAML values, fall back to defaults if not present
            enabled=agent.get("enabled", True),
            max_rounds=agent.get("max_rounds", 10),
            agent_timeout=agent.get("timeout", 120),
            recursion_limit=agent.get("recursion_limit", int(os.getenv("AGENT_RECURSION_LIMIT", "100"))),
            full_output=agent.get("full_output", True),

            # MCP
            mcp_server_command=server_cmd,
            mcp_timeout_seconds=mcp.get("timeout_seconds", 180),
        )