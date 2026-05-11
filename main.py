#!/usr/bin/env python3
import asyncio
import json
import os
import time
from pathlib import Path

from config.settings import *
from core.parser import SourceLoader
from core.merger import ChannelMerger
from core.speed_tester import SpeedTester
from core.exporter import M3UExporter, TXTExporter, LogExporter
from utils.cache import SpeedCache
from utils.logger import log


def auto_detect_type(url: str) -> str:
    url_lower = url.lower()
    if url_lower.endswith(('.m3u', '.m3u8')):
        return 'm3u'
    elif url_lower.endswith('.json'):
        return 'json'
    else:
        return 'txt'


def load_sources() -> list:
    with open(SOURCES_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    sources = []
    
    if isinstance(config, list):
        for item in config:
            if isinstance(item, str):
                url = item.strip()
                sources.append({
                    'name': 'auto',
                    'url': url,
                    'type': auto_detect_type(url),
                    'isp': 'other',
                    'proxy': False,
                    'enabled': True
                })
            elif isinstance(item, dict):
                if item.get('enabled', True):
                    url = item['url']
                    file_type = item.get('type') or auto_detect_type(url)
                    sources.append({
                        'name': item.get('name', 'auto'),
                        'url': url,
                        'type': file_type,
                        'isp': item.get('isp', 'other'),
                        'proxy': item.get('proxy', False),
                        'enabled': True
                    })
    
    elif isinstance(config, dict):
        for file_type, items in config.items():
            for item in items:
                if isinstance(item, str):
                    url = item.strip()
                    sources.append({
                        'name': 'auto',
                        'url': url,
                        'type': file_type,
                        'isp': 'other',
                        'proxy': False,
                        'enabled': True
                    })
                elif isinstance(item, dict) and item.get('enabled', True):
                    sources.append({
                        'name': item.get('name', 'auto'),
                        'url': item['url'],
                        'type': file_type,
                        'isp': item.get('isp', 'other'),
                        'proxy': item.get('proxy', False),
                        'enabled': True
                    })
    
    # GitHub Actions 跳过代理源
    if os.getenv('GITHUB_ACTIONS'):
        proxy_sources = [s for s in sources if s.get('proxy')]
        if proxy_sources:
            log.info(f"[GitHub Actions] 跳过 {len(proxy_sources)} 个代理源")
            sources = [s for s in sources if not s.get('proxy')]
    
    return sources


def sort_for_mobile(channels: List) -> List:
    """移动源优先，组播优先"""
    def get_weight(ch):
        isp = ch.extra.get('isp', 'other')
        is_multicast = ch.url.startswith(('udp://', 'rtp://', 'rtsp://'))
        
        if isp == 'mobile' and is_multicast:
            return 0
        elif isp == 'mobile':
            return 1
        elif is_multicast:
            return 2
        elif isp == 'unicom':
            return 3
        elif isp == 'telecom':
            return 4
        else:
            return 5
    
    return sorted(channels, key=lambda c: (get_weight(c), -c.speed))


def main():
    log.info("=" * 50)
    log.info("IPTV 源处理器启动")
    
    if os.getenv('GITHUB_ACTIONS'):
        log.info("[环境] GitHub Actions (跳过代理源)")
    else:
        log.info("[环境] 本地运行 [浙江宁波移动]")
    
    start_time = time.time()
    cache = SpeedCache(str(CACHE_FILE), ttl=CACHE_TTL_HOURS * 3600)
    
    log.info("[1/5] 加载订阅源...")
    sources = load_sources()
    all_channels = []
    
    for source in sources:
        channels = SourceLoader.load(source)
        all_channels.extend(channels)
        proxy_tag = "[代理]" if source.get('proxy') else ""
        isp_tag = source.get('isp', 'other')
        log.info(f"  ✓ {source['name']}{proxy_tag}: {len(channels)}个 [{isp_tag}]")
    
    log.info(f"  总计加载: {len(all_channels)} 个频道")
    
    log.info("[2/5] 整合去重...")
    merger = ChannelMerger(dedup_mode=DEDUP_MODE, keep_strategy=DEDUP_KEEP)
    merger.load_blacklist(str(BLACKLIST_FILE))
    merged = merger.merge(all_channels)
    log.info(f"  去重后: {len(merged)} 个频道")
    
    if TEMPLATE_FILE.exists():
        log.info("[3/5] 应用模板...")
        merged = merger.apply_template(merged, str(TEMPLATE_FILE))
    
    log.info(f"[4/5] 测速中... 并发: {MAX_CONCURRENT_TESTS}")
    
    need_test = []
    for ch in merged:
        cached_speed = cache.get(ch.url)
        if cached_speed is not None:
            ch.speed = cached_speed
        else:
            need_test.append(ch)
    
    log.info(f"  缓存命中: {len(merged)-len(need_test)}/{len(merged)}")
    
    if need_test:
        tester = SpeedTester(
            timeout=SPEED_TEST_TIMEOUT,
            duration=SPEED_TEST_DURATION,
            max_concurrent=MAX_CONCURRENT_TESTS
        )
        asyncio.run(tester.test_all(need_test))
        
        for ch in need_test:
            cache.set(ch.url, ch.speed)
        cache.save()
    
    # 移动优先排序
    valid_channels = sort_for_mobile(merged)
    log.info(f"  总频道: {len(valid_channels)}个 (移动+组播优先)")
    
    log.info("[5/5] 导出结果...")
    
    # 按 ISP 分组导出
    M3UExporter.export_by_isp(valid_channels, str(OUTPUT_DIR))
    TXTExporter.export_by_isp(valid_channels, str(OUTPUT_DIR))
    
    # 额外导出移动优先合并版
    M3UExporter.export(valid_channels, str(OUTPUT_DIR / "result-mobile-first.m3u"))
    TXTExporter.export(valid_channels, str(OUTPUT_DIR / "result-mobile-first.txt"))
    
    LogExporter.export_speed_log(valid_channels, str(LOG_DIR / "speed_test.log"))
    
    elapsed = time.time() - start_time
    log.info(f"处理完成! 耗时: {elapsed:.1f}秒")
    log.info(f"输出文件在: {OUTPUT_DIR}")
    log.info(f"  移动优先: result-mobile-first.m3u")


if __name__ == "__main__":
    main()
