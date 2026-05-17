import asyncio
import time
import aiohttp
from typing import List, Optional
from dataclasses import dataclass
from urllib.parse import urlparse

from core.parser import Channel
from config.settings import (
    SPEED_TEST_TIMEOUT, SPEED_TEST_DURATION, 
    MAX_CONCURRENT_TESTS, PROXY_ENABLED, PROXY_URL
)


@dataclass
class SpeedResult:
    url: str
    speed: Optional[float]  # None=失败, 0=无法计算
    latency_ms: float = -1
    error: str = ""


class SpeedTester:
    """
    异步测速器 - 关键优化：
    1. 组播源(udp/rtp/rtsp)直接跳过HTTP测速，标记为SKIP
    2. 使用aiohttp + 代理支持(Clash外网源)
    3. 快速失败：连接超时3秒，总超时20秒
    4. 只测前N秒，不下载完整流
    """
    
    def __init__(
        self,
        timeout: int = SPEED_TEST_TIMEOUT,
        duration: int = SPEED_TEST_DURATION,
        max_concurrent: int = MAX_CONCURRENT_TESTS,
        proxy_url: Optional[str] = PROXY_URL if PROXY_ENABLED else None
    ):
        self.timeout = timeout
        self.duration = duration
        self.max_concurrent = max_concurrent
        self.proxy_url = proxy_url
        
        # 连接器配置
        self.connector = aiohttp.TCPConnector(
            limit=max_concurrent * 2,
            limit_per_host=5,  # 单域名并发限制，防被封
            enable_cleanup_closed=True,
            force_close=True,   # 测速完关闭连接，不 keep-alive
            ttl_dns_cache=300,
        )
        
        # 超时配置：连接3秒，总超时20秒
        self.client_timeout = aiohttp.ClientTimeout(
            total=timeout,
            connect=min(3, timeout),  # 连接超时3秒，快速失败
            sock_read=timeout
        )
    
    def is_multicast(self, url: str) -> bool:
        """判断是否为组播源 - 这些源不走HTTP测速"""
        url_lower = url.strip().lower()
        return any(url_lower.startswith(p) for p in [
            'udp://', 'rtp://', 'rtsp://', 'udpxy://'
        ]) or url_lower.startswith((
            'http://239.', 'http://233.', 'http://232.',
            'http://[ff', 'http://[23'
        ))
    
    def is_private_ip(self, url: str) -> bool:
        """判断是否为内网IP源 - 可能无法从外网测速"""
        try:
            parsed = urlparse(url)
            host = parsed.hostname
            if not host:
                return False
            # 内网段
            if host.startswith(('10.', '172.16.', '172.17.', '172.18.', 
                              '172.19.', '172.20.', '172.21.', '172.22.',
                              '172.23.', '172.24.', '172.25.', '172.26.',
                              '172.27.', '172.28.', '172.29.', '172.30.',
                              '172.31.', '192.168.')):
                return True
            return False
        except:
            return False
    
    async def test_channel(self, session: aiohttp.ClientSession, 
                          channel: Channel) -> SpeedResult:
        """测速单个频道 - 组播直接返回SKIP"""
        url = channel.url.strip()
        
        # === 关键优化1：组播源跳过HTTP测速 ===
        if self.is_multicast(url):
            channel.speed = None  # 组播不测速，后续特殊处理
            return SpeedResult(url=url, speed=None, error="multicast_skip")
        
        # === 关键优化2：内网源标记，可能无法从外网测通 ===
        is_private = self.is_private_ip(url)
        
        start = time.time()
        total_bytes = 0
        
        try:
            async with session.get(
                url,
                timeout=self.client_timeout,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': '*/*',
                    'Connection': 'close',  # 不保持连接
                },
                allow_redirects=True,
                proxy=self.proxy_url,  # Clash代理
            ) as resp:
                
                # 快速检查状态码
                if resp.status not in (200, 206):
                    channel.speed = None
                    return SpeedResult(
                        url=url, speed=None, 
                        latency_ms=(time.time()-start)*1000,
                        error=f"http_{resp.status}"
                    )
                
                # 读取数据测速，只读duration秒
                read_start = time.time()
                async for chunk in resp.content.iter_chunked(8192):
                    total_bytes += len(chunk)
                    elapsed = time.time() - read_start
                    
                    if elapsed >= self.duration:
                        break
                    
                    # 总超时保护
                    if time.time() - start > self.timeout:
                        break
                
                elapsed = time.time() - read_start
                if elapsed <= 0:
                    channel.speed = None
                    return SpeedResult(url=url, speed=None, error="no_data")
                
                # 计算速度 KB/s
                speed_kbps = (total_bytes / 1024) / elapsed
                
                # 内网源但速度极低，可能是外网不通
                if is_private and speed_kbps < 1:
                    channel.speed = None
                    return SpeedResult(url=url, speed=None, error="private_slow")
                
                channel.speed = speed_kbps
                return SpeedResult(
                    url=url, 
                    speed=speed_kbps,
                    latency_ms=(time.time()-start)*1000
                )
                
        except asyncio.TimeoutError:
            channel.speed = None
            return SpeedResult(url=url, speed=None, error="timeout")
        except Exception as e:
            channel.speed = None
            return SpeedResult(url=url, speed=None, error=str(e)[:50])
    
    async def test_all(self, channels: List[Channel]) -> List[Channel]:
        """批量测速 - 带进度显示"""
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        # 分离组播和单播
        multicast_channels = [c for c in channels if self.is_multicast(c.url)]
        unicast_channels = [c for c in channels if not self.is_multicast(c.url)]
        
        print(f"[测速] 组播源: {len(multicast_channels)}个 (跳过测速)")
        print(f"[测速] 单播源: {len(unicast_channels)}个 (开始测速)")
        
        # 组播源直接标记
        for ch in multicast_channels:
            ch.speed = None  # 标记为未测速，后续特殊处理
        
        if not unicast_channels:
            return channels
        
        async with aiohttp.ClientSession(connector=self.connector) as session:
            async def bounded_test(ch):
                async with semaphore:
                    return await self.test_channel(session, ch)
            
            # 分批执行，每批显示进度
            batch_size = 50
            total = len(unicast_channels)
            results = []
            
            for i in range(0, total, batch_size):
                batch = unicast_channels[i:i+batch_size]
                tasks = [bounded_test(ch) for ch in batch]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # 处理异常结果
                for j, res in enumerate(batch_results):
                    if isinstance(res, Exception):
                        batch[j].speed = None
                        results.append(SpeedResult(url=batch[j].url, speed=None, error=str(res)))
                    else:
                        results.append(res)
                
                # 进度显示
                done = min(i + batch_size, total)
                success = sum(1 for r in results if r.speed is not None)
                print(f"[测速进度] {done}/{total} ({done/total*100:.0f}%) - "
                      f"成功:{success} 失败:{done-success}")
        
        return channels
    
    def close(self):
        """清理连接器"""
        if hasattr(self, 'connector'):
            asyncio.get_event_loop().run_until_complete(self.connector.close())
