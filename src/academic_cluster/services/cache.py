"""
缓存服务

提供 Redis 异步缓存访问。
"""

import json
from typing import Any, Optional

import structlog

from ..config import get_settings

logger = structlog.get_logger()


class CacheService:
    """Redis 异步缓存服务"""

    def __init__(self, redis_url: Optional[str] = None):
        import redis.asyncio as redis

        settings = get_settings()

        if redis_url is None:
            redis_url = settings.redis.url

        self.redis = redis.from_url(
            redis_url,
            decode_responses=True,
        )

        logger.info("Cache service initialized")

    async def close(self):
        """关闭 Redis 连接"""
        await self.redis.close()
        logger.info("Cache connection closed")

    async def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        try:
            data = await self.redis.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning("Cache get failed", key=key, error=str(e))
            return None

    async def set(
        self,
        key: str,
        value: Any,
        expire: int = 3600,
    ) -> bool:
        """设置缓存"""
        try:
            data = json.dumps(value, ensure_ascii=False)
            await self.redis.set(key, data, ex=expire)
            return True
        except Exception as e:
            logger.warning("Cache set failed", key=key, error=str(e))
            return False

    async def delete(self, key: str) -> bool:
        """删除缓存"""
        try:
            await self.redis.delete(key)
            return True
        except Exception as e:
            logger.warning("Cache delete failed", key=key, error=str(e))
            return False

    async def exists(self, key: str) -> bool:
        """检查缓存是否存在"""
        try:
            return await self.redis.exists(key) > 0
        except Exception:
            return False

    async def get_embedding(self, paper_id: str, model_name: str) -> Optional[list[float]]:
        """获取缓存的嵌入向量"""
        key = f"embedding:{model_name}:{paper_id}"
        return await self.get(key)

    async def set_embedding(
        self,
        paper_id: str,
        model_name: str,
        embedding: list[float],
        expire: int = 86400,
    ) -> bool:
        """缓存嵌入向量"""
        key = f"embedding:{model_name}:{paper_id}"
        return await self.set(key, embedding, expire=expire)

    async def get_paper(self, paper_id: str) -> Optional[dict]:
        """获取缓存的论文"""
        key = f"paper:{paper_id}"
        return await self.get(key)

    async def set_paper(
        self,
        paper_id: str,
        paper_data: dict,
        expire: int = 3600,
    ) -> bool:
        """缓存论文"""
        key = f"paper:{paper_id}"
        return await self.set(key, paper_data, expire=expire)

    async def get_search_results(self, query_hash: str) -> Optional[list[dict]]:
        """获取缓存的搜索结果"""
        key = f"search:{query_hash}"
        return await self.get(key)

    async def set_search_results(
        self,
        query_hash: str,
        results: list[dict],
        expire: int = 1800,
    ) -> bool:
        """缓存搜索结果"""
        key = f"search:{query_hash}"
        return await self.set(key, results, expire=expire)


# 全局缓存实例
_cache_service: Optional[CacheService] = None


def get_cache() -> CacheService:
    """获取缓存服务单例"""
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service


async def close_cache():
    """关闭缓存连接"""
    global _cache_service
    if _cache_service is not None:
        await _cache_service.close()
        _cache_service = None
