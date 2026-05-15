import logging
from datetime import datetime
from zoneinfo import ZoneInfo

# 自定义格式化器，使用北京时间
class BeijingFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        # 获取北京时间
        beijing_time = datetime.fromtimestamp(record.created, tz=ZoneInfo('Asia/Shanghai'))
        if datefmt:
            return beijing_time.strftime(datefmt)
        return beijing_time.isoformat()

# 使用自定义格式化器
formatter = BeijingFormatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')

handler = logging.StreamHandler()
handler.setFormatter(formatter)

log = logging.getLogger("iptv")
log.setLevel(logging.INFO)
log.addHandler(handler)
log.propagate = False  # 避免重复输出
