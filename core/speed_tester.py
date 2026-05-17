import asyncio
import time
import aiohttp
import socket
import ipaddress
import subprocess
from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass
from urllib.parse import urlparse

from core.parser import Channel
from config.settings import (
    SPEED_TEST_TIMEOUT, SPEED_TEST_DURATION, 
    MAX_CONCURRENT_TESTS, PROXY_ENABLED, PROXY_URL,
    MULTICAST_MIN_SPEED, UNICAST_MIN_SPEED
)


@dataclass
class SpeedConfig:
    """分层测速配置"""
    duration: float
    total_timeout: float
    connect_timeout: float
    min_speed: float
    use_proxy: bool
    is_multicast: bool  # 是否组播协议（udp/rtp）


class SpeedTester:
    """
    分层异步测速器：
    - 组播源：用 ffmpeg/ffprobe 或 socket 测速（原生UDP/RTP）
    - HTTP组播转单播：用 aiohttp 测速
    - 国内单播：正常测速
    - 外网/代理源：延长测速时间，走Clash代理
    """
    
    # 外网/港澳台域名特征
    OVERSEAS_PATTERNS = [
        '.hk', '.tw', '.mo', '.sg', '.jp', '.kr', '.us', '.uk', '.eu',
        'aktv', 'youtube', 'youtu.be', 'google', 'gstatic',
        'cloudfront', 'cloudflare', 'fastly', 'bunny',
        'vimeo', 'dailymotion', 'twitch', 'tiktok',
        'hktv', 'tvb', 'viu', 'mytv', 'linetv',
        'hamivideo', 'ofiii', '4gtv', 'litv',
        'iqiyi', 'youku', 'bilibili', 'douyin',
    ]
    
    # 国内CDN特征
    CN_PATTERNS = [
        '.cn', '.com.cn', '.net.cn', 'alicdn', 'aliyun', 'aliyuncs',
        'tencent', 'qcloud', 'myqcloud', 'baidu', 'bdstatic',
        'douyincdn', 'byteimg', 'qiniu', 'hwcdn', 'ctyun',
        'cctv', 'cntv', 'chinanet', 'cmcc', 'unicom', 'telecom',
    ]
    
    def __init__(
        self,
        timeout: int = SPEED_TEST_TIMEOUT,
        duration: int = SPEED_TEST_DURATION,
        max_concurrent: int = MAX_CONCURRENT_TESTS,
        proxy_url: Optional[str] = PROXY_URL if PROXY_ENABLED else None
    ):
        self.proxy_url = proxy_url
        self.max_concurrent = max_concurrent
        
        # HTTP连接器
        self.connector = aiohttp.TCPConnector(
            limit=max_concurrent * 3,
            limit_per_host=3,
            enable_cleanup_closed=True,
            force_close=True,
            ttl_dns_cache=300,
        )
        
        # 组播测速信号量（ffmpeg并发不能太高）
        self.mc_semaphore = asyncio.Semaphore(min(10, max_concurrent))
    
    def is_native_multicast(self, url: str) -> bool:
        """原生组播协议（udp/rtp/rtsp）"""
        return url.strip().lower().startswith(('udp://', 'rtp://', 'rtsp://'))
    
    def is_http_multicast(self, url: str) -> bool:
        """HTTP转发的组播地址"""
        url_lower = url.strip().lower()
        return url_lower.startswith((
            'http://239.', 'http://233.', 'http://232.', 'http://231.',
            'http://[ff', 'http://[23'
        ))
    
    def is_multicast(self, url: str) -> bool:
        """所有组播类型"""
        return self.is_native_multicast(url) or self.is_http_multicast(url)
    
    def is_private_ip(self, url: str) -> bool:
        """内网IP判断"""
        try:
            parsed = urlparse(url)
            host = parsed.hostname
            if not host:
                return False
            try:
                ip = ipaddress.ip_address(host)
                return ip.is_private
            except ValueError:
                return host.startswith((
                    '10.', '172.16.', '172.17.', '172.18.', '172.19.',
                    '172.20.', '172.21.', '172.22.', '172.23.', '172.24.',
                    '172.25.', '172.26.', '172.27.', '172.28.', '172.29.',
                    '172.30.', '172.31.', '192.168.', '127.'
                ))
        except:
            return False
    
    def classify_source(self, url: str, source_config: Optional[dict] = None) -> SpeedConfig:
        """分层识别源类型，返回测速配置"""
        url_lower = url.lower()
        parsed = urlparse(url)
        host = parsed.hostname or ""
        
        # 原生组播（udp/rtp/rtsp）
        if self.is_native_multicast(url):
            return SpeedConfig(
                duration=8,           # 组播测8秒
                total_timeout=15,     # 组播超时15秒
                connect_timeout=5,
                min_speed=MULTICAST_MIN_SPEED,  # 10 KB/s
                use_proxy=False,
                is_multicast=True
            )
        
        # HTTP组播转发
        if self.is_http_multicast(url):
            return SpeedConfig(
                duration=8,
                total_timeout=15,
                connect_timeout=3,
                min_speed=MULTICAST_MIN_SPEED,
                use_proxy=False,
                is_multicast=False  # 走HTTP测速
            )
        
        # 内网IP
        if self.is_private_ip(url):
            return SpeedConfig(
                duration=5,
                total_timeout=10,
                connect_timeout=2,
                min_speed=10,
                use_proxy=False,
                is_multicast=False
            )
        
        # 代理源
        if source_config and source_config.get('proxy'):
            return SpeedConfig(
                duration=15,          # 外网15秒
                total_timeout=35,
                connect_timeout=10,
                min_speed=15,
                use_proxy=True,
                is_multicast=False
            )
        
        # 外网/港澳台
        if any(pat in host for pat in self.OVERSEAS_PATTERNS):
            return SpeedConfig(
                duration=15,
                total_timeout=35,
                connect_timeout=10,
                min_speed=15,
                use_proxy=True,
                is_multicast=False
            )
        
        # 国内CDN
        if any(pat in host for pat in self.CN_PATTERNS):
            return SpeedConfig(
                duration=8,
                total_timeout=15,
                connect_timeout=3,
                min_speed=20,
                use_proxy=False,
                is_multicast=False
            )
        
        # 默认
        return SpeedConfig(
            duration=10,
            total_timeout=20,
            connect_timeout=5,
            min_speed=15,
            use_proxy=False,
            is_multicast=False
        )
    
    async def test_native_multicast(self, channel: Channel, config: SpeedConfig) -> None:
        """
        原生组播测速：用 ffprobe 或 ffmpeg 探测
        返回码0且能读到数据视为成功
        """
        url = channel.url.strip()
        
        async with self.mc_semaphore:
            try:
                # 方法1：ffprobe 探测流信息（最准确）
                proc = await asyncio.create_subprocess_exec(
                    'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                    '-show_entries', 'stream=codec_type', '-of',
                    'default=noprint_wrappers=1', '-timeout', '5000000',  # 5秒微秒
                    '-i', url,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                
                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), 
                        timeout=config.total_timeout
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    channel.speed = None
                    return
                
                if proc.returncode == 0 and stdout:
                    # ffprobe成功，说明流可用
                    # 估算速度：无法精确测速，给个中等值标记可用
                    channel.speed = 100.0  # 虚拟值，表示可用
                else:
                    channel.speed = None
                    
            except FileNotFoundError:
                # ffprobe 不存在，降级用 ffmpeg
                await self._test_with_ffmpeg(channel, config)
            except Exception:
                channel.speed = None
    
    async def _test_with_ffmpeg(self, channel: Channel, config: SpeedConfig) -> None:
        """ffmpeg 测速备用"""
        url = channel.url.strip()
        
        try:
            proc = await asyncio.create_subprocess_exec(
                'ffmpeg', '-i', url, '-t', '3', '-f', 'null', '-',
                '-y', '-v', 'quiet',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            try:
                _, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=config.total_timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                channel.speed = None
                return
            
            # ffmpeg 能连接上就算成功（组播通常稳定）
            if proc.returncode == 0:
                channel.speed = 100.0
            else:
                # 检查stderr是否有流信息
                err = stderr.decode('utf-8', errors='ignore') if stderr else ''
                if 'Stream #' in err or 'Input #' in err:
                    channel.speed = 100.0  # 能解析到流信息也算可用
                else:
                    channel.speed = None
                    
        except Exception:
            channel.speed = None
    
    async def test_http_channel(self, session: aiohttp.ClientSession,
                               channel: Channel,
                               config: SpeedConfig) -> None:
        """HTTP/HTTPS 源测速"""
        url = channel.url.strip()
        start = time.time()
        total_bytes = 0
        
        client_timeout = aiohttp.ClientTimeout(
            total=config.total_timeout,
            connect=config.connect_timeout,
            sock_read=config.total_timeout
        )
        
        try:
            async with session.get(
                url,
                timeout=client_timeout,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': '*/*',
                    'Connection': 'close',
                    'Referer': urlparse(url).scheme + '://' + urlparse(url).netloc,
                },
                allow_redirects=True,
                proxy=self.proxy_url if config.use_proxy else None,
            ) as resp:
                
                if resp.status not in (200, 206):
                    channel.speed = None
                    return
                
                read_start = time.time()
                async for chunk in resp.content.iter_chunked(16384):
                    total_bytes += len(chunk)
                    elapsed = time.time() - read_start
                    
                    if elapsed >= config.duration:
                        break
                    if time.time() - start > config.total_timeout:
                        break
                    if total_bytes > 1024 * 1024:  # 1MB足够
                        break
                
                elapsed = time.time() - read_start
                if elapsed <= 0.1:
                    elapsed = 0.1
                
                speed_kbps = (total_bytes / 1024) / elapsed
                
                if speed_kbps < config.min_speed:
                    channel.speed = None
                else:
                    channel.speed = speed_kbps
                    
        except asyncio.TimeoutError:
            channel.speed = None
        except Exception:
            channel.speed = None
    
    async def test_channel(self, session: aiohttp.ClientSession,
                          channel: Channel,
                          config: SpeedConfig) -> None:
        """根据类型选择测速方式"""
        if config.is_multicast:
            # 原生组播用 ffmpeg/ffprobe
            await self.test_native_multicast(channel, config)
        else:
            # HTTP 源用 aiohttp
            await self.test_http_channel(session, channel, config)
    
    async def test_all(self, channels: List[Channel],
                      source_configs: Optional[Dict[str, dict]] = None) -> List[Channel]:
        """批量分层测速"""
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        # 分类统计
        native_mc = [c for c in channels if self.is_native_multicast(c.url)]
        http_mc = [c for c in channels if self.is_http_multicast(c.url)]
        unicast = [c for c in channels if not self.is_multicast(c.url)]
        
        print(f"[测速] 原生组播: {len(native_mc)}个 (ffmpeg)")
        print(f"[测速] HTTP组播: {len(http_mc)}个 (aiohttp)")
        print(f"[测速] 单播源: {len(unicast)}个")
        
        # 分层统计
        stats = {"内网": 0, "国内": 0, "代理": 0, "外网": 0, "未知": 0}
        for ch in unicast + http_mc:
            cfg = self.classify_source(ch.url, source_configs.get(ch.url) if source_configs else None)
            if cfg.duration == 5:
                stats["内网"] += 1
            elif not cfg.use_proxy and cfg.duration == 8:
                stats["国内"] += 1
            elif cfg.use_proxy and cfg.duration == 15:
                if source_configs and source_configs.get(ch.url, {}).get('proxy'):
                    stats["代理"] += 1
                else:
                    stats["外网"] += 1
            else:
                stats["未知"] += 1
        
        for k, v in stats.items():
            if v > 0:
                print(f"  - {k}: {v}个")
        
        if not channels:
            return channels
        
        # 原生组播测速（不需要aiohttp session）
        if native_mc:
            print(f"[测速] 开始原生组播测速...")
            mc_tasks = []
            for ch in native_mc:
                cfg = self.classify_source(ch.url)
                mc_tasks.append(self.test_native_multicast(ch, cfg))
            
            # 分批执行，每批10个（ffmpeg并发不能太高）
            for i in range(0, len(mc_tasks), 10):
                batch = mc_tasks[i:i+10]
                await asyncio.gather(*batch, return_exceptions=True)
                done = min(i + 10, len(native_mc))
                ok = sum(1 for c in native_mc[:done] if c.speed is not None)
                print(f"  组播进度 {done}/{len(native_mc)}: 成功{ok}")
        
        # HTTP源测速
        http_channels = http_mc + unicast
        if http_channels:
            print(f"[测速] 开始HTTP源测速...")
            
            async with aiohttp.ClientSession(connector=self.connector) as session:
                async def bounded_test(ch):
                    async with semaphore:
                        cfg = self.classify_source(
                            ch.url,
                            source_configs.get(ch.url) if source_configs else None
                        )
                        return await self.test_channel(session, ch, cfg)
                
                batch_size = 30
                total = len(http_channels)
                
                for i in range(0, total, batch_size):
                    batch = http_channels[i:i+batch_size]
                    tasks = [bounded_test(ch) for ch in batch]
                    await asyncio.gather(*tasks, return_exceptions=True)
                    
                    done = min(i + batch_size, total)
                    success = sum(1 for c in http_channels[:done] if c.speed is not None)
                    print(f"[测速进度] {done}/{total} ({done/total*100:.0f}%) - "
                          f"成功:{success} 失败:{done-success}")
        
        # 汇总结果
        total_ok = sum(1 for c in channels if c.speed is not None)
        print(f"[测速完成] 总计:{len(channels)} 成功:{total_ok} 失败:{len(channels)-total_ok}")
        
        return channels
    
    def close(self):
        if hasattr(self, 'connector'):
            try:
                asyncio.get_event_loop().run_until_complete(self.connector.close())
            except:
                pass
