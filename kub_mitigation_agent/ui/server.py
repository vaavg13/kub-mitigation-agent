"""
FastAPI-based UI server for agent trace visualization.

Provides:
- REST API for current experiment state
- WebSocket endpoint for real-time trace streaming
- Static file serving for the frontend
"""

import asyncio
import json
import logging
import queue
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

from .events import trace_emitter, TraceEvent

logger = logging.getLogger(__name__)

# Path to static files
STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="KubMitigation Agent UI",
        description="Real-time visualization of Kubernetes mitigation agent traces",
        version="1.0.0"
    )
    
    # CORS for development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Mount static files
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    
    # Register routes
    register_routes(app)
    
    return app


def register_routes(app: FastAPI) -> None:
    """Register all API routes."""
    
    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve the main UI page."""
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return HTMLResponse("<h1>KubMitigation Agent UI</h1><p>Static files not found.</p>")
    
    @app.get("/api/live")
    async def get_live_experiment() -> Dict[str, Any]:
        """Get currently running experiment state."""
        current = trace_emitter.get_current_experiment()
        return {
            "current_experiment": current,
            "status": "running" if current else "idle"
        }
    
    @app.post("/api/event")
    async def receive_event(event_data: Dict[str, Any]) -> Dict[str, str]:
        """Receive events from the experiment runner (cross-process)."""
        try:
            event = TraceEvent(
                event_type=event_data.get("event_type", ""),
                experiment_id=event_data.get("experiment_id", ""),
                timestamp=event_data.get("timestamp", ""),
                data=event_data.get("data", {})
            )
            trace_emitter.emit(event)
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Failed to process event: {e}")
            return {"status": "error", "message": str(e)}
    
    @app.websocket("/ws/trace")
    async def websocket_trace(websocket: WebSocket):
        """WebSocket endpoint for real-time trace streaming."""
        await websocket.accept()
        logger.info("WebSocket client connected")
        
        # Subscribe to events
        event_queue = trace_emitter.subscribe()
        
        try:
            # Send current state on connect
            current = trace_emitter.get_current_experiment()
            if current:
                await websocket.send_json({
                    "type": "init",
                    "experiment": current
                })
            else:
                await websocket.send_json({
                    "type": "init",
                    "experiment": None,
                    "message": "Waiting for experiment to start..."
                })
            
            # Stream events from the thread-safe queue
            while True:
                try:
                    # Poll the queue with timeout to allow heartbeats
                    try:
                        event: TraceEvent = event_queue.get(timeout=0.1)
                        await websocket.send_json({
                            "type": "event",
                            "event": event.to_dict()
                        })
                    except queue.Empty:
                        pass
                    
                    # Send heartbeat every few seconds
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    if "WebSocket" in str(type(e).__name__):
                        break
                    logger.error(f"Error in event loop: {e}")
                    
        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            trace_emitter.unsubscribe(event_queue)
    
    @app.get("/api/health")
    async def health_check() -> Dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok"}


class UIServer:
    """
    UI Server that runs in a subprocess to avoid gevent/asyncio conflicts.
    
    Designed to run alongside the experiment runner in the same process.
    """
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8888):
        self.host = host
        self.port = port
        self._process: Optional[subprocess.Popen] = None
        
    def start(self) -> None:
        """Start the server in a subprocess."""
        if self._process and self._process.poll() is None:
            logger.warning("Server already running")
            return
        
        # Start uvicorn as a subprocess to avoid gevent conflicts
        import sys
        import time
        
        cmd = [
            sys.executable, "-m", "uvicorn",
            "kub_mitigation_agent.ui.server:create_app",
            "--factory",
            "--host", self.host,
            "--port", str(self.port),
            "--log-level", "warning",
            "--no-access-log"
        ]
        
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Configure event forwarding to this server
        from .events import set_remote_server
        server_url = f"http://127.0.0.1:{self.port}"
        set_remote_server(server_url)
        
        # Wait for server to be ready
        time.sleep(1)
        
        print(f"\n{'='*60}")
        print(f"🚀 Agent UI Server started")
        print(f"   Open: http://localhost:{self.port}")
        print(f"{'='*60}\n")
    
    def stop(self) -> None:
        """Stop the server subprocess."""
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
    
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._process is not None and self._process.poll() is None


# Global server instance for easy access
_ui_server: Optional[UIServer] = None


def start_ui_server(host: str = "0.0.0.0", port: int = 8888) -> UIServer:
    """Start the UI server in a subprocess."""
    global _ui_server
    if _ui_server is None:
        _ui_server = UIServer(host=host, port=port)
    _ui_server.start()
    return _ui_server


def run_server(
    host: str = "0.0.0.0",
    port: int = 8888,
    logs_dir: str = "DATASET_LOGS",
    reload: bool = False
) -> None:
    """
    Run the UI server in foreground (blocking).
    
    This is for standalone usage, not for integration with experiments.
    """
    import uvicorn
    
    app = create_app()
    
    print(f"\n{'='*60}")
    print(f"🚀 KubMitigation Agent UI Server")
    print(f"{'='*60}")
    print(f"  URL: http://{host}:{port}")
    print(f"  WebSocket: ws://{host}:{port}/ws/trace")
    print(f"{'='*60}\n")
    
    uvicorn.run(app, host=host, port=port, reload=reload)


if __name__ == "__main__":
    run_server()
