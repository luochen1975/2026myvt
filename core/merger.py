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
        self.mobile_multicast_limit = 8  # 移动组播多保留
    
    def load_blacklist(self, blacklist_file: str):
        try:
            with open(blacklist_file, 'r') as f:
                self.blacklist = {line.strip() for line in f if line.strip() and not line.startswith('#')}
        except FileNotFoundError:
            pass
    
    def _normalize_name(self, name: str) -> str:
        name = re.sub(r'\s+', '', name).lower()
        aliases = {
            'brtv': '北京',
            'zhejiangtv': '浙江',
            'ningbotv': '宁波',
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
    
    def _get_isp(self, channels: List[Channel]) -> str:
        """判断频道组的主要ISP"""
        isps = [c.extra.get('isp', 'other') for c in channels]
        if 'mobile' in isps:
            return 'mobile'
        elif 'unicom' in isps:
            return 'unicom'
        elif 'telecom' in isps:
            return 'telecom'
        return 'other'
    
    def _select_by_type(self, channels: List[Channel]) -> List[Channel]:
        multicast = [c for c in channels if self._is_multicast(c.url)]
        unicast = [c for c in channels if not self._is_multicast(c.url)]
        
        selected = []
        isp = self._get_isp(channels)
        
        # 组播源：移动网络多保留
        if multicast:
            multicast.sort(key=lambda c: c.speed, reverse=True)
            limit = self.mobile_multicast_limit if isp == 'mobile' else self.multicast_limit
            selected.extend(multicast[:limit])
            if len(multicast) > limit:
                print(f"  [组播去重] {channels[0].name}({isp}): {len(multicast)}个→{limit}个")
        
        # 单播源：全部保留
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
                
                names = [ch.name, ch.tvg_name] if ch.tvg_name else [ch.name]
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
