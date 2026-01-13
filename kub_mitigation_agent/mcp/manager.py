#!/usr/bin/env python3
"""
MCP Manager using LangChain MCP Adapters

Manages connections to MCP servers and provides tools to agents.
Uses langchain-mcp-adapters for robust MCP protocol support.

For more information, see:
- https://docs.langchain.com/oss/python/langchain/mcp
- https://github.com/rohitg00/kubectl-mcp-server
"""
import logging
from typing import Dict, Any, List, Optional
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.callbacks import Callbacks, CallbackContext
from mcp.types import LoggingMessageNotificationParams

logger = logging.getLogger(__name__)


class MCPManager:
    """
    Manages multiple MCP servers using LangChain adapters.
    
    Provides a unified interface for:
    - Kubectl operations (current)
    - Prometheus queries (future)
    - Other MCP-based tools (future)
    
    Features:
    - Automatic tool conversion to LangChain tools
    - Progress tracking for long-running operations
    - Logging from MCP servers
    - Error handling and retries
    """
    
    def __init__(
        self,
        server_configs: Dict[str, Any],
        enable_logging: bool = True,
        enable_progress: bool = True,
    ):
        """
        Initialize MCP manager with server configurations.
        
        Args:
            server_configs: Dictionary of server configurations
                Example:
                {
                    "kubectl": {
                        "transport": "stdio",
                        "command": "python",
                        "args": ["-m", "kubectl_mcp_tool.mcp_server"]
                    }
                }
            enable_logging: Whether to log messages from MCP servers
            enable_progress: Whether to track progress for long operations
        """
        self.server_configs = server_configs
        self.enable_logging = enable_logging
        self.enable_progress = enable_progress
        
        # Initialize callbacks
        callbacks = Callbacks()
        if enable_logging:
            callbacks.on_logging_message = self._handle_logging
        if enable_progress:
            callbacks.on_progress = self._handle_progress
        
        # Initialize MultiServerMCPClient
        self.client = MultiServerMCPClient(
            server_configs,
            callbacks=callbacks,
        )
        
        logger.info(f"Initialized MCP manager with servers: {list(server_configs.keys())}")
    
    async def get_tools(self) -> List[Any]:
        """
        Get all tools from connected MCP servers as LangChain tools.
        
        Returns:
            List of LangChain Tool objects that can be used with agents
        """
        tools = await self.client.get_tools()
        logger.info(f"Loaded {len(tools)} tools from MCP servers")
        return tools
    
    async def _handle_logging(
        self,
        params: LoggingMessageNotificationParams,
        context: CallbackContext,
    ):
        """
        Handle log messages from MCP servers.
        
        Args:
            params: Logging parameters from MCP server
            context: Context about which server sent the log
        """
        level_map = {
            "debug": logging.DEBUG,
            "info": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
            "critical": logging.CRITICAL,
        }
        
        log_level = level_map.get(params.level.lower(), logging.INFO)
        logger.log(
            log_level,
            f"[MCP:{context.server_name}] {params.data}"
        )
    
    async def _handle_progress(
        self,
        progress: float,
        total: Optional[float],
        message: Optional[str],
        context: CallbackContext,
    ):
        """
        Handle progress updates from MCP servers.
        
        Args:
            progress: Current progress value
            total: Total value (if known)
            message: Progress message
            context: Context about which tool is progressing
        """
        if total:
            percent = (progress / total * 100)
            tool_info = f" [{context.tool_name}]" if context.tool_name else ""
            logger.info(
                f"[MCP:{context.server_name}{tool_info}] Progress: {percent:.1f}% - {message or 'working...'}"
            )
        else:
            logger.info(
                f"[MCP:{context.server_name}] Progress: {progress} - {message or 'working...'}"
            )
    
    async def cleanup(self):
        """Clean up MCP client resources."""
        # MultiServerMCPClient handles cleanup automatically
        # This method is here for consistency with the previous API
        logger.info("MCP manager cleanup complete")
