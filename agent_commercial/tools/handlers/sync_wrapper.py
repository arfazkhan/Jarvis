"""
Synchronous Wrapper for BMS Tool Handler
=========================================

Provides a synchronous interface for the async BMSToolHandler.
"""

import asyncio
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
        """Synchronous tool execution for mode dispatcher"""
        
        # Get or create event loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If already in async context, just run directly
                try:
                    import nest_asyncio
                    nest_asyncio.apply()
                    return loop.run_until_complete(self.execute(tool_name, args))
                except ImportError:
                    # nest_asyncio not available, create new loop
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    return new_loop.run_until_complete(self.execute(tool_name, args))
            else:
                return loop.run_until_complete(self.execute(tool_name, args))
        except RuntimeError:
            # No event loop, create one
            return asyncio.run(self.execute(tool_name, args))
