from __future__ import annotations  # 放在第一行，允许使用 list[Channel] 而无需导入 List
def _filter_keywords(self, channels: List[Channel]) -> List[Channel]:
    """过滤特定关键词和广告台（从 blacklist.txt 加载规则）"""
    from core.parser import load_blacklist_rules
    rules = load_blacklist_rules()
    
    # 从 blacklist.txt 获取正则规则和关键词
    patterns = rules.get('regex', [])
    keywords = rules.get('keywords', [])
    
    filtered = []
    for ch in channels:
        name = ch.name
        
        # 正则匹配频道名（如 1998年,、广告域名等）
        if any(p.search(name) for p in patterns):
            continue
        
        # 关键词匹配频道名（二次保险）
        if any(k in name for k in keywords):
            continue
        
        filtered.append(ch)
    
    return filtered
