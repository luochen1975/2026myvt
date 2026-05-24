#!/usr/bin/env python3
"""
IPTV 分层测速器
- 组播/RTSP：ffmpeg 探测
- HTTP 国内：aiohttp 直连
- HTTP 国外/代理：Clash + aiohttp
"""
import asyncio
import subprocess
import time
from typing import Dict, List, Optional

import aiohttp
from aiohttp import ClientTimeout, TCPConnector

from utils.logger import log


class SpeedTester:
    """
    分层测速器
    proxy 控制逻辑：
      - source_configs[url].get("proxy") == True  → 走 Clash 代理
      - source_configs[url].get("proxy") == False → 直连
      - 未设置 → 按 URL 特征自动判断（组播/本地直连，http外网走代理）
    """

    def __init__(
        self,
        timeout: float = 10.0,
        duration: float = 3.0,
        max_concurrent: int = 50,
        clash_api: str = "http://127.0.0.1:7890",  # Clash HTTP 代理端口
    ):
        self.timeout = timeout
        self.duration = duration
        self.max_concurrent = max_concurrent
        self.clash_api = clash_api
        self.semaphore = asyncio.Semaphore(max_concurrent)

    def _is_multicast(self, url: str) -> bool:
        url_low = url.lower().strip()
        return url_low.startswith(("udp://", "rtp://", "rtsp://"))

    def _is_ipv6(self, url: str) -> bool:
        return "[" in url and "]" in url

    def _need_proxy(self, ch, source_configs: dict) -> bool:
        """
        判断是否使用代理：
        1. 优先读取 source_configs 中强制设置的 proxy 字段
        2. 未设置时自动判断：
           - 组播/IPv6 直连
           - 国内常见域名直连
           - 其他 HTTP 默认走代理（GitHub Actions 环境）
        """
        url = ch.url
        cfg = source_configs.get(url, {})

        # 强制指定（main.py 里对港澳台/国外会强制设 True/False）
        if "proxy" in cfg:
            return bool(cfg["proxy"])

        # 自动判断
        url_low = url.lower()

        # 组播/RTSP 不走代理
        if self._is_multicast(url):
            return False

        # IPv6 地址通常是国内运营商内网，不走代理
        if self._is_ipv6(url):
            return False

        # 国内常见域名直连
        domestic = [
            ".cn", "chinamobile", "cmcc", "migu", "bestv", "bcs.ott",
            "mobaibox", "gitv", "cntv", "cctv", "tvfan", "ott.fif",
        ]
        if any(d in url_low for d in domestic):
            return False

        # 默认：HTTP/HTTPS 外网源在 Actions 环境走代理
        return True

    async def _test_ffmpeg(self, url: str) -> Optional[float]:
        """用 ffmpeg 探测组播/RTSP 源的速度 (KB/s)"""
        cmd = [
            "ffmpeg",
            "-i", url,
            "-t", str(self.duration),
            "-f", "null",
            "-",
        ]
        start = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                return None

            elapsed = time.time() - start
            if proc.returncode != 0:
                return None

            # 简单估算：ffmpeg 成功打开并读取了 duration 秒，认为可用
            # 返回一个固定高速度值表示通畅（实际直播不需要精确带宽）
            return 9999.0
        except Exception as e:
            log.debug(f"ffmpeg 测速失败 {url}: {e}")
            return None

    async def _test_aiohttp(
        self,
        url: str,
        use_proxy: bool = False,
    ) -> Optional[float]:
        """用 aiohttp 测 HTTP 源的速度 (KB/s)"""
        connector = TCPConnector(limit=100, force_close=True, enable_cleanup_closed=True)

        # 代理设置
        proxy = None
        if use_proxy and self.clash_api:
            proxy = self.clash_api

        timeout = ClientTimeout(total=self.timeout, connect=5)

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            trust_env=True,
        ) as session:
            start = time.time()
            try:
                async with session.get(url, proxy=proxy, allow_redirects=True) as resp:
                    if resp.status >= 400:
                        return None

                    total_bytes = 0
                    chunk_start = time.time()
                    async for chunk in resp.content.iter_chunked(8192):
                        total_bytes += len(chunk)
                        if time.time() - chunk_start >= self.duration:
                            break

                    elapsed = time.time() - start
                    if elapsed < 0.1:
                        elapsed = 0.1

                    speed_kbps = (total_bytes / 1024) / elapsed
                    return speed_kbps
            except asyncio.TimeoutError:
                return None
            except Exception as e:
                log.debug(f"aiohttp 测速失败 {url} proxy={use_proxy}: {e}")
                return None
            finally:
                await connector.close()

    async def _test_one(
        self,
        ch,
        source_configs: dict,
    ) -> None:
        """测速单个频道"""
        url = ch.url
        use_proxy = self._need_proxy(ch, source_configs)

        async with self.semaphore:
            if self._is_multicast(url):
                log.debug(f"[ffmpeg] {ch.name} {url[:60]}...")
                speed = await self._test_ffmpeg(url)
            else:
                log.debug(f"[{'代理' if use_proxy else '直连'}] {ch.name} {url[:60]}...")
                speed = await self._test_aiohttp(url, use_proxy=use_proxy)

            ch.speed = speed
            status = f"{speed:.1f}KB/s" if speed else "失败"
            log.debug(f"  → {status}")

    async def test_all(
        self,
        channels: List,
        source_configs: dict,
    ) -> None:
        """批量测速"""
        if not channels:
            return

        tasks = [
            asyncio.create_task(self._test_one(ch, source_configs))
            for ch in channels
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        # 统计
        ok = sum(1 for c in channels if c.speed is not None)
        fail = len(channels) - ok
        log.info(f"测速完成: 成功{ok} 失败{fail}")
