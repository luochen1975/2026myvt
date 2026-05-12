import json
import re
import requests
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
        for line in content.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if ',' in line:
                parts = line.split(',', 1)
                name = parts[0].strip()
                url_part = parts[1].strip()
                
                # 过滤掉只有后半段的（前面带逗号）
                if not name or url_part.startswith(','):
                    continue
                
                group = ""
                if '#' in url_part:
                    url, group = url_part.rsplit('#', 1)
                else:
                    url = url_part
                
                # 清洗 $ 后面的垃圾
                if '$' in url:
                    url = url.split('$')[0].strip()
                
                if url and (url.startswith('http') or url.startswith(('udp://', 'rtp://', 'rtsp://'))):
                    channels.append(Channel(name=name, url=url, group=group, source=source))
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
        if not url or not url.startswith('http'):
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
