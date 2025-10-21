import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import KubernetesAgentConfig
from .agent import KubernetesAgent

app = FastAPI()


class RunRequest(BaseModel):
    intent: str
    snapshot: Dict[str, Any] = {}
    timeout_seconds: int | None = None


class JobStatus(BaseModel):
    job_id: str
    status: str  # queued | running | succeeded | failed | timeout | cancelled
    started_at: str | None = None
    updated_at: str | None = None
    duration_seconds: float | None = None
    exit_code: int | None = None
    error: str | None = None


jobs: Dict[str, Dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now().isoformat()


async def _run_job(job_id: str, payload: RunRequest):
    jobs[job_id]["status"] = "running"
    jobs[job_id]["started_at"] = _now_iso()
    jobs[job_id]["updated_at"] = jobs[job_id]["started_at"]

    # Load YAML config via KubernetesAgentConfig defaults to env unless provided; we use YAML file
    # The experiment config location is relative to repo root
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    agent_yaml_path = repo_root / "experiment_configs" / "agent.config.yaml"
    try:
        cfg_dict = json.loads(agent_yaml_path.read_text(encoding="utf-8").encode("utf-8").decode("utf-8"))
    except Exception:
        import yaml  # lazy import to avoid hard dep here if not needed elsewhere
        cfg_dict = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8"))
    agent_cfg = KubernetesAgentConfig.from_yaml_dict(cfg_dict)

    timeout = payload.timeout_seconds or agent_cfg.agent_timeout

    agent = KubernetesAgent(config=agent_cfg)
    start_ts = datetime.now().timestamp()
    try:
        await agent.initialize()
        actions_taken, operational_summary = await asyncio.wait_for(
            agent.agent_loop(payload.intent, payload.snapshot), timeout=timeout
        )
        duration = datetime.now().timestamp() - start_ts
        jobs[job_id].update(
            {
                "status": "succeeded",
                "updated_at": _now_iso(),
                "duration_seconds": duration,
                "result": {
                    "actions_taken": actions_taken,
                    "operational_summary": operational_summary,
                    "duration_seconds": duration,
                },
                "exit_code": 0,
            }
        )
    except asyncio.TimeoutError:
        duration = datetime.now().timestamp() - start_ts
        jobs[job_id].update(
            {
                "status": "timeout",
                "updated_at": _now_iso(),
                "duration_seconds": duration,
                "exit_code": 124,
                "error": f"agent timed out after {timeout}s",
            }
        )
    except Exception as e:
        duration = datetime.now().timestamp() - start_ts
        jobs[job_id].update(
            {
                "status": "failed",
                "updated_at": _now_iso(),
                "duration_seconds": duration,
                "exit_code": 1,
                "error": str(e),
            }
        )
    finally:
        try:
            await agent.cleanup()
        except Exception:
            pass


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.post("/agents/run")
async def run_agent(req: RunRequest):
    job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    jobs[job_id] = {
        "status": "queued",
        "started_at": None,
        "updated_at": _now_iso(),
        "result": None,
        "exit_code": None,
        "error": None,
    }
    asyncio.create_task(_run_job(job_id, req))
    return {"job_id": job_id, "status": "queued"}


@app.get("/agents/{job_id}/status")
async def agent_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="unknown job")
    j = jobs[job_id]
    return JobStatus(
        job_id=job_id,
        status=j.get("status"),
        started_at=j.get("started_at"),
        updated_at=j.get("updated_at"),
        duration_seconds=j.get("duration_seconds"),
        exit_code=j.get("exit_code"),
        error=j.get("error"),
    )


@app.get("/agents/{job_id}/result")
async def agent_result(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="unknown job")
    j = jobs[job_id]
    if j.get("status") not in {"succeeded", "failed", "timeout", "cancelled"}:
        raise HTTPException(status_code=409, detail="job not completed")
    return j.get("result") or {"error": j.get("error")}


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("AGENT_SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("AGENT_SERVER_PORT", "8765"))
    uvicorn.run("kub_mitigation_agent.agent.agent_server:app", host=host, port=port, log_level="info", reload=False)