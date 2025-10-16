from __future__ import annotations
import os
import shlex
from typing import List, Optional, Dict, Any
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
    max_rounds: int = Field(default=int(os.getenv("AGENT_MAX_ROUNDS", "10")))
    show_reasoning: bool = Field(default=os.getenv("AGENT_SHOW_REASONING", "true").lower() == "true")
    reasoning_in_context: bool = Field(default=os.getenv("AGENT_REASONING_IN_CONTEXT", "true").lower() == "true")
    agent_timeout: int = Field(default=int(os.getenv("AGENT_TIMEOUT", "120")))
    agent_verbose: bool = Field(default=os.getenv("AGENT_VERBOSE", "false").lower() == "true")

    # MCP
    mcp_server_command: List[str] = Field(default_factory=lambda: os.getenv("MCP_SERVER_COMMAND", "node ./mcp-server-kubernetes/dist/index.js").split(" "))

    # (LangSmith config is loaded via environment/.env, not through this model)

    @classmethod
    def from_yaml_dict(cls, y: Dict[str, Any]) -> "KubernetesAgentConfig":
        """Construct config from a nested YAML dict while reading API keys from env."""
        y = y or {}
        llm = y.get("llm", {}) or {}
        agent = y.get("agent", {}) or {}
        mcp = y.get("mcp", {}) or {}
        # LangSmith settings are not read from YAML; environment should be used instead.

        server_cmd_raw = mcp.get("server_command")
        if isinstance(server_cmd_raw, str):
            server_cmd = shlex.split(server_cmd_raw)
        elif isinstance(server_cmd_raw, list):
            server_cmd = server_cmd_raw
        else:
            server_cmd = os.getenv("MCP_SERVER_COMMAND", "node ./mcp-server-kubernetes/dist/index.js").split(" ")

        return cls(
            # LLM
            provider=llm.get("provider", os.getenv("LLM_PROVIDER", "openai")),
            model=llm.get("model", os.getenv("LLM_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1"))),
            temperature=float(llm.get("temperature", os.getenv("LLM_TEMPERATURE", "0.2"))),
            max_tokens=int(llm.get("max_tokens", os.getenv("LLM_MAX_TOKENS", "4096"))),
            request_timeout=int(llm.get("request_timeout", os.getenv("LLM_REQUEST_TIMEOUT", "120"))),

            # Agent behavior
            max_rounds=int(agent.get("max_rounds", os.getenv("AGENT_MAX_ROUNDS", "10"))),
            agent_timeout=int(agent.get("timeout", os.getenv("AGENT_TIMEOUT", "120"))),
            show_reasoning=bool(agent.get("show_reasoning", os.getenv("AGENT_SHOW_REASONING", "true").lower() == "true")),
            reasoning_in_context=bool(agent.get("reasoning_in_context", os.getenv("AGENT_REASONING_IN_CONTEXT", "true").lower() == "true")),
            agent_verbose=bool(agent.get("verbose", os.getenv("AGENT_VERBOSE", "false").lower() == "true")),

            # MCP
            mcp_server_command=server_cmd,

        )