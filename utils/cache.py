import json
import hashlib
import time
from pathlib import Path
from typing import Optional

class SpeedCache:
    """测速缓存 - 支持失败标记，避免重复测速死节点"""
    
    FAIL_MARKER = -1.0  # 标记失败（比0小，排序时放最后）
    SKIP_MARKER = -2.0  # 标记组播跳过测速
    
    def __init__(self, path, ttl=86400):
        self.path = Path(path)
        self.ttl = ttl
        self.d = {}
        self._load()
    
    def _key(self, url: str) -> str:
        # 使用完整URL的MD5，避免冲突
        return hashlib.md5(url.encode('utf-8')).hexdigest()[:16]
    
    def _load(self):
        try:
            if self.path.exists():
                with open(self.path, 'r', encoding='utf-8') as f:
                    self.d = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.d = {}
    
    def get(self, url: str) -> Optional[float]:
        """获取缓存速度。None=未缓存，FAIL_MARKER=上次失败，SKIP_MARKER=组播跳过"""
        k = self._key(url)
        item = self.d.get(k)
        if not item:
            return None
        if time.time() - item.get("t", 0) > self.ttl:
            return None
        return item.get("speed")
    
    def set(self, url: str, speed: Optional[float]):
        """设置缓存。speed=None表示失败"""
        self.d[self._key(url)] = {
            "speed": self.FAIL_MARKER if speed is None else speed,
            "t": time.time()
        }
    
    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self.d, f, ensure_ascii=False)
    
    def stats(self) -> dict:
        """统计缓存状态"""
        total = len(self.d)
        failed = sum(1 for v in self.d.values() if v.get("speed") == self.FAIL_MARKER)
        skipped = sum(1 for v in self.d.values() if v.get("speed") == self.SKIP_MARKER)
        valid = total - failed - skipped
        return {"total": total, "valid": valid, "failed": failed, "skipped": skipped}
