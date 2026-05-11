import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

SOURCES_FILE = BASE_DIR / "config" / "sources.json"
TEMPLATE_FILE = BASE_DIR / "config" / "template.txt"
BLACKLIST_FILE = BASE_DIR / "config" / "blacklist.txt"

OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_M3U = OUTPUT_DIR / "result.m3u"
OUTPUT_TXT = OUTPUT_DIR / "result.txt"
LOG_DIR = OUTPUT_DIR / "logs"

# 测速配置 - 移动网络优化
SPEED_TEST_TIMEOUT = 20          # 移动网络慢，超时放宽
SPEED_TEST_DURATION = 8            # 组播源测久一点
MIN_SPEED_KBPS = 20                # 移动组播20KB/s就能流畅
MAX_CONCURRENT_TESTS = 20          # 移动宽带并发降一点，稳定

# 组播特殊处理
MULTICAST_MIN_SPEED = 10             # 组播源最低10KB/s保留
UNICAST_MIN_SPEED = 50               # 单播源最低50KB/s

# 去重配置
DEDUP_MODE = "url_fingerprint"
DEDUP_KEEP = "fastest"

# 缓存配置
CACHE_ENABLED = True
CACHE_FILE = BASE_DIR / "output" / ".speed_cache.json"
CACHE_TTL_HOURS = 24

# 请求配置
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# 代理配置 (Clash)
PROXY_ENABLED = True
PROXY_URL = "http://127.0.0.1:7890"

# ISP 分组
ISP_GROUPS = {
    "telecom": "电信",
    "unicom": "联通",
    "mobile": "移动",
    "other": "其他"
}

# 你的网络标识
MY_ISP = "mobile"
MY_CITY = "ningbo"

# 确保目录存在
OUTPUT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
