#!/usr/bin/env python3
"""
Agent Output Formatter
Provides colorized, pretty-printed logging for agent thoughts, actions, and observations.
"""
import json
import logging
import re


class AgentLogFormatter(logging.Formatter):
    """
    Custom formatter that colorizes and prettifies agent output.
    
    Features:
    - Different colors for THOUGHT, ACTION, OBSERVATION
    - Line spacing between log entries
    - Pretty printing for JSON/dict content
    """
    
    def __init__(self, show_observations: bool = True):
        super().__init__()
        self.show_observations = show_observations

    # ANSI color codes
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    
    # Colors for different log types
    THOUGHT_COLOR = '\033[36m'      # Cyan
    ACTION_COLOR = '\033[33m'       # Yellow
    OBSERVATION_COLOR = '\033[32m'  # Green
    INFO_COLOR = '\033[37m'         # White/Default
    WARNING_COLOR = '\033[35m'      # Magenta
    ERROR_COLOR = '\033[31m'        # Red
    
    # Prefix styles
    THOUGHT_PREFIX = f"{BOLD}{THOUGHT_COLOR}💭 THOUGHT:{RESET}{THOUGHT_COLOR}"
    ACTION_PREFIX = f"{BOLD}{ACTION_COLOR}⚡ ACTION:{RESET}{ACTION_COLOR}"
    OBSERVATION_PREFIX = f"{BOLD}{OBSERVATION_COLOR}👁  OBSERVATION:{RESET}{OBSERVATION_COLOR}"
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors and pretty printing."""
        message = record.getMessage()
        
        # Add spacing before agent thinking rounds
        if "Agent thinking (round" in message:
            round_num = re.search(r'round (\d+)', message)
            round_str = round_num.group(1) if round_num else "?"
            return f"\n{self.BOLD}{self.DIM}{'=' * 60}{self.RESET}\n{self.BOLD}🤖 Agent Round {round_str}{self.RESET}\n{self.DIM}{'=' * 60}{self.RESET}"
        
        # Handle THOUGHT messages
        if message.startswith("THOUGHT:"):
            content = message[8:].strip()
            if content == "(none)" or not content:
                return f"{self.THOUGHT_PREFIX} {self.DIM}(none){self.RESET}\n"
            return f"{self.THOUGHT_PREFIX}\n  {content}{self.RESET}\n"
        
        # Handle ACTION messages
        if message.startswith("ACTION:"):
            content = message[7:].strip()
            # Try to prettify if it contains JSON args
            formatted_content = self._format_action(content)
            return f"{self.ACTION_PREFIX}\n  {formatted_content}{self.RESET}\n"
        
        # Handle OBSERVATION messages
        if message.startswith("OBSERVATION:"):
            if not self.show_observations:
                return f"{self.OBSERVATION_PREFIX} {self.DIM}(hidden){self.RESET}\n"
            content = message[12:].strip()
            formatted_content = self._format_observation(content)
            return f"{self.OBSERVATION_PREFIX}\n{formatted_content}{self.RESET}\n"
        
        # Handle other special messages
        if "Operation completed:" in message:
            return f"\n{self.BOLD}{self.INFO_COLOR}✓ {message}{self.RESET}\n"
        
        if "PROBLEM LOCATION:" in message:
            content = message.split("PROBLEM LOCATION:", 1)[1].strip()
            formatted = self._prettify_json(content, indent=2)
            return f"{self.BOLD}{self.WARNING_COLOR}📍 PROBLEM LOCATION:{self.RESET}\n{formatted}\n"
        
        if message.startswith("AGENT CREATED ACTION PLAN"):
            return f"\n{self.BOLD}{self.INFO_COLOR}📋 {message}{self.RESET}"
        
        # Handle action plan display
        if "📝 Action Plan:" in message:
            # This is already formatted, just colorize it
            lines = message.split('\n')
            colored_lines = []
            for line in lines:
                if line.startswith("📝"):
                    colored_lines.append(f"{self.BOLD}{self.INFO_COLOR}{line}{self.RESET}")
                else:
                    colored_lines.append(f"{self.INFO_COLOR}{line}{self.RESET}")
            return '\n'.join(colored_lines) + '\n'
        
        # Default formatting for other messages
        if record.levelno >= logging.ERROR:
            return f"{self.ERROR_COLOR}{message}{self.RESET}"
        elif record.levelno >= logging.WARNING:
            return f"{self.WARNING_COLOR}{message}{self.RESET}"
        else:
            return f"{self.INFO_COLOR}{message}{self.RESET}"
    
    def _format_action(self, content: str) -> str:
        """Format action content, prettifying JSON args if present."""
        # Pattern: function_name({...json...})
        match = re.match(r'([a-zA-Z_][a-zA-Z0-9_]*)\((.*)\)$', content)
        if match:
            func_name = match.group(1)
            args_str = match.group(2)
            try:
                args = json.loads(args_str)
                pretty_args = json.dumps(args, indent=2)
                # Indent the args
                indented_args = '\n    '.join(pretty_args.split('\n'))
                return f"{self.BOLD}{func_name}{self.RESET}(\n    {indented_args}\n  )"
            except (json.JSONDecodeError, ValueError):
                pass
        
        return content
    
    def _format_observation(self, content: str) -> str:
        """Format observation content with pretty JSON."""
        formatted = self._prettify_json(content, indent=2)
        # Indent all lines
        lines = formatted.split('\n')
        indented = '\n  '.join(lines)
        return f"  {indented}"
    
    def _prettify_json(self, content: str, indent: int = 2) -> str:
        """Attempt to parse and prettify JSON content."""
        try:
            data = json.loads(content)
            return json.dumps(data, indent=indent, sort_keys=False)
        except (json.JSONDecodeError, ValueError, TypeError):
            return content


def setup_agent_logging(logger_name: str = "kub_mitigation_agent.agent.react_agent", show_observations: bool = True):
    """
    Setup colorized logging for the agent.
    
    Args:
        logger_name: Name of the logger to configure (default: react_agent logger)
        show_observations: Whether to show observation details
    """
    agent_logger = logging.getLogger(logger_name)
    
    # Remove existing handlers to avoid duplicates
    agent_logger.handlers.clear()
    
    # Create console handler with custom formatter
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(AgentLogFormatter(show_observations=show_observations))
    agent_logger.addHandler(console_handler)
    
    # Prevent propagation to avoid duplicate logs
    agent_logger.propagate = False
    
    return agent_logger

