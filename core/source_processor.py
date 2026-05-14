#!/usr/bin/env python3
import requests
from pathlib import Path

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

def filter_genre(text, genres):
    if not genres:
        return text
    out, skip = [], False
    for line in text.strip().split('\n'):
        if line.strip().endswith(',#genre#'):
            skip = any(g in line for g in genres)
            continue
        if not skip:
            out.append(line)
    return '\n'.join(out) + '\n'

def filter_keyword(text, keywords):
    if not keywords:
        return text
    return '\n'.join(l for l in text.strip().split('\n') 
                    if not any(k in l for k in keywords)) + '\n'

def process_source(item):
    """处理单个源，返回保存路径"""
    if isinstance(item, dict):
        name = item.get("name", "unnamed")
        url = item["url"]
        exc = item.get("exclude", {})
    else:
        name = item.split('/')[-1].replace('.txt', '').replace('.m3u', '').replace('.m3u8', '')
        url = item
        exc = {}
    
    text = requests.get(url, timeout=15).text
    
    if "genres" in exc:
        text = filter_genre(text, exc["genres"])
    if "keywords" in exc:
        text = filter_keyword(text, exc["keywords"])
    
    ext = "m3u" if ".m3u" in url else "txt"
    out_path = CACHE_DIR / f"{name}.{ext}"
    
    out_path.write_text(text, encoding='utf-8')
    return out_path
