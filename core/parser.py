import json
import re
import requests
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import List, Optional, Dict

@dataclass
class Channel:
    name: str
    url: str
    group: str = ""
    logo: str = ""
    tvg_id: str = ""
    tvg_name: str = ""
    extra: Dict = None
    source: str = ""      # 来源标识
    speed: float = 0.0    # 测速结果(KB/s)
    
    def __post_init__(self):
        if self.extra is None:
            self.extra = {}

class M3UParser:
    """M3U/M3U8 解析器"""
    
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
                # 解析 EXTINF 行
                current_meta = M3UParser._parse_extinf(line)
                
            elif line.startswith('#EXTGRP:'):
                current_meta['group'] = line[8:].strip()
                
            elif not line.startswith('#') and current_meta:
                # URL行
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
        """解析 #EXTINF 元数据"""
        meta = {}
        
        # 提取名称（逗号后）
        if ',' in line:
            meta['name'] = line.split(',', 1)[1].strip()
        
        # 提取属性
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
    """TXT 格式解析器 (名称,URL 或 名称,URL#分组)"""
    
    @staticmethod
    def parse(content: str, source: str = "") -> List[Channel]:
        channels = []
        
        for line in content.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
                
            # 格式: 频道名,http://... 或 频道名,http://...#分组
            if ',' in line:
                parts = line.split(',', 1)
                name = parts[0].strip()
                url_part = parts[1].strip()
                
                # 检查是否有分组标记
                group = ""
                if '#' in url_part:
                    url, group = url_part.rsplit('#', 1)
                else:
                    url = url_part
                
                if url.startswith('http'):
                    channels.append(Channel(
                        name=name,
                        url=url,
                        group=group,
                        source=source
                    ))
                    
        return channels

class JSONParser:
    """JSON 格式解析器"""
    
    @staticmethod
    def parse(content: str, source: str = "") -> List[Channel]:
        channels = []
        data = json.loads(content)
        
        # 支持多种JSON结构
        if isinstance(data, list):
            for item in data:
                ch = JSONParser._item_to_channel(item, source)
                if ch:
                    channels.append(ch)
        elif isinstance(data, dict):
            # 可能是 {"channels": [...]} 结构
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
    """统一源加载器"""
    
    PARSERS = {
        'm3u': M3UParser,
        'm3u8': M3UParser,
        'txt': TXTParser,
        'json': JSONParser
    }
    
    @staticmethod
    def load(source_config: dict) -> List[Channel]:
        name = source_config.get('name', 'unknown')
        url = source_config['url']
        file_type = source_config.get('type', 'm3u').lower()
        
        try:
            content = SourceLoader._fetch_content(url)
            parser = SourceLoader.PARSERS.get(file_type, M3UParser)
            return parser.parse(content, source=name)
        except Exception as e:
            print(f"[ERROR] 加载源 {name} 失败: {e}")
            return []
    
    @staticmethod
    def _fetch_content(url: str) -> str:
        if url.startswith('http'):
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.text
        else:
            # 本地文件
            with open(url, 'r', encoding='utf-8') as f:
                return f.read()