"""
Centralized logging configuration for kub_mitigation_agent.

This module provides a simple, consistent logging setup across the entire application.
Logging is used primarily for agent execution tracking, while experiments use print() 
for user-facing progress output.
"""
import logging
import os

from kub_mitigation_agent.agent.agent_formatter import setup_agent_logging


def setup_logging():
    """
    Configure logging for the application with a clean, minimal format.
    
    - Format: [LEVEL] message
    - Default level: INFO (can be overridden with LOG_LEVEL env var)
    - Suppresses noisy third-party libraries (httpx, httpcore, etc.)
    """
    # Get log level from environment, default to INFO
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, log_level, logging.INFO)
    
    # Remove any existing handlers to avoid conflicts
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Configure root logger with clean, minimal format
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
    
    # Ensure our package loggers inherit the configuration
    logging.getLogger("kub_mitigation_agent").setLevel(level)
    
    # Suppress noisy third-party libraries
    noisy_libs = ["httpx", "httpcore", "urllib3"]
    for lib in noisy_libs:
        logging.getLogger(lib).setLevel(logging.WARNING)
    
    # Setup colorized agent logging
    setup_agent_logging("kub_mitigation_agent.agent.react_agent")



