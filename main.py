#!/usr/bin/env python3
import asyncio
import json
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
    """根据 URL 后缀自动识别格式"""
    url_lower = url.lower()
    if url_lower.endswith(('.m3u', '.m3u8')):
        return 'm3u'
    elif url_lower.endswith('.json'):
        return 'json'
    else:
        return 'txt'


def load_sources() -> list:
    """加载源配置，支持多种格式自动识别"""
    with open(SOURCES_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    sources = []
    
    # 方式一：纯 URL 列表 ["https://a.com/zb.txt", ...]
    if isinstance(config, list):
        for item in config:
            if isinstance(item, str):
                url = item.strip()
                sources.append({
                    'name': 'auto',
                    'url': url,
                    'type': auto_detect_type(url),
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
                        'enabled': True
                    })
    
    # 方式二：分组格式 {"txt": [...], "m3u": [...]}
    elif isinstance(config, dict):
        for file_type, items in config.items():
            for item in items:
                if isinstance(item, str):
                    url = item.strip()
                    sources.append({
                        'name': 'auto',
                        'url': url,
                        'type': file_type,
                        'enabled': True
                    })
                elif isinstance(item, dict) and item.get('enabled', True):
                    sources.append({
                        'name': item.get('name', 'auto'),
                        'url': item['url'],
                        'type': file_type,
                        'enabled': True
                    })
    
    return sources


def main():
    log.info("=" * 50)
    log.info("IPTV 源处理器启动")
    
    start_time = time.time()
    cache = SpeedCache(str(CACHE_FILE), ttl=CACHE_TTL_HOURS * 3600)
    
    # 1. 加载所有源
    log.info("[1/5] 加载订阅源...")
    sources = load_sources()
    all_channels = []
    
    for source in sources:
        channels = SourceLoader.load(source)
        all_channels.extend(channels)
        log.info(f"  ✓ {source['name']}: {len(channels)} 个频道 ({source['type']})")
    
    log.info(f"  总计加载: {len(all_channels)} 个频道")
    
    # 2. 整合去重
    log.info("[2/5] 整合去重...")
    merger = ChannelMerger(dedup_mode=DEDUP_MODE, keep_strategy=DEDUP_KEEP)
    merger.load_blacklist(str(BLACKLIST_FILE))
    merged = merger.merge(all_channels)
    log.info(f"  去重后: {len(merged)} 个频道")
    
    # 3. 应用模板（如果有）
    if TEMPLATE_FILE.exists():
        log.info("[3/5] 应用模板...")
        merged = merger.apply_template(merged, str(TEMPLATE_FILE))
    
    # 4. 测速（带缓存）
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
    
    # 过滤低速源
    valid_channels = [ch for ch in merged if ch.speed >= MIN_SPEED_KBPS]
    log.info(f"  有效频道: {len(valid_channels)}/{len(merged)} (≥{MIN_SPEED_KBPS}KB/s)")
    
    # 5. 导出结果
    log.info("[5/5] 导出结果...")
    M3UExporter.export(valid_channels, str(OUTPUT_M3U))
    TXTExporter.export(valid_channels, str(OUTPUT_TXT), include_speed=True)
    LogExporter.export_speed_log(valid_channels, str(LOG_DIR / "speed_test.log"))
    
    elapsed = time.time() - start_time
    log.info(f"处理完成! 耗时: {elapsed:.1f}秒")
    log.info(f"输出: {OUTPUT_M3U}, {OUTPUT_TXT}")


if __name__ == "__main__":
    main()