"""
Event emitter for real-time trace streaming.

This module provides an event bus that can be used to emit agent trace
updates during experiment execution, which are then broadcast to connected
WebSocket clients.

Supports both in-process emission and cross-process HTTP forwarding.
"""

import json
import logging
import threading
import queue
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Global configuration for remote server
_REMOTE_SERVER_URL: Optional[str] = None


def set_remote_server(url: str) -> None:
    """Configure events to be forwarded to a remote server."""
    global _REMOTE_SERVER_URL
    _REMOTE_SERVER_URL = url
    logger.info(f"Events will be forwarded to: {url}")


@dataclass
class TraceEvent:
    """A trace event that can be emitted and broadcast."""
    event_type: str  # "experiment_start", "step", "experiment_end", "phase"
    experiment_id: str
    timestamp: str
    data: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


@dataclass
class ExperimentState:
    """Tracks the current state of an experiment for the UI."""
    id: str
    started_at: str
    status: str = "running"
    config: Dict[str, Any] = field(default_factory=dict)
    phases: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    completed_at: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TraceEventEmitter:
    """
    Thread-safe event emitter for broadcasting trace events.
    
    Supports two modes:
    1. In-process: Uses thread-safe queues for local subscribers
    2. Remote: Forwards events to a remote server via HTTP
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: List[queue.Queue] = []
        self._current_experiment: Optional[ExperimentState] = None
        self._events_history: List[TraceEvent] = []
        self._max_history = 1000
        
    def subscribe(self) -> queue.Queue:
        """Subscribe to trace events. Returns a thread-safe queue."""
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(q)
            logger.info(f"New subscriber, total: {len(self._subscribers)}")
        return q
    
    def unsubscribe(self, q: queue.Queue) -> None:
        """Unsubscribe from trace events."""
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)
            logger.info(f"Unsubscribed, remaining: {len(self._subscribers)}")
    
    def emit(self, event: TraceEvent) -> None:
        """Emit an event to all subscribers (thread-safe)."""
        # If remote server configured, forward via HTTP
        if _REMOTE_SERVER_URL:
            self._forward_to_remote(event)
            return
        
        # Local emission
        with self._lock:
            # Update internal state
            self._update_experiment_state(event)
            
            # Store in history
            self._events_history.append(event)
            if len(self._events_history) > self._max_history:
                self._events_history = self._events_history[-self._max_history:]
            
            # Broadcast to all subscribers
            dead_queues = []
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    dead_queues.append(q)
            
            # Remove dead queues
            for q in dead_queues:
                self._subscribers.remove(q)
                
            logger.debug(f"Emitted {event.event_type} to {len(self._subscribers)} subscribers")
    
    def _forward_to_remote(self, event: TraceEvent) -> None:
        """Forward event to remote server via HTTP POST."""
        try:
            data = json.dumps(event.to_dict(), default=str).encode('utf-8')
            req = urllib.request.Request(
                f"{_REMOTE_SERVER_URL}/api/event",
                data=data,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=2) as response:
                pass  # Just check it succeeded
        except urllib.error.URLError as e:
            logger.debug(f"Failed to forward event: {e}")
        except Exception as e:
            logger.debug(f"Error forwarding event: {e}")
    
    def _update_experiment_state(self, event: TraceEvent) -> None:
        """Track experiment state internally (called within lock)."""
        exp_id = event.experiment_id
        
        if event.event_type == "experiment_start":
            self._current_experiment = ExperimentState(
                id=exp_id,
                started_at=event.timestamp,
                config=event.data.get("config", {})
            )
        elif self._current_experiment and self._current_experiment.id == exp_id:
            if event.event_type == "phase":
                self._current_experiment.phases.append(event.data)
            elif event.event_type == "step":
                self._current_experiment.steps.append(event.data)
            elif event.event_type == "experiment_end":
                self._current_experiment.completed_at = event.timestamp
                self._current_experiment.status = event.data.get("status", "completed")
                self._current_experiment.summary = event.data.get("summary")
    
    def get_current_experiment(self) -> Optional[Dict[str, Any]]:
        """Get the current running experiment data."""
        with self._lock:
            if self._current_experiment:
                return self._current_experiment.to_dict()
        return None
    
    def clear(self) -> None:
        """Clear all tracked experiment data."""
        with self._lock:
            self._current_experiment = None
            self._events_history.clear()


# Global singleton instance
trace_emitter = TraceEventEmitter()


# Helper functions for common event types
def emit_experiment_start(experiment_id: str, config: Dict[str, Any]) -> None:
    """Emit experiment start event."""
    event = TraceEvent(
        event_type="experiment_start",
        experiment_id=experiment_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        data={"config": config}
    )
    trace_emitter.emit(event)
    logger.info(f"Experiment started: {experiment_id}")


def emit_phase(experiment_id: str, phase_name: str, status: str, metrics: Optional[Dict[str, Any]] = None) -> None:
    """Emit phase event."""
    event = TraceEvent(
        event_type="phase",
        experiment_id=experiment_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        data={
            "phase": phase_name,
            "status": status,
            "metrics": metrics or {}
        }
    )
    trace_emitter.emit(event)
    logger.info(f"Phase {phase_name}: {status}")


def emit_agent_step(
    experiment_id: str,
    step_number: int,
    thought: Optional[str],
    actions: List[Dict[str, Any]],
    observations: List[Any]
) -> None:
    """Emit agent step event."""
    # Serialize observations safely
    safe_observations = []
    for obs in observations:
        try:
            # Test if it's JSON serializable
            json.dumps(obs, default=str)
            safe_observations.append(obs)
        except (TypeError, ValueError):
            safe_observations.append(str(obs))
    
    event = TraceEvent(
        event_type="step",
        experiment_id=experiment_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        data={
            "step_number": step_number,
            "thought": thought,
            "actions": actions,
            "observations": safe_observations
        }
    )
    trace_emitter.emit(event)
    logger.info(f"Agent step {step_number}: {[a.get('name') for a in actions]}")


def emit_experiment_end(experiment_id: str, status: str, summary: Optional[Dict[str, Any]] = None) -> None:
    """Emit experiment end event."""
    event = TraceEvent(
        event_type="experiment_end",
        experiment_id=experiment_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        data={"status": status, "summary": summary}
    )
    trace_emitter.emit(event)
    logger.info(f"Experiment ended: {experiment_id} - {status}")
