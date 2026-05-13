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

    if os.getenv('GITHUB_ACTIONS'):
        proxy_sources = [s for s in sources if s.get('proxy')]
        if proxy_sources:
            log.info(f"[GitHub Actions] 跳过 {len(proxy_sources)} 个代理源")
            sources = [s for s in sources if not s.get('proxy')]

    return sources


def main():
    # 确保输出目录存在（GitHub Actions 环境需要）
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

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

        # 统计组播源
        multicast_count = sum(1 for ch in channels if ch.url.strip().lower().startswith(('udp://', 'rtp://', 'rtsp://')))
        log.info(f"  ✓ {source['name']}{proxy_tag}: {len(channels)}个 [{isp_tag}] (组播:{multicast_count}个)")

    # 总统计
    total_multicast = sum(1 for ch in all_channels if ch.url.strip().lower().startswith(('udp://', 'rtp://', 'rtsp://')))
    log.info(f"  总计加载: {len(all_channels)} 个频道 (组播:{total_multicast}个)")

    log.info("[2/5] 整合去重...")
    merger = ChannelMerger(dedup_mode=DEDUP_MODE, keep_strategy=DEDUP_KEEP)
    merger.load_blacklist(str(BLACKLIST_FILE))
    merged = merger.merge(all_channels)

    # 去重后统计
    merged_multicast = sum(1 for ch in merged if ch.url.strip().lower().startswith(('udp://', 'rtp://', 'rtsp://')))
    log.info(f"  去重后: {len(merged)} 个频道 (组播:{merged_multicast}个)")

    # 3. 应用模板
    grouped_channels = {}
    if TEMPLATE_FILE.exists():
        log.info("[3/5] 应用模板...")
        grouped_channels = merger.apply_template(merged, str(TEMPLATE_FILE))

        # 调试：打印分组结果
        log.info("=== 频道分组诊断 ===")
        for group_name, sub_groups in grouped_channels.items():
            total = sum(len(chs) for chs in sub_groups.values())
            if total > 0:
                log.info(f"  分组 '{group_name}': {total} 个频道")
                for sub_name, chs in sub_groups.items():
                    if len(chs) > 0:
                        sample = chs[0].name if chs else "空"
                        log.info(f"    - {sub_name}: {len(chs)} 个 (示例: {sample})")
    else:
        grouped_channels = {'其他': {'未分类': merged}}

    # 4. 测速
    log.info(f"[4/5] 测速中... 并发: {MAX_CONCURRENT_TESTS}")

    all_channels_flat = []
    for group in grouped_channels.values():
        for sub_group in group.values():
            all_channels_flat.extend(sub_group)

    need_test = []
    for ch in all_channels_flat:
        cached_speed = cache.get(ch.url)
        if cached_speed is not None:
            ch.speed = cached_speed
        else:
            need_test.append(ch)

    log.info(f"  缓存命中: {len(all_channels_flat)-len(need_test)}/{len(all_channels_flat)}")

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

    log.info(f"  总频道: {len(all_channels_flat)}个")

    # 5. 按模板分组导出 + ISP分组导出
    log.info("[5/5] 导出结果...")

    # 按模板分组导出（原有）
    TXTExporter.export_by_template(grouped_channels, str(OUTPUT_DIR / "result.txt"))
    log.info(f"  ✓ TXT 模板导出完成")

    M3UExporter.export_by_template(grouped_channels, str(OUTPUT_DIR))
    log.info(f"  ✓ M3U 模板导出完成")

    # 按ISP分组导出（新增）
    # 全部频道
    M3UExporter.export_all(all_channels_flat, str(OUTPUT_DIR / "result-all.m3u"))
    log.info(f"  ✓ 全部M3U导出完成")

    # 移动优先
    M3UExporter.export_mobile_first(all_channels_flat, str(OUTPUT_DIR / "result-mobile-first.m3u"))
    TXTExporter.export_mobile_first(all_channels_flat, str(OUTPUT_DIR / "result-mobile-first.txt"))
    log.info(f"  ✓ 移动优先导出完成")

    # 其他源
    M3UExporter.export_other(all_channels_flat, str(OUTPUT_DIR / "result-other.m3u"))
    TXTExporter.export_other(all_channels_flat, str(OUTPUT_DIR / "result-other.txt"))
    log.info(f"  ✓ 其他源导出完成")

    # 速度日志
    LogExporter.export_speed_log(all_channels_flat, str(LOG_DIR / "speed_test.log"))
    log.info(f"  ✓ 测速日志导出完成")

    elapsed = time.time() - start_time
    log.info(f"处理完成，耗时: {elapsed:.1f}秒")
    log.info("=" * 50)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log.error(f"运行出错: {e}")
        import traceback
        traceback.print_exc()
        raise
