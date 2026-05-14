import json
import re
import requests
from pathlib import Path
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import List, Optional, Dict

from config.settings import PROXY_ENABLED, PROXY_URL, USER_AGENT


@dataclass
class Channel:
    name: str
    url: str
    group: str = ""
    logo: str = ""
    tvg_id: str = ""
    tvg_name: str = ""
    extra: Dict = None
    source: str = ""
    speed: float = 0.0

    def __post_init__(self):
        if self.extra is None:
            self.extra = {}


class M3UParser:
    @staticmethod
    def parse(content: str, source: str = "") -> List[Channel]:
        channels = []
        lines = content.strip().split('\n')
        current_meta = {}

        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue

            if line.startswith('#EXTINF:'):
                current_meta = M3UParser._parse_extinf(line)
            elif line.startswith('#EXTGRP:'):
                current_meta['group'] = line[8:].strip()
            elif not line.startswith('#') and current_meta:
                channel = Channel(
                    name=current_meta.get('name', 'Unknown'),
                    url=line,
                    group=current_meta.get('group', ''),
                    logo=current_meta.get('logo', ''),
                    tvg_id=current_meta.get('tvg_id', ''),
                    tvg_name=current_meta.get('tvg_name', ''),
                    source=source,
                    extra=current_meta
                )
                channels.append(channel)
                current_meta = {}

        return channels

    @staticmethod
    def _parse_extinf(line: str) -> dict:
        meta = {}
        if ',' in line:
            meta['name'] = line.split(',', 1)[1].strip()
        attrs = re.findall(r'([a-zA-Z-]+)="([^"]*)"', line)
        for key, value in attrs:
            key = key.replace('-', '_').lower()
            if key == 'group_title':
                meta['group'] = value
            elif key == 'tvg_logo':
                meta['logo'] = value
            else:
                meta[key] = value
        return meta


class TXTParser:
    @staticmethod
    def parse(content: str, source: str = "") -> List[Channel]:
        channels = []
        current_group = ""

        for line in content.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # 分组标题行: "央视,#genre#" 或 "央视, #genre#"
            if ',#genre#' in line or ', #genre#' in line:
                parts = line.split(',', 1)
                current_group = parts[0].strip()
                continue

            # 普通频道行: "CCTV-1,http://..."
            if ',' in line:
                parts = line.split(',', 1)
                name = parts[0].strip()
                url_part = parts[1].strip()

                # 过滤掉只有后半段的（前面带逗号）
                if not name or url_part.startswith(','):
                    continue

                # 提取 URL 和附加分组
                group = current_group  # 使用当前分组
                if '#' in url_part:
                    url, extra_group = url_part.rsplit('#', 1)
                    url = url.strip()
                    if extra_group.strip():
                        group = extra_group.strip()  # URL后面的#分组优先
                else:
                    url = url_part

                # 清洗 $ 后面的垃圾
                if '$' in url:
                    url = url.split('$')[0].strip()

                # 确保组播地址不被过滤
                url = url.strip()
                if url and (url.startswith('http') or url.startswith(('udp://', 'rtp://', 'rtsp://', 'UDP://', 'RTP://', 'RTSP://'))):
                    channels.append(Channel(
                        name=name, 
                        url=url, 
                        group=group, 
                        source=source
                    ))

        return channels


class JSONParser:
    @staticmethod
    def parse(content: str, source: str = "") -> List[Channel]:
        channels = []
        data = json.loads(content)
        if isinstance(data, list):
            for item in data:
                ch = JSONParser._item_to_channel(item, source)
                if ch:
                    channels.append(ch)
        elif isinstance(data, dict):
            items = data.get('channels', data.get('list', []))
            for item in items:
                ch = JSONParser._item_to_channel(item, source)
                if ch:
                    channels.append(ch)
        return channels

    @staticmethod
    def _item_to_channel(item: dict, source: str) -> Optional[Channel]:
        if not isinstance(item, dict):
            return None
        url = item.get('url', item.get('link', item.get('address', '')))
        if not url or not (url.startswith('http') or url.startswith(('udp://', 'rtp://', 'rtsp://'))):
            return None
        return Channel(
            name=item.get('name', item.get('title', 'Unknown')),
            url=url,
            group=item.get('group', item.get('category', '')),
            logo=item.get('logo', item.get('icon', '')),
            tvg_id=item.get('tvg_id', ''),
            source=source,
            extra=item
        )


# ========== 新增：blacklist.txt 支持 ==========

# blacklist.txt 路径：parser.py 在 core/，向上退一级到项目根目录，再进 config/
BLACKLIST_FILE = Path(__file__).parent.parent / "config" / "blacklist.txt"


def load_blacklist_rules() -> dict:
    """
    加载 config/blacklist.txt 规则文件
    支持规则类型：
        domain:    域名黑名单（匹配 URL 域名部分）
        contains:  包含黑名单（匹配 URL 包含的字符串）
        genre:     【新增】genre 分组黑名单（匹配 TXT 的 #genre# 分组名）
        keyword:   【新增】单行关键词黑名单（匹配任意行内容）
    """
    rules = {
        'domains': [],
        'contains': [],
        'urls': [],
        'genres': [],      # ← 新增：genre 分组黑名单
        'keywords': [],    # ← 新增：单行关键词黑名单
    }

    if not BLACKLIST_FILE.exists():
        return rules  # 文件不存在则返回空规则

    with open(BLACKLIST_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if ':' in line:
                rule_type, rule_value = line.split(':', 1)
                rule_type = rule_type.strip().lower()
                rule_value = rule_value.strip()

                if rule_type == 'domain':
                    rules['domains'].append(rule_value)
                elif rule_type == 'contains':
                    rules['contains'].append(rule_value)
                # ========== 新增规则类型 ==========
                elif rule_type == 'genre':
                    rules['genres'].append(rule_value)
                elif rule_type == 'keyword':
                    rules['keywords'].append(rule_value)
                # ==================================
            else:
                rules['urls'].append(line)

    return rules


def filter_genre(text: str, genres: list) -> str:
    """
    【genre 分组过滤】
    作用：剔除 TXT 格式中指定的整个 #genre# 分组及其下所有频道
    
    在 blacklist.txt 中配置：
        genre:广播电台RADIO    ← 过滤"广播电台RADIO"整个分组
        genre:购物             ← 过滤"购物"整个分组
        genre:少儿             ← 过滤"少儿"整个分组
    
    匹配方式：包含匹配，如 "广播" 匹配 "广播电台RADIO,#genre#"
    适用格式：仅 TXT（M3U/JSON 无 #genre# 行，自动跳过）
    """
    if not genres:
        return text
    out, skip = [], False
    for line in text.strip().split('\n'):
        stripped = line.strip()
        # 检测 genre 分组标题行，如 "广播电台RADIO,#genre#"
        if stripped.endswith(',#genre#'):
            # 判断该 genre 名称是否包含在过滤列表中
            skip = any(g in stripped for g in genres)
            if skip:
                continue  # 跳过该 genre 行，不输出
        # 非 genre 行，根据 skip 状态决定是否保留
        if not skip:
            out.append(line)
    return '\n'.join(out) + '\n'


def filter_keyword(text: str, keywords: list) -> str:
    """
    【单行关键词过滤】
    作用：剔除包含指定关键词的任意行（频道行或分组行）
    
    在 blacklist.txt 中配置：
        keyword:测试           ← 过滤包含"测试"的行
        keyword:体验           ← 过滤包含"体验"的行
        keyword:高清           ← 过滤包含"高清"的行
    
    匹配方式：包含匹配，对所有格式（TXT/M3U/JSON）有效
    注意：大小写敏感
    """
    if not keywords:
        return text
    return '\n'.join(l for l in text.strip().split('\n') 
                    if not any(k in l for k in keywords)) + '\n'


def apply_blacklist_filter(text: str, rules: dict) -> str:
    """
    应用 blacklist 规则过滤原始文本
    在 SourceLoader.load() 解析前调用
    """
    # 先按 genre 过滤（仅 TXT 有效，M3U/JSON 无 #genre# 行）
    if rules.get('genres'):
        text = filter_genre(text, rules['genres'])
    
    # 再按关键词过滤单行（所有格式通用）
    if rules.get('keywords'):
        text = filter_keyword(text, rules['keywords'])
    
    return text


# ========== SourceLoader（增加自动加载 blacklist）==========

class SourceLoader:
    PARSERS = {
        'txt': TXTParser,
        'm3u': M3UParser,
        'm3u8': M3UParser,
        'json': JSONParser
    }

    @staticmethod
    def load(source_config: dict) -> List[Channel]:
        name = source_config.get('name', 'unknown')
        url = source_config['url']
        file_type = source_config.get('type', 'm3u').lower()
        use_proxy = source_config.get('proxy', False)

        try:
            content = SourceLoader._fetch_content(url, use_proxy)
            
            # ========== 新增：自动加载并应用 blacklist ==========
            # 无需修改 main.py，parser.py 自己读取 config/blacklist.txt
            # 支持规则：
            #   genre:xxx    → 过滤 TXT 的 #genre# 分组
            #   keyword:xxx  → 过滤包含关键词的单行
            # ================================================
            blacklist_rules = load_blacklist_rules()
            content = apply_blacklist_filter(content, blacklist_rules)
            # ==================================================
            
            parser = SourceLoader.PARSERS.get(file_type, M3UParser)
            channels = parser.parse(content, source=name)

            isp = source_config.get('isp', 'other')
            for ch in channels:
                ch.extra['isp'] = isp

            return channels
        except Exception as e:
            print(f"[ERROR] 加载源 {name} 失败: {e}")
            return []

    @staticmethod
    def _fetch_content(url: str, use_proxy: bool = False) -> str:
        proxies = None
        if use_proxy and PROXY_ENABLED:
            proxies = {
                'http': PROXY_URL,
                'https': PROXY_URL
            }

        if url.startswith('http'):
            headers = {'User-Agent': USER_AGENT}
            resp = requests.get(url, headers=headers, timeout=30, proxies=proxies)
            resp.raise_for_status()

            # 尝试多种编码解码
            content_bytes = resp.content
            for enc in ['utf-8', 'gbk', 'gb2312', 'big5']:
                try:
                    return content_bytes.decode(enc)
                except UnicodeDecodeError:
                    continue

            # 都失败则忽略错误字符
            return content_bytes.decode('utf-8', errors='ignore')
        else:
            with open(url, 'r', encoding='utf-8') as f:
                return f.read()
