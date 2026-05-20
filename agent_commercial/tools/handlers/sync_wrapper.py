"""
Synchronous Wrapper for BMS Tool Handler
=========================================

Provides a synchronous interface for the async BMSToolHandler.
"""

import asyncio
import concurrent.futures
import logging
from typing import Dict, Any

from agent_commercial.tools.handlers.base import BMSToolHandler

logger = logging.getLogger("arvis.bms.tools.sync")


class BMSToolHandlerSync(BMSToolHandler):
    """
    Synchronous wrapper for BMSToolHandler.
    Used by the mode dispatcher for unified tool execution.
    """

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Synchronous tool execution — safe in both sync and async call sites."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # Already inside an event loop (e.g. called from sync code under uvicorn).
            # Offload to a fresh thread so asyncio.run() gets a clean loop.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self.execute(tool_name, args))
                return future.result(timeout=30)
        else:
            return asyncio.run(self.execute(tool_name, args))
