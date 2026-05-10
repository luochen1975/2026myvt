import json, hashlib, time

class SpeedCache:
    def __init__(self, path, ttl=86400):
        self.path, self.ttl, self.d = path, ttl, {}
        try:
            with open(path) as f: self.d = json.load(f)
        except: pass
    def get(self, url):
        k = hashlib.md5(url.encode()).hexdigest()[:16]
        item = self.d.get(k)
        return item["speed"] if item and time.time()-item["t"]<self.ttl else None
    def set(self, url, speed):
        self.d[hashlib.md5(url.encode()).hexdigest()[:16]] = {"speed": speed, "t": time.time()}
    def save(self):
        with open(self.path, 'w') as f: json.dump(self.d, f)