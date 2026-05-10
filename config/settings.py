# config/settings.py
import os
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).parent.parent

# 输入配置
SOURCES_FILE = BASE_DIR / "config" / "sources.json"
TEMPLATE_FILE = BASE_DIR / "config" / "template.txt"
BLACKLIST_FILE = BASE_DIR / "config" / "blacklist.txt"

# 输出配置
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_M3U = OUTPUT_DIR / "result.m3u"
OUTPUT_TXT = OUTPUT_DIR / "result.txt"
LOG_DIR = OUTPUT_DIR / "logs"

# 测速配置
SPEED_TEST_TIMEOUT = 10          # 测速超时(秒)
SPEED_TEST_DURATION = 3            # 测速时长(秒)
MIN_SPEED_KBPS = 200               # 最小可用速度(KB/s)
MAX_CONCURRENT_TESTS = 50          # 最大并发测速数

# 去重配置
DEDUP_MODE = "url_fingerprint"     # url_fingerprint / name_url / none
DEDUP_KEEP = "fastest"             # fastest / first

# 缓存配置
CACHE_ENABLED = True
CACHE_FILE = BASE_DIR / "output" / ".speed_cache.json"
CACHE_TTL_HOURS = 24

# 请求配置
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# 确保目录存在
OUTPUT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)