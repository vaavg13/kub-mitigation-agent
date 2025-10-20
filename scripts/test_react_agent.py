#!/usr/bin/env python3
"""
Test script for ReAct Agent.
Validates the simplified agent can access the cluster and metrics.
"""

import asyncio
import json
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
from kub_mitigation_agent.agent.react_agent import ReactAgent


if __name__ == "__main__":
    # Load config (assumes file exists)
    cfg_dict = yaml.safe_load((PROJECT_ROOT / "agent.config.yaml").read_text(encoding="utf-8"))
    cfg = KubernetesAgentConfig.from_yaml_dict(cfg_dict)

    # Minimal logging to surface progress
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("MCP command:", " ".join(cfg.mcp_server_command))
    
    # Test intent - diagnose performance issue
    NAMESPACE = "app-iot-gateway"
    intent = (
        f"Diagnose and resolve any performance degradation in namespace '{NAMESPACE}'. "
        f"Check latency, CPU, and memory metrics. If issues are found, take corrective action."
    )

    async def _run():
        agent = ReactAgent(cfg)
        print("Initializing ReAct agent...")
        await asyncio.wait_for(agent.initialize(), timeout=30)
        print("ReAct agent initialized. Running mission...")
        
        try:
            actions_taken, operational_summary = await asyncio.wait_for(
                agent.agent_loop(intent), 
                timeout=cfg.agent_timeout or 120
            )
        finally:
            await agent.cleanup()
        
        logger.info(f"Actions taken: {len(actions_taken)}")
        logger.info(f"Operational summary:\n{json.dumps(operational_summary, indent=2)}")
        
        return actions_taken, operational_summary

    asyncio.run(_run())

