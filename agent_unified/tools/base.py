"""
ARVIS Base Tool (Production-Ready)
===================================

Enhanced base tool infrastructure with:
- Pydantic input validation
- Execution timeouts
- Retry logic with exponential backoff
- Result caching for read operations
- Structured logging with correlation IDs
- Health checks
"""

import asyncio
import functools
import hashlib
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union

from pydantic import BaseModel, Field, PrivateAttr


logger = logging.getLogger("arvis.unified.tools")


# Type for tool execution functions
T = TypeVar('T')


class ToolResult(BaseModel):
    """
    Standardized result from tool execution.
    
    Attributes:
        output: Successful output (JSON string)
        error: Error message if failed
        base64_image: Optional base64 image data
        cached: Whether result was retrieved from cache
        execution_time_ms: Time taken to execute
        correlation_id: Request tracking ID
    """
    output: Optional[str] = None
    error: Optional[str] = None
    base64_image: Optional[str] = None
    cached: bool = False
    execution_time_ms: int = 0
    correlation_id: Optional[str] = None
    
    @property
    def success(self) -> bool:
        return self.error is None
    
    def __str__(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        return self.output or ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "output": self.output,
            "error": self.error,
            "cached": self.cached,
            "execution_time_ms": self.execution_time_ms,
            "correlation_id": self.correlation_id
        }


class ToolConfig(BaseModel):
    """Configuration for tool execution behavior."""
    
    # Timeout settings
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    
    # Retry settings
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_delay_ms: int = Field(default=1000, ge=100)
    retry_backoff_multiplier: float = Field(default=2.0, ge=1.0, le=5.0)
    retryable_exceptions: List[str] = Field(default_factory=lambda: [
        "TimeoutError", "ConnectionError", "OSError"
    ])
    
    # Caching settings
    enable_cache: bool = False
    cache_ttl_seconds: int = Field(default=60, ge=0)
    
    # Rate limiting
    rate_limit_calls: int = Field(default=0, ge=0)  # 0 = no limit
    rate_limit_period_seconds: int = Field(default=60, ge=1)


class CacheEntry(BaseModel):
    """Cached tool result entry."""
    result: ToolResult
    cached_at: datetime
    ttl_seconds: int
    
    def is_expired(self) -> bool:
        if self.ttl_seconds <= 0:
            return True
        return datetime.now() > self.cached_at + timedelta(seconds=self.ttl_seconds)


class ToolMetrics(BaseModel):
    """Runtime metrics for a tool."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    cache_hits: int = 0
    total_execution_time_ms: int = 0
    last_called: Optional[datetime] = None
    last_error: Optional[str] = None
    
    @property
    def avg_execution_time_ms(self) -> float:
        if self.total_calls == 0:
            return 0
        return self.total_execution_time_ms / self.total_calls
    
    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 0
        return self.successful_calls / self.total_calls


class BaseTool(ABC, BaseModel):
    """
    Production-ready base class for all tools.
    
    Features:
    - Pydantic validation for inputs
    - Automatic timeout enforcement
    - Retry with exponential backoff
    - Result caching
    - Execution metrics
    - Health checks
    """
    
    name: str = Field(..., description="Unique tool name")
    description: str = Field(..., description="Tool description for LLM")
    parameters: dict = Field(default_factory=dict, description="JSON Schema for parameters")
    
    # Configuration
    config: ToolConfig = Field(default_factory=ToolConfig)
    
    # Runtime state using PrivateAttr (Pydantic V2)
    _cache: Dict[str, CacheEntry] = PrivateAttr(default_factory=dict)
    _metrics: ToolMetrics = PrivateAttr(default_factory=ToolMetrics)
    _rate_limit_calls: List[float] = PrivateAttr(default_factory=list)
    _correlation_id: Optional[str] = PrivateAttr(default=None)
    
    model_config = {"arbitrary_types_allowed": True}
    
    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute the tool logic.
        
        Override this method in subclasses.
        This will be automatically wrapped with timeout, retry, and caching.
        """
        pass
    
    async def __call__(self, **kwargs) -> ToolResult:
        """
        Main entry point for tool execution.
        
        Applies all production features:
        1. Validate inputs
        2. Check rate limits
        3. Check cache
        4. Execute with timeout and retry
        5. Update metrics
        """
        correlation_id = str(uuid.uuid4())[:8]
        self._correlation_id = correlation_id
        start_time = time.time()
        
        logger.info(f"[{self.name}:{correlation_id}] Executing with args: {self._safe_log_args(kwargs)}")
        
        try:
            # 1. Validate inputs
            validation_error = self._validate_inputs(kwargs)
            if validation_error:
                execution_time = int((time.time() - start_time) * 1000)
                self._update_metrics(False, execution_time, validation_error)
                return self._make_result(error=validation_error, correlation_id=correlation_id, execution_time_ms=execution_time)
            
            # 2. Check rate limits
            if not self._check_rate_limit():
                execution_time = int((time.time() - start_time) * 1000)
                rate_error = f"Rate limit exceeded ({self.config.rate_limit_calls} calls per {self.config.rate_limit_period_seconds}s)"
                self._update_metrics(False, execution_time, rate_error)
                return self._make_result(
                    error=rate_error,
                    correlation_id=correlation_id,
                    execution_time_ms=execution_time
                )
            
            # 3. Check cache
            if self.config.enable_cache:
                cache_key = self._get_cache_key(kwargs)
                cached = self._get_from_cache(cache_key)
                if cached:
                    cached.correlation_id = correlation_id
                    cached.cached = True
                    self._metrics.cache_hits += 1
                    logger.info(f"[{self.name}:{correlation_id}] Cache hit")
                    return cached
            
            # 4. Execute with timeout and retry
            result = await self._execute_with_retry(correlation_id, **kwargs)
            
            # 5. Cache successful results
            if result.success and self.config.enable_cache:
                self._add_to_cache(cache_key, result)
            
            # 6. Update metrics
            execution_time = int((time.time() - start_time) * 1000)
            result.execution_time_ms = execution_time
            result.correlation_id = correlation_id
            
            self._update_metrics(result.success, execution_time, result.error)
            
            return result
            
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            logger.error(f"[{self.name}:{correlation_id}] Unhandled error: {e}")
            self._update_metrics(False, execution_time, str(e))
            return self._make_result(
                error=f"Tool execution failed: {str(e)}",
                correlation_id=correlation_id,
                execution_time_ms=execution_time
            )
    
    async def _execute_with_retry(self, correlation_id: str, **kwargs) -> ToolResult:
        """Execute with timeout and retry logic."""
        last_error = None
        
        for attempt in range(self.config.max_retries + 1):
            try:
                # Apply timeout
                result = await asyncio.wait_for(
                    self.execute(**kwargs),
                    timeout=self.config.timeout_seconds
                )
                return result
                
            except asyncio.TimeoutError:
                last_error = f"Execution timed out after {self.config.timeout_seconds}s"
                logger.warning(f"[{self.name}:{correlation_id}] Timeout on attempt {attempt + 1}")
                
            except Exception as e:
                last_error = str(e)
                exception_type = type(e).__name__
                
                # Check if exception is retryable
                if exception_type not in self.config.retryable_exceptions:
                    logger.error(f"[{self.name}:{correlation_id}] Non-retryable error: {e}")
                    return self._make_result(error=last_error, correlation_id=correlation_id)
                
                logger.warning(f"[{self.name}:{correlation_id}] Retryable error on attempt {attempt + 1}: {e}")
            
            # Wait before retry (with exponential backoff)
            if attempt < self.config.max_retries:
                delay = self.config.retry_delay_ms * (self.config.retry_backoff_multiplier ** attempt) / 1000
                await asyncio.sleep(delay)
        
        return self._make_result(
            error=f"Failed after {self.config.max_retries + 1} attempts: {last_error}",
            correlation_id=correlation_id
        )
    
    def _validate_inputs(self, kwargs: Dict[str, Any]) -> Optional[str]:
        """Validate inputs against JSON schema."""
        params = self.parameters
        if not params or "properties" not in params:
            return None
        
        properties = params.get("properties", {})
        required = params.get("required", [])
        
        # Check required parameters
        for req in required:
            if req not in kwargs or kwargs[req] is None:
                return f"Missing required parameter: {req}"
        
        # Type validation for provided parameters
        for key, value in kwargs.items():
            if key not in properties:
                continue  # Allow extra params
            
            prop = properties[key]
            expected_type = prop.get("type")
            
            if value is None:
                continue
            
            if expected_type == "string" and not isinstance(value, str):
                return f"Parameter '{key}' must be a string"
            elif expected_type == "integer" and not isinstance(value, int):
                return f"Parameter '{key}' must be an integer"
            elif expected_type == "number" and not isinstance(value, (int, float)):
                return f"Parameter '{key}' must be a number"
            elif expected_type == "boolean" and not isinstance(value, bool):
                return f"Parameter '{key}' must be a boolean"
            elif expected_type == "array" and not isinstance(value, list):
                return f"Parameter '{key}' must be an array"
            elif expected_type == "object" and not isinstance(value, dict):
                return f"Parameter '{key}' must be an object"
            
            # Enum validation
            if "enum" in prop and value not in prop["enum"]:
                return f"Parameter '{key}' must be one of: {prop['enum']}"
        
        return None
    
    def _check_rate_limit(self) -> bool:
        """Check if rate limit allows this call."""
        if self.config.rate_limit_calls <= 0:
            return True
        
        now = time.time()
        cutoff = now - self.config.rate_limit_period_seconds
        
        # Remove old entries
        self._rate_limit_calls = [t for t in self._rate_limit_calls if t > cutoff]
        
        if len(self._rate_limit_calls) >= self.config.rate_limit_calls:
            return False
        
        self._rate_limit_calls.append(now)
        return True
    
    def _get_cache_key(self, kwargs: Dict[str, Any]) -> str:
        """Generate cache key from arguments."""
        serialized = json.dumps(kwargs, sort_keys=True, default=str)
        return hashlib.md5(serialized.encode()).hexdigest()
    
    def _get_from_cache(self, key: str) -> Optional[ToolResult]:
        """Get result from cache if not expired."""
        if key not in self._cache:
            return None
        
        entry = self._cache[key]
        if entry.is_expired():
            del self._cache[key]
            return None
        
        return entry.result
    
    def _add_to_cache(self, key: str, result: ToolResult):
        """Add result to cache."""
        self._cache[key] = CacheEntry(
            result=result,
            cached_at=datetime.now(),
            ttl_seconds=self.config.cache_ttl_seconds
        )
    
    def _update_metrics(self, success: bool, execution_time: int, error: Optional[str]):
        """Update tool metrics."""
        self._metrics.total_calls += 1
        self._metrics.total_execution_time_ms += execution_time
        self._metrics.last_called = datetime.now()
        
        if success:
            self._metrics.successful_calls += 1
        else:
            self._metrics.failed_calls += 1
            self._metrics.last_error = error
    
    def _make_result(
        self,
        output: Optional[str] = None,
        error: Optional[str] = None,
        correlation_id: Optional[str] = None,
        execution_time_ms: int = 0
    ) -> ToolResult:
        """Create a ToolResult with common fields."""
        return ToolResult(
            output=output,
            error=error,
            correlation_id=correlation_id,
            execution_time_ms=execution_time_ms
        )
    
    def _safe_log_args(self, kwargs: Dict[str, Any], max_len: int = 100) -> str:
        """Safely log arguments, truncating sensitive/long values."""
        safe = {}
        for k, v in kwargs.items():
            v_str = str(v)
            if len(v_str) > max_len:
                v_str = v_str[:max_len] + "..."
            safe[k] = v_str
        return str(safe)
    
    # Convenience methods for subclasses
    def success_response(self, data: Any) -> ToolResult:
        """Create a successful response."""
        if isinstance(data, str):
            output = data
        else:
            output = json.dumps(data, default=str)
        return ToolResult(output=output)
    
    def fail_response(self, error: str) -> ToolResult:
        """Create a failure response."""
        return ToolResult(error=error)
    
    # Health check
    async def health_check(self) -> Dict[str, Any]:
        """Check tool health and return status."""
        return {
            "name": self.name,
            "healthy": True,
            "metrics": {
                "total_calls": self._metrics.total_calls,
                "success_rate": self._metrics.success_rate,
                "avg_execution_time_ms": self._metrics.avg_execution_time_ms,
                "cache_hits": self._metrics.cache_hits
            },
            "config": {
                "timeout_seconds": self.config.timeout_seconds,
                "max_retries": self.config.max_retries,
                "cache_enabled": self.config.enable_cache
            }
        }
    
    def get_metrics(self) -> ToolMetrics:
        """Get tool metrics."""
        return self._metrics
    
    def clear_cache(self):
        """Clear the tool's cache."""
        self._cache.clear()
    
    # OpenAI function calling format
    def to_param(self) -> dict:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }


# Decorator for cacheable tools
def cacheable(ttl_seconds: int = 60):
    """Decorator to make a tool cacheable."""
    def decorator(cls):
        original_post_init = getattr(cls, 'model_post_init', None)
        
        def new_post_init(self, __context):
            if original_post_init:
                original_post_init(self, __context)
            self.config.enable_cache = True
            self.config.cache_ttl_seconds = ttl_seconds
        
        cls.model_post_init = new_post_init
        return cls
    return decorator


# Decorator for rate-limited tools
def rate_limited(calls: int, period_seconds: int = 60):
    """Decorator to add rate limiting to a tool."""
    def decorator(cls):
        original_post_init = getattr(cls, 'model_post_init', None)
        
        def new_post_init(self, __context):
            if original_post_init:
                original_post_init(self, __context)
            self.config.rate_limit_calls = calls
            self.config.rate_limit_period_seconds = period_seconds
        
        cls.model_post_init = new_post_init
        return cls
    return decorator

