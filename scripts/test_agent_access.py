#!/usr/bin/env python3
"""
Minimal script to validate the agent can access the cluster and metrics.
Assumes `agent.config.yaml` exists and required dependencies/env are set.
"""

import asyncio
import logging
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv


# Ensure project root is on PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")


from kub_mitigation_agent.agent.config import KubernetesAgentConfig
from kub_mitigation_agent.agent.agent import KubernetesAgent


if __name__ == "__main__":
    # Load config (assumes file exists)
    cfg_dict = yaml.safe_load((PROJECT_ROOT / "agent.config.yaml").read_text(encoding="utf-8"))
    cfg = KubernetesAgentConfig.from_yaml_dict(cfg_dict)

    # Minimal logging to surface progress
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("MCP command:", " ".join(cfg.mcp_server_command))

    # Minimal, read-only intent
    NAMESPACE = "app-iot-gateway"
    intent = (
        f"Retrieve CPU and RAM metrics for namespace '{NAMESPACE}' across 10m and 2m horizons. Report on the behaviour of the application in the last 2m vs the last 10m. "
    )

    async def _run():
        agent = KubernetesAgent(cfg)
        print("Initializing agent...")
        await asyncio.wait_for(agent.initialize(), timeout=30)
        print("Agent initialized. Running intent...")
        try:
            actions_taken, operational_summary = await asyncio.wait_for(agent.agent_loop(intent), timeout=cfg.agent_timeout or 120)
        finally:
            await agent.cleanup()
        print("actions:", len(actions_taken))
        if isinstance(operational_summary, dict):
            print("summary:", operational_summary.get("summary") or operational_summary)
        else:
            print("summary:", operational_summary)

    asyncio.run(_run())


