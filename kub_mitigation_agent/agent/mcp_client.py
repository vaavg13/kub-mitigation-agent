#!/usr/bin/env python3
import asyncio
import json
from typing import Any, Dict, Optional

class MCPClient:
    def __init__(self, server_command: list, response_timeout_seconds: int = 60):
        self.server_command = server_command
        self.process: Optional[asyncio.subprocess.Process] = None
        self.request_id = 1
        self._send_lock = asyncio.Lock()
        self._stderr_task: Optional[asyncio.Task] = None
        self.response_timeout_seconds = response_timeout_seconds

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(
            *self.server_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        # Drain stderr continuously to avoid blocking due to pipe backpressure
        async def _drain_stderr(reader: asyncio.StreamReader):
            try:
                while True:
                    line = await reader.readline()
                    if not line:
                        break
                    # Intentionally ignore or log elsewhere if needed
                    # Using print avoids tight coupling with logging setup here
                    # but keeps the pipe drained.
                    try:
                        print(f"[MCP-STDERR] {line.decode(errors='replace').rstrip()}")
                    except Exception:
                        pass
            except Exception:
                # Silently exit on any errors; goal is just to keep the pipe drained
                pass

        if self.process and self.process.stderr:
            self._stderr_task = asyncio.create_task(_drain_stderr(self.process.stderr))

    async def send_request(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params or {}
        }
        self.request_id += 1
        # Serialize writes and reads to avoid interleaving between concurrent tool calls
        async with self._send_lock:
            request_json = json.dumps(request) + "\n"
            if not self.process or not self.process.stdin or not self.process.stdout:
                raise RuntimeError("MCP server process is not started")

            self.process.stdin.write(request_json.encode())
            await self.process.stdin.drain()

        # Read response handling large kubectl outputs
        # The default asyncio StreamReader limit (~64KB) is too small for large cluster outputs
        chunks = []
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.process.stdout.readuntil(b'\n'),
                        timeout=self.response_timeout_seconds
                    )
                    chunks.append(chunk)
                    break
                except asyncio.LimitOverrunError as e:
                    # Response exceeded buffer limit - read consumed bytes and continue
                    # This happens when kubectl returns many resources (pods, events, etc.)
                    chunk = await self.process.stdout.read(e.consumed)
                    chunks.append(chunk)
                    # Continue reading until we find the newline
        except asyncio.TimeoutError:
            raise RuntimeError(f"MCP server did not respond within {self.response_timeout_seconds} seconds")
        
        response_line = b''.join(chunks)
        if not response_line:
            raise RuntimeError("MCP server closed connection")
        
        return json.loads(response_line.decode().strip())

    async def initialize(self):
        return await self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"}
        })

    async def call_tool(self, name: str, arguments: Dict[str, Any]):
        return await self.send_request("tools/call", {
            "name": name,
            "arguments": arguments
        })

    async def stop(self):
        if self.process:
            try:
                # Close stdin first to signal the process to exit gracefully
                if self.process.stdin:
                    self.process.stdin.close()
                    await self.process.stdin.wait_closed()
                # Cancel stderr draining task if running
                if self._stderr_task:
                    self._stderr_task.cancel()
                    try:
                        await self._stderr_task
                    except Exception:
                        pass
                
                # Wait for process to exit gracefully first
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=2)
                except asyncio.TimeoutError:
                    # If it doesn't exit gracefully, terminate it
                    self.process.terminate()
                    try:
                        await asyncio.wait_for(self.process.wait(), timeout=3)
                    except asyncio.TimeoutError:
                        # Last resort: force kill
                        self.process.kill()
                        await self.process.wait()
            except Exception:
                # If anything fails during cleanup, just ignore it
                # This prevents the "event loop is closed" error
                pass