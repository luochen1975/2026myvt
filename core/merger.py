import hashlib
import re
import fnmatch
from typing import List, Dict
from collections import defaultdict
from core.parser import Channel

class ChannelMerger:
    """频道整合去重器"""
    
    def __init__(self, dedup_mode: str = "url_fingerprint", keep_strategy: str = "fastest"):
        self.dedup_mode = dedup_mode
        self.keep_strategy = keep_strategy
        self.blacklist = set()
        self.multicast_limit = 4
    
    def load_blacklist(self, blacklist_file: str):
        try:
            with open(blacklist_file, 'r') as f:
                self.blacklist = {line.strip() for line in f if line.strip() and not line.startswith('#')}
        except FileNotFoundError:
            pass
    
    def _normalize_name(self, name: str) -> str:
        """名称标准化：统一别名、去空格、转小写"""
        name = re.sub(r'\s+', '', name).lower()
        
        # 别名映射
        aliases = {
            'brtv': '北京',
            'hunantv': '湖南',
            'zjtv': '浙江',
            'jstv': '江苏',
        }
        
        for old, new in aliases.items():
            name = name.replace(old, new)
        
        return name
    
    def merge(self, all_channels: List[Channel]) -> List[Channel]:
        filtered = self._filter_blacklist(all_channels)
        name_groups = self._group_by_name(filtered)
        
        result = []
        for name, channels in name_groups.items():
            selected = self._select_by_type(channels)
            result.extend(selected)
        
        result.sort(key=lambda c: (c.group, c.name))
        return result
    
    def _filter_blacklist(self, channels: List[Channel]) -> List[Channel]:
        return [
            ch for ch in channels 
            if not any(black in ch.url for black in self.blacklist)
        ]
    
    def _group_by_name(self, channels: List[Channel]) -> Dict[str, List[Channel]]:
        groups = defaultdict(list)
        for ch in channels:
            key = self._normalize_name(ch.name)
            groups[key].append(ch)
        return dict(groups)
    
    def _is_multicast(self, url: str) -> bool:
        return url.startswith(('udp://', 'rtp://', 'rtsp://'))
    
    def _select_by_type(self, channels: List[Channel]) -> List[Channel]:
        multicast = [c for c in channels if self._is_multicast(c.url)]
        unicast = [c for c in channels if not self._is_multicast(c.url)]
        
        selected = []
        
        if multicast:
            multicast.sort(key=lambda c: c.speed, reverse=True)
            selected.extend(multicast[:self.multicast_limit])
            if len(multicast) > self.multicast_limit:
                print(f"  [组播去重] {channels[0].name}: {len(multicast)}个→{self.multicast_limit}个")
        
        selected.extend(unicast)
        return selected
    
    def apply_template(self, channels: List[Channel], template_file: str) -> List[Channel]:
        try:
            with open(template_file, 'r', encoding='utf-8') as f:
                template_lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        except FileNotFoundError:
            return channels
        
        result = []
        used = set()
        
        for pattern in template_lines:
            matched = []
            for ch in channels:
                if id(ch) in used:
                    continue
                
                # 模板匹配时也用标准化名称
                names = [ch.name, ch.tvg_name] if ch.tvg_name else [ch.name]
                # 同时匹配原始名称和标准化名称
                check_names = list(names)
                check_names.append(self._normalize_name(ch.name))
                
                if any(fnmatch.fnmatch(name, pattern) for name in check_names):
                    matched.append(ch)
                    used.add(id(ch))
            
            result.extend(matched)
        
        for ch in channels:
            if id(ch) not in used:
                result.append(ch)
                
        return result