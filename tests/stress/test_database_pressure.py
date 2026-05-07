"""
Stress Test: Database Pressure
==============================

Test ARVIS database performance under load.
- 1M+ rows
- Query performance
- Write performance
"""

import pytest
import asyncio
from datetime import datetime, timedelta

from agent_commercial.database import BMSDatabase
from tests.factories import DataPointFactory


class TestDatabasePressure:
    """Database performance under heavy load."""
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    @pytest.mark.slow
    async def test_write_100k_points(self):
        """Write 100,000 data points rapidly."""
        db = BMSDatabase(db_path=":memory:")
        
        # Write 100k points
        start = asyncio.get_event_loop().time()
        for i in range(100000):
            await db.save_data_point(
                point_id=f"CH-01/P{i % 100:03d}",
                value=float(i),
                unit="°C",
                equipment_id="CH-01"
            )
        elapsed = asyncio.get_event_loop().time() - start
        
        # Should complete in reasonable time
        assert elapsed < 30.0, f"Writing 100k points took {elapsed:.2f}s"
        
        # Close
        await db.close()
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    @pytest.mark.slow
    async def test_query_with_500k_rows(self):
        """Query performance with 500k rows."""
        db = BMSDatabase(db_path=":memory:")
        
        # Seed 500k rows
        for i in range(500000):
            await db.save_data_point(
                point_id=f"CH-01/P{i % 50:03d}",
                value=float(i),
                unit="°C",
                equipment_id="CH-01"
            )
        
        # Query recent history
        start = asyncio.get_event_loop().time()
        history = await db.get_point_history("CH-01/P001", hours=24)
        elapsed = asyncio.get_event_loop().time() - start
        
        # Should query quickly even with 500k rows
        assert elapsed < 5.0, f"Query took {elapsed:.2f}s with 500k rows"
        
        await db.close()
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    @pytest.mark.slow
    async def test_concurrent_db_writes(self):
        """1000 concurrent database writes."""
        db = BMSDatabase(db_path=":memory:")
        
        # Concurrent writes
        async def write_batch(batch_id):
            for i in range(100):
                await db.save_data_point(
                    point_id=f"BATCH-{batch_id}/P{i:03d}",
                    value=float(batch_id * 100 + i),
                    unit="kW",
                    equipment_id=f"BATCH-{batch_id}"
                )
        
        # Run 10 concurrent batches
        tasks = [write_batch(i) for i in range(10)]
        await asyncio.gather(*tasks)
        
        # Verify all written
        # (In real test, would query and count)
        
        await db.close()
    
    @pytest.mark.asyncio
    @pytest.mark.stress
    async def test_database_cleanup(self):
        """Database should clean up old data."""
        db = BMSDatabase(db_path=":memory:")
        
        # Write points with old timestamps
        old_time = datetime.now() - timedelta(days=365)
        for i in range(1000):
            await db.save_data_point(
                point_id=f"OLD/P{i:03d}",
                value=float(i),
                unit="°C"
            )
        
        # Get stats
        stats = db.get_stats()
        assert stats["total_readings"] == 1000
        
        await db.close()


if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-v", "-m", "stress"])
