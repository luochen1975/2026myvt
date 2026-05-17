#!/usr/bin/env python3
"""日志模块 - 北京时间"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo


class BeijingFormatter(logging.Formatter):
    """自定义格式化器，使用北京时间"""
    def formatTime(self, record, datefmt=None):
        beijing_time = datetime.fromtimestamp(record.created, tz=ZoneInfo("Asia/Shanghai"))
        if datefmt:
            return beijing_time.strftime(datefmt)
        return beijing_time.isoformat()


formatter = BeijingFormatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

handler = logging.StreamHandler()
handler.setFormatter(formatter)

log = logging.getLogger("iptv")
log.setLevel(logging.INFO)
log.addHandler(handler)
log.propagate = False
