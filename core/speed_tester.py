import time
import asyncio
import aiohttp
from typing import List, Dict, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.parser import Channel

class SpeedTester:
    """异步测速器"""
    
    def __init__(self, timeout: int = 10, duration: int = 3, max_concurrent: int = 50):
        self.timeout = timeout
        self.duration = duration
        self.max_concurrent = max_concurrent
        self.results_cache: Dict[str, float] = {}
    
    async def test_channel(self, session: aiohttp.ClientSession, channel: Channel) -> float:
        """测速单个频道"""
        cache_key = self._get_cache_key(channel)
        
        # 检查缓存
        if cache_key in self.results_cache:
            channel.speed = self.results_cache[cache_key]
            return channel.speed
        
        start_time = time.time()
        total_bytes = 0
        
        try:
            async with session.get(
                channel.url, 
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={'User-Agent': 'Mozilla/5.0'}
            ) as response:
                
                if response.status != 200:
                    channel.speed = 0
                    return 0
                
                # 读取数据测速
                async for chunk in response.content.iter_chunked(8192):
                    total_bytes += len(chunk)
                    elapsed = time.time() - start_time
                    
                    if elapsed >= self.duration:
                        break
                        
                    # 检查总超时
                    if elapsed > self.timeout:
                        break
            
            elapsed = time.time() - start_time
            speed_kbps = (total_bytes / 1024) / elapsed if elapsed > 0 else 0
            
            channel.speed = speed_kbps
            self.results_cache[cache_key] = speed_kbps
            return speed_kbps
            
        except Exception as e:
            channel.speed = 0
            return 0
    
    async def test_all(self, channels: List[Channel]) -> List[Channel]:
        """批量测速"""
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def bounded_test(session, ch):
            async with semaphore:
                return await self.test_channel(session, ch)
        
        connector = aiohttp.TCPConnector(limit=self.max_concurrent * 2)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [bounded_test(session, ch) for ch in channels]
            await asyncio.gather(*tasks, return_exceptions=True)
        
        return channels
    
    def _get_cache_key(self, channel: Channel) -> str:
        """生成缓存键"""
        return f"{channel.name}|{channel.url}"
    
    def save_cache(self, cache_file: str):
        """保存测速缓存"""
        import json
        with open(cache_file, 'w') as f:
            json.dump(self.results_cache, f)
    
    def load_cache(self, cache_file: str):
        """加载测速缓存"""
        import json
        try:
            with open(cache_file, 'r') as f:
                self.results_cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass