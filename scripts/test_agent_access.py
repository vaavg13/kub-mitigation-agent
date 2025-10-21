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
    cfg_dict = yaml.safe_load((PROJECT_ROOT / "experiment_configs" / "agent.config.yaml").read_text(encoding="utf-8"))
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
        print(f"Timeout: {cfg.agent_timeout}s")
        
        try:
            actions_taken, operational_summary = await asyncio.wait_for(
                agent.agent_loop(intent), 
                timeout=cfg.agent_timeout
            )
        except asyncio.TimeoutError:
            print(f"\n❌ TIMEOUT: Agent exceeded {cfg.agent_timeout}s. Increase timeout in config or use faster model.")
            return
        finally:
            await agent.cleanup()
            
        print(f"\n✓ Completed: {len(actions_taken)} actions")
        if isinstance(operational_summary, dict):
            status = operational_summary.get("status", "N/A")
            success = "✓" if operational_summary.get("success") else "✗"
            print(f"{success} Status: {status}")
        else:
            print("summary:", operational_summary)

    asyncio.run(_run())


