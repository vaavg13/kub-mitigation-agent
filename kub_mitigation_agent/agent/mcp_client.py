#!/usr/bin/env python3
import asyncio
import json
from typing import Any, Dict

class MCPClient:
    def __init__(self, server_command: list):
        self.server_command = server_command
        self.process = None
        self.request_id = 1

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(
            *self.server_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

    async def send_request(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params or {}
        }
        self.request_id += 1
        
        request_json = json.dumps(request) + "\n"
        self.process.stdin.write(request_json.encode())
        await self.process.stdin.drain()
        
        response_line = await self.process.stdout.readline()
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