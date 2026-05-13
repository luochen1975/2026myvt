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
        self.multicast_limit = 5
        self.mobile_multicast_limit = 6
        self.unicast_limit = 8
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
        """标准化频道名称"""
        # 去空格、转小写
        name = re.sub(r'\s+', '', name).lower()
        
        # CCTV 统一格式
        name = re.sub(r'cctv\s*(\d+)', r'cctv-\1', name)
        name = re.sub(r'cctv-(\d+)[^\d].*', r'cctv-\1', name)
        
        # 去掉清晰度后缀
        name = re.sub(r'(高清|hd|超清|uhd|4k|8k|标清|sd|1080p|720p)', '', name)
        
        # 去掉"频道"后缀
        name = re.sub(r'频道$', '', name)
        
        # 别名替换
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
            if not ch.url:
                continue
            # 只过滤纯逗号开头的，保留组播
            url_stripped = ch.url.strip()
            if url_stripped.startswith(','):
                continue
            valid.append(ch)
        return valid
    
    def _filter_keywords(self, channels: List[Channel]) -> List[Channel]:
        """过滤特定关键词和广告台"""
        skip_keywords = [
            '春晚', '春节联欢晚会', '历年春晚', '春晚回放', 'cctv春晚',
            '成人', '午夜', '激情', '诱惑', '私密', '限制级',
            'av', 'xxx', 'porn', 'adult',  'sexy',
            'redtraffic', 'G2s9zK2n9m', 'mycamtv', 'ddyunbo',
            'bgbfds', '6apzfdx', 'shuma5588', 'xsmj10',
            'aosikazy12', 'slbfsl', 'cdn2020', 'hndtl',
            'm8t9ew', '46cdn', '41cdn', '34cdn', 'krevonix',
            # 广告购物台
            '购物', '直销', '广告', '电视购物', '快乐购', '家家购',
            '优购物', '好享购', '聚鲨', '环球购物', '时尚购物'
        ]
        year_nian_comma_pattern = re.compile(r'(19\d{2}|20\d{2})年,')
        
        filtered = []
        for ch in channels:
            text = f"{ch.name} {ch.group}".lower()
            
            # 检查关键词
            if any(kw in text for kw in skip_keywords):
                print(f"  [过滤] {ch.name}")
                continue
            
            # 检查年份+年+逗号
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
        """判断是否为组播源，支持大小写"""
        url = url.strip().lower()
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
        """区分组播和单播，分别处理"""
        multicast = [c for c in channels if self._is_multicast(c.url)]
        unicast = [c for c in channels if not self._is_multicast(c.url)]
        
        selected = []
        isp = self._get_isp(channels)
        
        # 组播源：按速度排序，保留最快的
        if multicast:
            multicast.sort(key=lambda c: c.speed, reverse=True)
            limit = self.mobile_multicast_limit if isp == 'mobile' else self.multicast_limit
            selected.extend(multicast[:limit])
            if len(multicast) > limit:
                print(f"  [组播去重] {channels[0].name}({isp}): {len(multicast)}个→{limit}个")
        
        # 单播源：保留最快的5个
        if unicast:
            unicast.sort(key=lambda c: c.speed, reverse=True)
            selected.extend(unicast[:self.unicast_limit])
            if len(unicast) > self.unicast_limit:
                print(f"  [单播去重] {channels[0].name}: {len(unicast)}个→{self.unicast_limit}个")
        
        return selected
    
    def apply_template(self, channels: List[Channel], template_file: str) -> Dict[str, Dict[str, List[Channel]]]:
        """应用模板，返回分组结果"""
        # 解析模板结构
        groups = {}  # group_name -> {sub_group -> [patterns]}
        current_group = None
        current_sub = None
        
        with open(template_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                # 一级分组: ❤️地方,#group#
                if line.endswith(',#group#'):
                    current_group = line.replace('❤️', '').replace(',#group#', '').strip()
                    groups[current_group] = {}
                    current_sub = None
                    continue
                
                # 二级分组: ❤️浙江,#genre#
                if line.endswith(',#genre#'):
                    current_sub = line.replace('❤️', '').replace(',#genre#', '').strip()
                    if current_group:
                        groups[current_group][current_sub] = []
                    continue
                
                # 频道模式
                if current_sub:
                    patterns = [p.strip() for p in line.split('|')]
                    groups[current_group][current_sub].extend(patterns)
        
        # 匹配频道到分组
        result = {}
        used = set()
        
        for group_name, sub_groups in groups.items():
            result[group_name] = {}
            for sub_name, patterns in sub_groups.items():
                matched = []
                for ch in channels:
                    if id(ch) in used:
                        continue
                    
                    names = [ch.name, ch.tvg_name] if ch.tvg_name else [ch.name]
                    check_names = list(names)
                    check_names.append(self._normalize_name(ch.name))
                    
                    if any(any(fnmatch.fnmatch(name, pat) for name in check_names) for pat in patterns):
                        matched.append(ch)
                        used.add(id(ch))
                
                if matched:
                    result[group_name][sub_name] = matched
        
        # 未匹配的放其他
        other = [ch for ch in channels if id(ch) not in used]
        if other:
            result['其他'] = {'未分类': other}
        
        return result
