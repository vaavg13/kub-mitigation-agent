from __future__ import annotations
import os
import shlex
from typing import List, Optional, Dict, Any
from typing import Literal
from pydantic import BaseModel, Field


class KubernetesAgentConfig(BaseModel):
    """Central configuration for the Kubernetes agent and LLM provider."""
    # Provider / model settings
    provider: str = Field(default=os.getenv("LLM_PROVIDER", "openai"))
    model: str = Field(default=os.getenv("LLM_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1")))
    temperature: float = Field(default=float(os.getenv("LLM_TEMPERATURE", "0.2")))
    max_tokens: int = Field(default=int(os.getenv("LLM_MAX_TOKENS", "4096")))
    request_timeout: int = Field(default=int(os.getenv("LLM_REQUEST_TIMEOUT", "120")))

    # API keys / endpoints (ingested from environment at instantiation time)
    openai_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    anthropic_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    google_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("GOOGLE_API_KEY"))
    xai_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("XAI_API_KEY"))
    xai_base_url: Optional[str] = Field(default_factory=lambda: os.getenv("XAI_BASE_URL"))

    # Agent behavior
    max_rounds: int = Field(default=10)
    agent_timeout: int = Field(default=120)
    agent_type: Literal["graph", "react"] = Field(default="graph")

    # MCP
    mcp_server_command: List[str] = Field(default_factory=lambda: ["node", "--no-deprecation", "./mcp-server-kubernetes/dist/index.js"])
    mcp_timeout_seconds: int = Field(default=int(os.getenv("MCP_TIMEOUT_SECONDS", "180")))

    @classmethod
    def from_yaml_dict(cls, y: Dict[str, Any]) -> "KubernetesAgentConfig":
        """Construct config from a nested YAML dict while reading API keys from env."""
        y = y or {}
        llm = y.get("llm", {}) or {}
        agent = y.get("agent", {}) or {}
        mcp = y.get("mcp", {}) or {}

        server_cmd_raw = mcp.get("server_command")
        if isinstance(server_cmd_raw, str):
            server_cmd = shlex.split(server_cmd_raw)
        elif isinstance(server_cmd_raw, list):
            server_cmd = server_cmd_raw
        else:
            server_cmd = os.getenv("MCP_SERVER_COMMAND", "node --no-deprecation ./mcp-server-kubernetes/dist/index.js").split(" ")

        return cls(
            # LLM - use YAML values, fall back to defaults if not present
            provider=llm.get("provider", "openai"),
            model=llm.get("model", "gpt-4.1"),
            temperature=float(llm.get("temperature", "0.2")),
            max_tokens=int(llm.get("max_tokens", "4096")),
            request_timeout=int(llm.get("request_timeout", "120")),

            # Agent behavior - use YAML values, fall back to defaults if not present
            max_rounds=int(agent.get("max_rounds", "10")),
            agent_timeout=int(agent.get("timeout", "120")),
            agent_type=str(
                agent.get(
                    "agent_type",
                    agent.get("type", "graph")
                )
            ).lower(),

            # MCP
            mcp_server_command=server_cmd,
            mcp_timeout_seconds=int(mcp.get("timeout_seconds", os.getenv("MCP_TIMEOUT_SECONDS", "180"))),
        )