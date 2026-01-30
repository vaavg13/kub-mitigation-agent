"""
UI Server for Agent Trace Visualization.

This module provides a web-based interface for viewing agent execution traces
with real-time streaming during experiment runs.
"""

from .server import create_app, run_server, start_ui_server, UIServer
from .events import TraceEventEmitter, trace_emitter, set_remote_server

__all__ = [
    "create_app", 
    "run_server", 
    "start_ui_server",
    "UIServer",
    "TraceEventEmitter", 
    "trace_emitter",
    "set_remote_server"
]
