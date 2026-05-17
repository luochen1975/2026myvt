#!/usr/bin/env python3
"""配置文件 - 浙江宁波移动网络优化"""
from pathlib import Path
import os

BASE_DIR = Path(__file__).parent.parent

SOURCES_FILE = BASE_DIR / "config" / "sources.json"
TEMPLATE_FILE = BASE_DIR / "config" / "template.txt"
BLACKLIST_FILE = BASE_DIR / "config" / "blacklist.txt"

OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_M3U = OUTPUT_DIR / "result.m3u"
OUTPUT_TXT = OUTPUT_DIR / "result.txt"
LOG_DIR = OUTPUT_DIR / "logs"

# ========== 测速配置 ==========
SPEED_TEST_TIMEOUT = 20          # 总超时
SPEED_TEST_DURATION = 8          # 测速读取秒数
MIN_SPEED_KBPS = 20              # 最低保留速度
MAX_CONCURRENT_TESTS = 20        # 并发数

# 分层测速配置
OVERSEAS_SPEED_DURATION = 15     # 外网/港澳台测15秒
OVERSEAS_SPEED_TIMEOUT = 35      # 外网超时35秒
OVERSEAS_CONNECT_TIMEOUT = 10      # 外网连接超时10秒

# 组播源配置
MULTICAST_MIN_SPEED = 10         # 组播最低保留速度
MULTICAST_TEST_DURATION = 8      # 组播测速8秒
MULTICAST_TEST_TIMEOUT = 15      # 组播超时15秒

# 内网源配置
PRIVATE_MIN_SPEED = 10           # 内网最低速度
PRIVATE_TEST_DURATION = 5        # 内网测5秒

# ========== 去重配置 ==========
DEDUP_MODE = "url_fingerprint"
DEDUP_KEEP = "fastest"

# ========== 缓存配置 ==========
CACHE_ENABLED = True
CACHE_FILE = BASE_DIR / "output" / ".speed_cache.json"
CACHE_TTL_HOURS = 24

# ========== 请求配置 ==========
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# ========== 代理配置 (Clash) ==========
PROXY_ENABLED = True
PROXY_URL = "http://127.0.0.1:7890"

# ========== ISP 分组 ==========
ISP_GROUPS = {
    "telecom": "电信",
    "unicom": "联通",
    "mobile": "移动",
    "other": "其他"
}

# 你的网络标识
MY_ISP = "mobile"
MY_CITY = "ningbo"

# ========== 数量限制配置 ==========
MULTICAST_LIMIT = 4              # 普通组播限制
MOBILE_MULTICAST_LIMIT = 6       # 移动组播限制
UNICAST_LIMIT = 15               # 单播限制
MAX_PER_GROUP = 300              # 每组最大频道数

# 确保目录存在
OUTPUT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
