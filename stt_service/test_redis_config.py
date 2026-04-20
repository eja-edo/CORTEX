#!/usr/bin/env python
"""
Redis configuration verification script.
Tests connection and validates settings.
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

async def test_redis_connection():
    """Test Redis connection and verify configuration."""
    
    print("=" * 70)
    print("REDIS CONFIGURATION CHECK")
    print("=" * 70)
    
    # Load config
    try:
        from stt_service.config.app_config import ConfigManager
        config_manager = ConfigManager()
        config = config_manager.get_config()
        redis_config = config.redis
        
        print("\n📋 Redis Configuration Loaded:")
        print(f"  Host: {redis_config.host}")
        print(f"  Port: {redis_config.port}")
        print(f"  DB: {redis_config.db}")
        print(f"  Password: {'SET (len=' + str(len(redis_config.password)) + ')' if redis_config.password else 'NOT SET (empty string)'}")
        print(f"  Connection Pool Max: {redis_config.max_connections}")
        print(f"  Socket Timeout: {redis_config.socket_timeout}s")
        print(f"  Socket Connect Timeout: {redis_config.socket_connect_timeout}s")
        
    except Exception as e:
        print(f"\n❌ Failed to load config: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test connection
    print("\n" + "=" * 70)
    print("Testing Redis Connection...")
    print("=" * 70)
    
    try:
        import redis.asyncio as redis
        
        # Build connection string
        conn_string = f"redis://{redis_config.host}:{redis_config.port}/{redis_config.db}"
        if redis_config.password:
            conn_string = f"redis://:{redis_config.password}@{redis_config.host}:{redis_config.port}/{redis_config.db}"
        
        print(f"\n🔗 Connection String: {conn_string}")
        
        # Try to connect
        r = await redis.from_url(
            f"redis://{'':redis_config.password + '@' if redis_config.password else ''}{redis_config.host}:{redis_config.port}/{redis_config.db}",
            socket_timeout=redis_config.socket_timeout,
            socket_connect_timeout=redis_config.socket_connect_timeout,
            decode_responses=False
        )
        
        # Test PING
        result = await r.ping()
        print(f"\n✅ PING result: {result}")
        
        # Test SET/GET
        await r.set("cortex:test:key", "test_value")
        value = await r.get("cortex:test:key")
        print(f"✅ SET/GET test: {value}")
        
        # Get info
        info = await r.info("server")
        print(f"\n✅ Redis Server Info:")
        print(f"  Redis version: {info.get('redis_version', 'N/A')}")
        print(f"  OS: {info.get('os', 'N/A')}")
        print(f"  Uptime: {info.get('uptime_in_seconds', 'N/A')}s")
        
        # Check if empty password works (without password)
        if not redis_config.password:
            print(f"\n✓ Password is not set (empty string)")
            print(f"✓ Connecting without auth - OK")
        else:
            print(f"\n⚠️  Password is set to: {'*' * len(redis_config.password)}")
            print(f"⚠️  Make sure Redis is configured with the same password!")
        
        await r.close()
        
        print("\n" + "=" * 70)
        print("✅ REDIS CONFIGURATION IS CORRECT!")
        print("=" * 70)
        return True
        
    except Exception as e:
        print(f"\n❌ Redis connection failed: {e}")
        print(f"\n⚠️  Check if:")
        print(f"  1. Redis is running: docker compose ps redis")
        print(f"  2. Port 6379 is accessible")
        print(f"  3. Password matches (if set)")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_redis_connection())
    sys.exit(0 if success else 1)
