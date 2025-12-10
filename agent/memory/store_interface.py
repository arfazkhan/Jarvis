"""
Memory Store Interface - Redis-Ready Design
Abstract interface for memory storage backends.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from datetime import datetime


class MemoryStore(ABC):
    """Abstract base class for memory storage backends."""
    
    @abstractmethod
    def get(self, key: str) -> Optional[Dict]:
        """Get value by key."""
        pass
    
    @abstractmethod
    def set(self, key: str, value: Dict, ttl: Optional[int] = None) -> bool:
        """Set value with optional TTL (seconds)."""
        pass
    
    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete by key."""
        pass
    
    @abstractmethod
    def keys(self, pattern: str = "*") -> List[str]:
        """List keys matching pattern."""
        pass


class LocalMemoryStore(MemoryStore):
    """In-memory implementation for local/single-instance use."""
    
    def __init__(self):
        self._data: Dict[str, Dict] = {}
        self._expiry: Dict[str, datetime] = {}
    
    def get(self, key: str) -> Optional[Dict]:
        # Check expiry
        if key in self._expiry:
            if datetime.now() > self._expiry[key]:
                self.delete(key)
                return None
        return self._data.get(key)
    
    def set(self, key: str, value: Dict, ttl: Optional[int] = None) -> bool:
        self._data[key] = value
        if ttl:
            from datetime import timedelta
            self._expiry[key] = datetime.now() + timedelta(seconds=ttl)
        return True
    
    def delete(self, key: str) -> bool:
        self._data.pop(key, None)
        self._expiry.pop(key, None)
        return True
    
    def keys(self, pattern: str = "*") -> List[str]:
        import fnmatch
        if pattern == "*":
            return list(self._data.keys())
        return [k for k in self._data.keys() if fnmatch.fnmatch(k, pattern)]
    
    def clear(self):
        """Clear all data."""
        self._data.clear()
        self._expiry.clear()


# Future Redis implementation placeholder
class RedisMemoryStore(MemoryStore):
    """Redis implementation for distributed/multi-instance use.
    
    Usage:
        import redis
        client = redis.Redis(host='localhost', port=6379)
        store = RedisMemoryStore(client)
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    def get(self, key: str) -> Optional[Dict]:
        import json
        data = self.redis.get(key)
        return json.loads(data) if data else None
    
    def set(self, key: str, value: Dict, ttl: Optional[int] = None) -> bool:
        import json
        return self.redis.set(key, json.dumps(value), ex=ttl)
    
    def delete(self, key: str) -> bool:
        return self.redis.delete(key) > 0
    
    def keys(self, pattern: str = "*") -> List[str]:
        return [k.decode() for k in self.redis.keys(pattern)]
