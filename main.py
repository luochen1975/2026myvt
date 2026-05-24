#!/usr/bin/env python3
"""
IPTV源处理器 - 优化版
浙江宁波移动网络专用
分层测速：组播(ffmpeg) / 国内(aiohttp) / 外网(Clash代理+aiohttp)
"""
import asyncio
import json
import os
import re
import time
from pathlib import Path
from collections import OrderedDict
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

os.environ["TZ"] = "Asia/Shanghai"
time.tzset()

from config.settings import *
from core.parser import SourceLoader
from core.merger import ChannelMerger, auto_group_by_name
from core.speed_tester import SpeedTester
from core.exporter import M3UExporter, TXTExporter, LogExporter
from utils.cache import SpeedCache
from utils.logger import log


CONFIG_DIR = Path(__file__).parent / "config"
BLACKLIST_FILE_PATH = CONFIG_DIR / "blacklist.txt"


def auto_detect_type(url: str) -> str:
    url_lower = url.lower()
    if url_lower.endswith((".m3u", ".m3u8")):
        return "m3u"
    elif url_lower.endswith(".json"):
        return "json"
    return "txt"


def load_sources() -> list:
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    sources = []

    def add_item(item):
        if isinstance(item, str):
            url = item.strip()
            sources.append({
                "name": "auto", "url": url,
                "type": auto_detect_type(url), "isp": "other",
                "proxy": False, "enabled": True
            })
        elif isinstance(item, dict):
            if item.get("enabled", True):
                sources.append({
                    "name": item.get("name", "auto"),
                    "url": item["url"],
                    "type": item.get("type") or auto_detect_type(item["url"]),
                    "isp": item.get("isp", "other"),
                    "proxy": item.get("proxy", False),
                    "enabled": True
                })

    if isinstance(config, list):
        for item in config:
            add_item(item)
    elif isinstance(config, dict):
        for file_type, items in config.items():
            for item in items:
                add_item(item)

    if os.getenv("GITHUB_ACTIONS"):
        proxy_sources = [s for s in sources if s.get("proxy")]
        if proxy_sources:
            log.info(f"[GitHub Actions] 跳过 {len(proxy_sources)} 个代理源")
            sources = [s for s in sources if not s.get("proxy")]

    return sources


def load_blacklist_rules(blacklist_file: str) -> dict:
    rules = {
        "domains": [], "contains": [], "urls": [],
        "keywords": [], "regex": [], "genre": []
    }

    if not os.path.exists(blacklist_file):
        log.warning(f"黑名单文件不存在: {blacklist_file}")
        return rules

    with open(blacklist_file, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if ":" in line:
                rule_type, rule_value = line.split(":", 1)
                rule_type = rule_type.strip().lower()
                rule_value = rule_value.strip()

                if rule_type == "domain":
                    rules["domains"].append(rule_value)
                elif rule_type == "contains":
                    rules["contains"].append(rule_value)
                elif rule_type == "keyword":
                    rules["keywords"].append(rule_value)
                elif rule_type == "regex":
                    try:
                        rules["regex"].append(re.compile(rule_value))
                    except re.error as e:
                        log.warning(f"正则错误 第{line_num}行: {e}")
                elif rule_type == "genre":
                    rules["genre"].append(rule_value)
            else:
                rules["urls"].append(line)

    return rules


def should_blacklist(url: str, rules: dict) -> tuple[bool, str]:
    if not url:
        return False, ""
    url_lower = url.lower()
    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    for black_url in rules["urls"]:
        if black_url.lower() in url_lower:
            return True, f"URL黑名单:{black_url}"
    for black_domain in rules["domains"]:
        if black_domain.lower() in domain:
            return True, f"域名黑名单:{black_domain}"
    for pattern in rules["contains"]:
        if pattern.lower() in url_lower:
            return True, f"包含规则:{pattern}"
    for keyword in rules["keywords"]:
        if keyword.lower() in url_lower:
            return True, f"关键词:{keyword}"
    for regex in rules["regex"]:
        if regex.search(url):
            return True, f"正则:{regex.pattern}"
    return False, ""


def clean_url(url: str) -> str:
    """清洗URL用于去重对比"""
    if not url or "?" not in url:
        return url
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    cleaned = {
        k: v for k, v in params.items()
        if not any(tp.lower() in k.lower() or k.lower().startswith(tp.lower())
                   for tp in ["play_token", "auth_key", "wsSecret", "wsTime", "token",
                             "auth", "sign", "signature", "timestamp", "ts", "t",
                             "expires", "expire", "e", "key", "ak", "sk"])
    }
    new_query = urlencode(cleaned, doseq=True) if cleaned else ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    log.info("=" * 50)
    log.info("IPTV 源处理器启动 [优化版 - 分层测速]")

    if os.getenv("GITHUB_ACTIONS"):
        log.info("[环境] GitHub Actions (跳过代理源)")
    else:
        log.info("[环境] 本地运行 [浙江宁波移动]")

    start_time = time.time()
    cache = SpeedCache(str(CACHE_FILE), ttl=CACHE_TTL_HOURS * 3600)
    cache_stats = cache.stats()
    log.info(f"[缓存] 总计:{cache_stats['total']} 有效:{cache_stats['valid']} 失败:{cache_stats['failed']}")

    # ========== 1. 加载源 ==========
    log.info("[1/6] 加载订阅源...")
    sources = load_sources()
    all_channels = []

    for source in sources:
        channels = SourceLoader.load(source)
        for ch in channels:
            ch.source = source.get("name", "unknown")
            ch.extra["isp"] = source.get("isp", "other")
        all_channels.extend(channels)
        mc_count = sum(1 for c in channels if c.url.strip().lower().startswith(("udp://", "rtp://", "rtsp://")))
        proxy_tag = "[代理]" if source.get("proxy") else ""
        log.info(f"  ✓ {source['name']}{proxy_tag}: {len(channels)}个 (组播:{mc_count}个)")

    total_mc = sum(1 for c in all_channels if c.url.strip().lower().startswith(("udp://", "rtp://", "rtsp://")))
    log.info(f"  总计: {len(all_channels)}个频道 (组播:{total_mc}个)")

    # ========== 2. 黑名单过滤 ==========
    log.info("[2/6] 黑名单过滤...")
    blacklist_rules = load_blacklist_rules(str(BLACKLIST_FILE_PATH))
    filtered = []
    blocked = 0
    for ch in all_channels:
        is_block, reason = should_blacklist(ch.url, blacklist_rules)
        if is_block:
            blocked += 1
        else:
            filtered.append(ch)
    log.info(f"  过滤后: {len(filtered)}个 (移除{blocked}个)")

    # ========== 3. 去重（不限制数量！）==========
    log.info("[3/6] URL去重...")
    merger = ChannelMerger(
        multicast_limit=MULTICAST_LIMIT,
        mobile_multicast_limit=MOBILE_MULTICAST_LIMIT,
        unicast_limit=UNICAST_LIMIT,
        max_per_group=MAX_PER_GROUP
    )
    deduped = merger.merge(filtered)
    log.info(f"  去重后: {len(deduped)}个唯一URL")

    # ========== 4. 测速（关键步骤 - 分层测速）==========
    log.info("[4/6] 分层测速...")

    # 构建 source_configs 映射
    source_configs = {}
    for source in sources:
        try:
            chs = SourceLoader.load(source)
            for ch in chs:
                source_configs[ch.url] = source
        except:
            pass

    # 判断港澳台/国外频道
    def is_oversea(ch):
        name = ch.name.lower()
        url = ch.url.lower()
        keywords = [
            "香港", "澳门", "台湾", "tvb", "翡翠", "明珠", "凤凰", "东森", "中天",
            "三立", "民视", "台视", "中视", "华视", "公视", "纬来", "非凡", "年代",
            "tvbs", "viutv", "now", "rthk", "澳视", "澳亚", "澳广视", "澳门莲花",
            "hbo", "cnn", "bbc", "discovery", "fox", "espn", "nhk", "disney",
            "macau", "hong kong", "taiwan", "kbs", "mbc", "abc", "cbs", "nbc",
            "pbs", "sky", "eurosport", "france", "germany", "italy", "spain",
            "russia", "japan", "korea", "usa", "uk", "america", "europe",
            "star movies", "star world", "national geographic", "animal planet",
            "cartoon network", "al jazeera", "deutsche welle", "cgtn", "wowow",
            "fuji tv", "tv asahi", "tv tokyo", "ntv", "sbs", "tbs", "trutv",
            "comedy central", "adult swim", "boomerang", "msnbc", "fox news",
            "bbc world", "france 24", "bein sports", "sky sports", "bt sport",
            "star sports", "fox sports", "showtime", "starz", "epix", "tnt",
            "cinemax", "mtv", "tlc", "pixar", "marvel", "star wars"
        ]
        return any(kw in name or kw in url for kw in keywords)

    need_test = []
    cached_ok = 0
    cached_fail = 0

    for ch in deduped:
        cached = cache.get(ch.url)
        if cached == SpeedCache.FAIL_MARKER:
            ch.speed = None
            cached_fail += 1
        elif cached is not None:
            ch.speed = cached
            cached_ok += 1
        else:
            need_test.append(ch)

    log.info(f"  缓存命中: 成功{cached_ok} 失败{cached_fail} 待测{len(need_test)}")

    if need_test:
        tester = SpeedTester(
            timeout=SPEED_TEST_TIMEOUT,
            duration=SPEED_TEST_DURATION,
            max_concurrent=MAX_CONCURRENT_TESTS
        )

        # 分离港澳台/国外频道
        normal_channels = [c for c in need_test if not is_oversea(c)]
        special_channels = [c for c in need_test if is_oversea(c)]

        log.info(f"  普通频道: {len(normal_channels)}个, 港澳台/国外: {len(special_channels)}个")

        # 普通频道：按原配置测速
        if normal_channels:
            log.info("  普通频道测速...")
            asyncio.run(tester.test_all(normal_channels, source_configs))

        # 港澳台/国外频道：先直连，失败再代理
        if special_channels:
            log.info("  港澳台/国外频道：先直连测速...")
            # 第一轮：强制直连（proxy=False）
            direct_configs = {}
            for ch in special_channels:
                cfg = dict(source_configs.get(ch.url, {
                    "name": "auto", "url": ch.url, "type": "txt",
                    "isp": "other", "proxy": False, "enabled": True
                }))
                cfg["proxy"] = False
                direct_configs[ch.url] = cfg

            asyncio.run(tester.test_all(special_channels, direct_configs))

            # 找出直连失败的
            failed_special = [c for c in special_channels if c.speed is None]
            if failed_special:
                log.info(f"  港澳台/国外直连失败 {len(failed_special)} 个，切换代理重测...")
                # 第二轮：强制代理
                proxy_configs = {}
                for ch in failed_special:
                    cfg = dict(source_configs.get(ch.url, {
                        "name": "auto", "url": ch.url, "type": "txt",
                        "isp": "other", "proxy": True, "enabled": True
                    }))
                    cfg["proxy"] = True
                    proxy_configs[ch.url] = cfg

                asyncio.run(tester.test_all(failed_special, proxy_configs))
            else:
                log.info("  港澳台/国外频道直连全部通过")

        # 保存缓存
        for ch in need_test:
            cache.set(ch.url, ch.speed)
        cache.save()

        tested_ok = sum(1 for c in need_test if c.speed is not None)
        tested_fail = len(need_test) - tested_ok
        log.info(f"  测速结果: 成功{tested_ok} 失败{tested_fail}")
    # ========== 5. 按类型限制数量（测速后！）==========
    log.info("[5/6] 按类型限制数量...")

    limited = merger.limit_by_type(deduped)

    mc_kept = sum(1 for c in limited if c.url.strip().lower().startswith(("udp://", "rtp://", "rtsp://")))
    log.info(f"  限制后: {len(limited)}个 (组播:{mc_kept}个)")

    # ========== 6. 分组与导出 ==========
    log.info("[6/6] 分组与导出...")

    # 自动分组
    grouped = auto_group_by_name(limited)

    # 每组内限制数量并排序
    final_groups = OrderedDict()
    for group_name, sub_groups in grouped.items():
        all_chs = []
        for chs in sub_groups.values():
            all_chs.extend(chs)

        if not all_chs:
            continue

        # 组内去重
        seen = set()
        unique = []
        for ch in all_chs:
            if ch.url not in seen:
                seen.add(ch.url)
                unique.append(ch)

        # 限制每组数量（按速度）
        limited_group = merger.limit_by_group(unique)

        # 排序：组播在前（内网源优先），然后按速度
        def sort_key(ch):
            is_mc = ch.url.strip().lower().startswith(("udp://", "rtp://", "rtsp://"))
            speed = ch.speed if ch.speed is not None else 999999
            return (-int(is_mc), -speed)

        limited_group.sort(key=sort_key)

        final_groups[group_name] = OrderedDict()
        final_groups[group_name]["全部"] = limited_group

    # 导出
    log.info("  导出结果...")
    TXTExporter.export_by_template(final_groups, str(OUTPUT_DIR / "result.txt"))
    M3UExporter.export_by_template(final_groups, str(OUTPUT_DIR))

    # 全部频道（调试用）
    M3UExporter.export_all(deduped, str(OUTPUT_DIR / "result-all.m3u"))

    # 移动优先
    mobile_first = sorted(
        [c for c in deduped if c.speed is not None],
        key=lambda x: x.speed if x.speed is not None else 0,
        reverse=True
    )
    M3UExporter.export_mobile_first(mobile_first, str(OUTPUT_DIR / "result-mobile-first.m3u"))
    TXTExporter.export_mobile_first(mobile_first, str(OUTPUT_DIR / "result-mobile-first.txt"))

    # 测速日志
    LogExporter.export_speed_log(deduped, str(LOG_DIR / "speed_test.log"))

    elapsed = time.time() - start_time
    log.info(f"处理完成，耗时: {elapsed:.1f}秒")
    log.info("=" * 50)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error(f"运行出错: {e}")
        import traceback
        traceback.print_exc()
        raise
