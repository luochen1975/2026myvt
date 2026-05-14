from __future__ import annotations

from core.parser import load_blacklist_rules  # 移到顶部导入

# 需要导入 Channel 类，假设它在 core.models 或 core.parser 中
# 根据你的项目结构调整导入路径
from core.parser import Channel  # 或者 from core.models import Channel


def filter_keywords(channels: list[Channel]) -> list[Channel]:
    """过滤特定关键词和广告台（从 blacklist.txt 加载规则）"""
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
