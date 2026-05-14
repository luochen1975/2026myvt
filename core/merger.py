from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path

from core.parser import Channel, load_blacklist_rules


class ChannelMerger:
    def __init__(self, dedup_mode: str = "auto", keep_strategy: str = "first"):
        self.dedup_mode = dedup_mode
        self.keep_strategy = keep_strategy
        self.blacklist_rules = None
    
    def load_blacklist(self, path: str) -> None:
        """加载黑名单文件"""
        self.blacklist_rules = load_blacklist_rules()
    
    def merge(self, channels: list[Channel]) -> list[Channel]:
        """整合去重：按 URL 去重，保留速度最快的"""
        seen = {}
        for ch in channels:
            if ch.url not in seen:
                seen[ch.url] = ch
            else:
                existing = seen[ch.url]
                ch_speed = getattr(ch, 'speed', float('inf'))
                ex_speed = getattr(existing, 'speed', float('inf'))
                if ch_speed < ex_speed:
                    seen[ch.url] = ch
        
        return list(seen.values())
    
    def apply_template(self, channels: list[Channel], template_path: str) -> dict:
        """应用模板分组"""
        # 读取模板文件
        template = OrderedDict()
        if Path(template_path).exists():
            with open(template_path, 'r', encoding='utf-8') as f:
                current_group = None
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith('#'):
                        # 分组标题
                        current_group = line.lstrip('#').strip()
                        template[current_group] = []
                    elif current_group:
                        template[current_group].append(line)
        
        # 按模板分组
        grouped = OrderedDict()
        ungrouped = []
        
        for ch in channels:
            matched = False
            for group_name, patterns in template.items():
                if any(self._match_pattern(ch.name, p) for p in patterns):
                    if group_name not in grouped:
                        grouped[group_name] = OrderedDict()
                        grouped[group_name]['全部'] = []
                    grouped[group_name]['全部'].append(ch)
                    matched = True
                    break
            
            if not matched:
                ungrouped.append(ch)
        
        if ungrouped:
            grouped['其他'] = OrderedDict()
            grouped['其他']['全部'] = ungrouped
        
        return grouped
    
    def _match_pattern(self, name: str, pattern: str) -> bool:
        """匹配频道名和模板模式"""
        # 支持简单通配符和正则
        if '*' in pattern or '?' in pattern:
            regex = pattern.replace('*', '.*').replace('?', '.')
            return bool(re.search(regex, name, re.IGNORECASE))
        return pattern.lower() in name.lower()
    
    def filter_keywords(self, channels: list[Channel]) -> list[Channel]:
        """过滤特定关键词和广告台（从 blacklist.txt 加载规则）"""
        rules = load_blacklist_rules()
        
        patterns = rules.get('regex', [])
        keywords = rules.get('keywords', [])
        
        filtered = []
        for ch in channels:
            name = ch.name
            
            if any(p.search(name) for p in patterns):
                continue
            
            if any(k in name for k in keywords):
                continue
            
            filtered.append(ch)
        
        return filtered
