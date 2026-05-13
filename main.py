#!/usr/bin/env python3
import asyncio
import json
import os
import re
import time
from pathlib import Path
from collections import OrderedDict
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from config.settings import *
from core.parser import SourceLoader
from core.merger import ChannelMerger
from core.speed_tester import SpeedTester
from core.exporter import M3UExporter, TXTExporter, LogExporter
from utils.cache import SpeedCache
from utils.logger import log


# ========== 路径配置 ==========
CONFIG_DIR = Path(__file__).parent / "config"
BLACKLIST_FILE_PATH = CONFIG_DIR / "blacklist.txt"
# ================================


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


def load_blacklist_rules(blacklist_file: str) -> dict:
    rules = {
        'domains': [],
        'contains': [],
        'urls': [],
    }

    if not os.path.exists(blacklist_file):
        log.warning(f"黑名单文件不存在: {blacklist_file}")
        return rules

    with open(blacklist_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if ':' in line:
                rule_type, rule_value = line.split(':', 1)
                rule_type = rule_type.strip().lower()
                rule_value = rule_value.strip()

                if rule_type == 'domain':
                    rules['domains'].append(rule_value)
                    log.debug(f"加载域名黑名单: {rule_value}")
                elif rule_type == 'contains':
                    rules['contains'].append(rule_value)
                    log.debug(f"加载包含规则: {rule_value}")
                else:
                    log.warning(f"未知规则类型 '{rule_type}' 在第 {line_num} 行")
            else:
                rules['urls'].append(line)
                log.debug(f"加载URL黑名单: {line}")

    log.info(f"黑名单规则加载完成: {len(rules['domains'])} 个域名, "
             f"{len(rules['contains'])} 个包含规则, {len(rules['urls'])} 个URL")
    return rules


def should_blacklist(url: str, rules: dict) -> tuple[bool, str]:
    if not url:
        return False, ""

    url_lower = url.lower()
    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    for black_url in rules['urls']:
        if black_url.lower() in url_lower:
            return True, f"匹配URL黑名单: {black_url}"

    for black_domain in rules['domains']:
        if black_domain.lower() in domain:
            return True, f"匹配域名黑名单: {black_domain}"

    for pattern in rules['contains']:
        if pattern.lower() in url_lower:
            return True, f"匹配包含规则: {pattern}"

    return False, ""


def save_blacklist_rule(blacklist_file: str, url: str, name: str, reason: str):
    os.makedirs(os.path.dirname(blacklist_file), exist_ok=True)

    parsed = urlparse(url)

    if '?' in url:
        params = parse_qs(parsed.query)
        for param in params.keys():
            if any(kw in param.lower() for kw in ['token', 'auth', 'sign', 'secret', 'key']):
                rule = f"contains:{param}"
                break
        else:
            rule = f"domain:{parsed.netloc}"
    else:
        rule = f"domain:{parsed.netloc}"

    if os.path.exists(blacklist_file):
        with open(blacklist_file, 'r', encoding='utf-8') as f:
            existing = f.read()
        if rule in existing:
            return False

    with open(blacklist_file, 'a', encoding='utf-8') as f:
        f.write(f"\n# 自动添加 [{time.strftime('%Y-%m-%d %H:%M:%S')}] - {name} - {reason}\n")
        f.write(f"{rule}\n")

    return True


def clean_url(url: str) -> str:
    if not url or '?' not in url:
        return url

    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)

    token_params = [
        'play_token', 'auth_key', 'wsSecret', 'wsTime', 'token',
        'auth', 'sign', 'signature', 'timestamp', 'ts', 't',
        'expires', 'expire', 'e', 'key', 'ak', 'sk',
        'user', 'pass', 'password', 'pwd', 'nonce', 'salt',
        'session', 'sid', 'cookie', 'ck',
        'auth_info', 'security_token', 'x-oss-', 'x-cos-',
        'edge_key', 'cdn_token', 'verify',
    ]

    cleaned_params = {}
    for key, values in params.items():
        key_lower = key.lower()
        should_remove = any(
            tp.lower() in key_lower or key_lower.startswith(tp.lower()) 
            for tp in token_params
        )

        if not should_remove:
            cleaned_params[key] = values

    if cleaned_params:
        new_query = urlencode(cleaned_params, doseq=True)
        new_url = urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, new_query, parsed.fragment
        ))
        return new_url
    else:
        return urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, '', parsed.fragment
        ))


def merge_subgroups(grouped_channels):
    fixed_groups = OrderedDict()

    for group_name, sub_groups in grouped_channels.items():
        all_channels_in_group = []
        for sub_name, chs in sub_groups.items():
            all_channels_in_group.extend(chs)

        seen_urls = {}
        unique_channels = []
        for ch in all_channels_in_group:
            if ch.url not in seen_urls:
                seen_urls[ch.url] = ch
                unique_channels.append(ch)
            else:
                existing = seen_urls[ch.url]
                if ch.speed > existing.speed:
                    seen_urls[ch.url] = ch
                    unique_channels.remove(existing)
                    unique_channels.append(ch)

        unique_channels.sort(key=lambda x: x.speed if x.speed else float('inf'))

        if unique_channels:
            fixed_groups[group_name] = OrderedDict()
            fixed_groups[group_name]['全部'] = unique_channels

    return fixed_groups


# ========== 新增：分组合并功能（移到 main() 外部）==========

def merge_province_groups(grouped_channels):
    """
    合并省份标签：统一各种前缀和后缀变体
    例如：☘️上海 → ❤️上海, ☘️河北频道 → ❤️河北
    """
    provinces = [
        '河北', '北京', '广东', '河南', '新疆', '上海', '安徽', '江苏', 
        '浙江', '四川', '湖北', '湖南', '山东', '山西', '辽宁', '福建',
        '甘肃', '广西', '贵州', '陕西', '江西', '重庆', '云南', '黑龙江',
        '海南', '内蒙古', '天津', '宁夏', '青海', '西藏', '吉林', 
        '澳门', '香港', '台湾'
    ]

    replace_rules = {}
    for prov in provinces:
        target = f'❤️{prov}'
        sources = [
            f'☘️{prov}频道', f'❤️{prov}频道', f'📡{prov}频道',
            f'🌐{prov}频道', f'{prov}频道',
            f'☘️{prov}', f'❤️{prov}', f'📡{prov}', f'🌐{prov}',
        ]
        for src in sources:
            replace_rules[src] = target

    merged = OrderedDict()

    for group_name, sub_groups in grouped_channels.items():
        new_name = replace_rules.get(group_name, group_name)

        if new_name not in merged:
            merged[new_name] = OrderedDict()

        for sub_name, channels in sub_groups.items():
            if sub_name not in merged[new_name]:
                merged[new_name][sub_name] = []
            merged[new_name][sub_name].extend(channels)

    # 去重
    for group_name, sub_groups in merged.items():
        for sub_name, channels in sub_groups.items():
            seen = {}
            unique = []
            for ch in channels:
                if ch.url not in seen:
                    seen[ch.url] = ch
                    unique.append(ch)
                else:
                    existing = seen[ch.url]
                    ch_speed = getattr(ch, 'speed', float('inf'))
                    ex_speed = getattr(existing, 'speed', float('inf'))
                    if ch_speed < ex_speed:
                        seen[ch.url] = ch
                        unique.remove(existing)
                        unique.append(ch)
            unique.sort(key=lambda x: getattr(x, 'speed', float('inf')))
            sub_groups[sub_name] = unique

    return merged


def merge_special_groups(grouped_channels):
    """
    合并特殊分组（非省份分组）
    """
    special_rules = {
        '歌曲': ['❤️歌曲', '歌曲', '🎵歌曲', '☘️歌曲'],
        '剧电影': ['❤️剧电影', '剧电影', '🎬剧电影', '☘️剧电影'],
        '香港台湾': ['🐎🐎⬇️❤️xianggang\\wanwan', '❤️xianggang\\wanwan', 'xianggang\\wanwan'],
        '其他': ['🍉🍉❤️其他1', '❤️其他1', '其他1', '❤️其他', '其他'],
        '央视': ['❤️V4央视', '❤️V6央视', 'V4央视', 'V6央视', '央视'],
        '广播': ['❤️广播', '广播', '📻广播'],
        '移动直播': ['❤️移动直播', '移动直播'],
        '卫视': ['❤️V4卫视', '❤️V6卫视', 'V4卫视', 'V6卫视'],
        '4k8K+': ['❤️4k8K+', '4k8K+'],
    }

    merged = OrderedDict()

    for group_name, sub_groups in grouped_channels.items():
        new_name = group_name

        for target, sources in special_rules.items():
            if group_name in sources:
                new_name = f'❤️{target}'
                break

        if new_name not in merged:
            merged[new_name] = OrderedDict()

        for sub_name, channels in sub_groups.items():
            if sub_name not in merged[new_name]:
                merged[new_name][sub_name] = []
            merged[new_name][sub_name].extend(channels)

    # 去重
    for group_name, sub_groups in merged.items():
        for sub_name, channels in sub_groups.items():
            seen = {}
            unique = []
            for ch in channels:
                if ch.url not in seen:
                    seen[ch.url] = ch
                    unique.append(ch)
                else:
                    existing = seen[ch.url]
                    ch_speed = getattr(ch, 'speed', float('inf'))
                    ex_speed = getattr(existing, 'speed', float('inf'))
                    if ch_speed < ex_speed:
                        seen[ch.url] = ch
                        unique.remove(existing)
                        unique.append(ch)
            unique.sort(key=lambda x: getattr(x, 'speed', float('inf')))
            sub_groups[sub_name] = unique

    return merged


def merge_all_groups(grouped_channels):
    """统一合并所有分组（省份 + 特殊分组）"""
    step1 = merge_province_groups(grouped_channels)
    step2 = merge_special_groups(step1)
    return step2

# =========================================================


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

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

        multicast_count = sum(1 for ch in channels if ch.url.strip().lower().startswith(('udp://', 'rtp://', 'rtsp://')))
        log.info(f"  ✓ {source['name']}{proxy_tag}: {len(channels)}个 [{isp_tag}] (组播:{multicast_count}个)")

    total_multicast = sum(1 for ch in all_channels if ch.url.strip().lower().startswith(('udp://', 'rtp://', 'rtsp://')))
    log.info(f"  总计加载: {len(all_channels)} 个频道 (组播:{total_multicast}个)")

    log.info("[2/5] 加载黑名单规则...")
    blacklist_rules = load_blacklist_rules(str(BLACKLIST_FILE_PATH))

    log.info("[2/5] 应用黑名单过滤...")
    new_blacklist_count = 0
    filtered_channels = []

    for ch in all_channels:
        should_block, reason = should_blacklist(ch.url, blacklist_rules)

        if should_block:
            if save_blacklist_rule(str(BLACKLIST_FILE_PATH), ch.url, ch.name, reason):
                new_blacklist_count += 1
                log.debug(f"新增黑名单: {ch.name} - {reason}")
        else:
            filtered_channels.append(ch)

    if new_blacklist_count > 0:
        log.info(f"  新增黑名单规则: {new_blacklist_count} 条")

    log.info(f"  过滤后: {len(filtered_channels)} 个频道 (移除 {len(all_channels)-len(filtered_channels)} 个)")
    all_channels = filtered_channels

    log.info("[2/5] 整合去重...")
    merger = ChannelMerger(dedup_mode=DEDUP_MODE, keep_strategy=DEDUP_KEEP)
    if BLACKLIST_FILE.exists():
        merger.load_blacklist(str(BLACKLIST_FILE))
    merged = merger.merge(all_channels)

    merged_multicast = sum(1 for ch in merged if ch.url.strip().lower().startswith(('udp://', 'rtp://', 'rtsp://')))
    log.info(f"  去重后: {len(merged)} 个频道 (组播:{merged_multicast}个)")

    grouped_channels = {}
    if TEMPLATE_FILE.exists():
        log.info("[3/5] 应用模板...")
        grouped_channels = merger.apply_template(merged, str(TEMPLATE_FILE))

        log.info("[3/5] 聚合分组...")
        grouped_channels = merge_subgroups(grouped_channels)

        # ========== 合并省份标签（修复：函数已移到外部）==========
        log.info("[3/5] 合并省份标签...")
        grouped_channels = merge_province_groups(grouped_channels)

        log.info("[3/5] 合并特殊分组...")
        grouped_channels = merge_special_groups(grouped_channels)
        # =========================================================

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

    log.info("[5/5] 导出结果...")

    TXTExporter.export_by_template(grouped_channels, str(OUTPUT_DIR / "result.txt"))
    log.info(f"  ✓ TXT 模板导出完成")

    M3UExporter.export_by_template(grouped_channels, str(OUTPUT_DIR))
    log.info(f"  ✓ M3U 模板导出完成")

    M3UExporter.export_all(all_channels_flat, str(OUTPUT_DIR / "result-all.m3u"))
    log.info(f"  ✓ 全部M3U导出完成")

    M3UExporter.export_mobile_first(all_channels_flat, str(OUTPUT_DIR / "result-mobile-first.m3u"))
    TXTExporter.export_mobile_first(all_channels_flat, str(OUTPUT_DIR / "result-mobile-first.txt"))
    log.info(f"  ✓ 移动优先导出完成")

    M3UExporter.export_other(all_channels_flat, str(OUTPUT_DIR / "result-other.m3u"))
    TXTExporter.export_other(all_channels_flat, str(OUTPUT_DIR / "result-other.txt"))
    log.info(f"  ✓ 其他源导出完成")

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
