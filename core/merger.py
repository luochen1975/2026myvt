import hashlib
import re
import fnmatch
import json
from pathlib import Path
from typing import List, Dict
from collections import defaultdict
from core.parser import Channel

class ChannelMerger:
    """频道整合去重器"""
    
    def __init__(self, dedup_mode: str = "url_fingerprint", keep_strategy: str = "fastest"):
        self.dedup_mode = dedup_mode
        self.keep_strategy = keep_strategy
        self.blacklist = set()
        self.multicast_limit = 2
        self.mobile_multicast_limit = 4
        self.unicast_limit = 5
        self.aliases = self._load_aliases()
    
    def _load_aliases(self) -> Dict[str, str]:
        """从文件加载别名"""
        alias_file = Path(__file__).parent.parent / "config" / "aliases.json"
        try:
            with open(alias_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def load_blacklist(self, blacklist_file: str):
        try:
            with open(blacklist_file, 'r') as f:
                self.blacklist = {line.strip() for line in f if line.strip() and not line.startswith('#')}
        except FileNotFoundError:
            pass
    
    def _normalize_name(self, name: str) -> str:
        name = re.sub(r'\s+', '', name).lower()
        for old, new in self.aliases.items():
            name = name.replace(old, new)
        return name
    
    def merge(self, all_channels: List[Channel]) -> List[Channel]:
        filtered = self._filter_blacklist(all_channels)
        filtered = self._filter_invalid(filtered)
        filtered = self._filter_keywords(filtered)
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
    
    def _filter_invalid(self, channels: List[Channel]) -> List[Channel]:
        """过滤无效URL"""
        valid = []
        for ch in channels:
            if not ch.url or ch.url.startswith(','):
                continue
            valid.append(ch)
        return valid
    
    def _filter_keywords(self, channels: List[Channel]) -> List[Channel]:
        """过滤特定关键词和年份+年+逗号"""
        skip_keywords = ['春晚', '春节联欢晚会', '历年春晚', '春晚回放', 'cctv春晚']
        year_nian_comma_pattern = re.compile(r'(19\d{2}|20\d{2})年,')
        
        filtered = []
        for ch in channels:
            text = f"{ch.name} {ch.group}".lower()
            
            if any(kw in text for kw in skip_keywords):
                print(f"  [过滤] {ch.name}")
                continue
            
            if year_nian_comma_pattern.search(ch.name):
                print(f"  [过滤] {ch.name}")
                continue
            
            filtered.append(ch)
        
        return filtered
    
    def _group_by_name(self, channels: List[Channel]) -> Dict[str, List[Channel]]:
        groups = defaultdict(list)
        for ch in channels:
            key = self._normalize_name(ch.name)
            groups[key].append(ch)
        return dict(groups)
    
    def _is_multicast(self, url: str) -> bool:
        return url.startswith(('udp://', 'rtp://', 'rtsp://'))
    
    def _get_isp(self, channels: List[Channel]) -> str:
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
        
        if multicast:
            multicast.sort(key=lambda c: c.speed, reverse=True)
            limit = self.mobile_multicast_limit if isp == 'mobile' else self.multicast_limit
            selected.extend(multicast[:limit])
            if len(multicast) > limit:
                print(f"  [组播去重] {channels[0].name}({isp}): {len(multicast)}个→{limit}个")
        
        if unicast:
            unicast.sort(key=lambda c: c.speed, reverse=True)
            selected.extend(unicast[:self.unicast_limit])
            if len(unicast) > self.unicast_limit:
                print(f"  [单播去重] {channels[0].name}: {len(unicast)}个→{self.unicast_limit}个")
        
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
