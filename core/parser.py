#!/usr/bin/env python3
"""解析器模块 - 支持M3U/TXT/JSON格式"""
import json
import re
import requests
from pathlib import Path
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import List, Optional, Dict

from config.settings import PROXY_ENABLED, PROXY_URL, USER_AGENT, NAME_RULES_FILE


@dataclass
class Channel:
    name: str
    url: str
    group: str = ""
    logo: str = ""
    tvg_id: str = ""
    tvg_name: str = ""
    extra: Dict = None
    source: str = ""
    speed: float = 0.0

    def __post_init__(self):
        if self.extra is None:
            self.extra = {}


class M3UParser:
    @staticmethod
    def parse(content: str, source: str = "") -> List[Channel]:
        channels = []
        lines = content.strip().split("\n")
        current_meta = {}

        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue

            if line.startswith("#EXTINF:"):
                current_meta = M3UParser._parse_extinf(line)
            elif line.startswith("#EXTGRP:"):
                current_meta["group"] = line[8:].strip()
            elif not line.startswith("#") and current_meta:
                channel = Channel(
                    name=current_meta.get("name", "Unknown"),
                    url=line,
                    group=current_meta.get("group", ""),
                    logo=current_meta.get("logo", ""),
                    tvg_id=current_meta.get("tvg_id", ""),
                    tvg_name=current_meta.get("tvg_name", ""),
                    source=source,
                    extra=current_meta
                )
                channels.append(channel)
                current_meta = {}

        return channels

    @staticmethod
    def _parse_extinf(line: str) -> dict:
        meta = {}
        if "," in line:
            meta["name"] = line.split(",", 1)[1].strip()
        attrs = re.findall(r'([a-zA-Z-]+)="([^"]*)"', line)
        for key, value in attrs:
            key = key.replace("-", "_").lower()
            if key == "group_title":
                meta["group"] = value
            elif key == "tvg_logo":
                meta["logo"] = value
            else:
                meta[key] = value
        return meta


class TXTParser:
    @staticmethod
    def parse(content: str, source: str = "") -> List[Channel]:
        channels = []
        current_group = ""

        for line in content.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if ",#genre#" in line or ", #genre#" in line:
                parts = line.split(",", 1)
                current_group = parts[0].strip()
                continue

            if "," in line:
                parts = line.split(",", 1)
                name = parts[0].strip()
                url_part = parts[1].strip()

                if not name or url_part.startswith(","):
                    continue

                group = current_group
                if "#" in url_part:
                    url, extra_group = url_part.rsplit("#", 1)
                    url = url.strip()
                    if extra_group.strip():
                        group = extra_group.strip()
                else:
                    url = url_part

                if "$" in url:
                    url = url.split("$")[0].strip()

                url = url.strip()
                if url and (url.startswith("http") or url.startswith(("udp://", "rtp://", "rtsp://", "UDP://", "RTP://", "RTSP://"))):
                    channels.append(Channel(
                        name=name, 
                        url=url, 
                        group=group, 
                        source=source
                    ))

        return channels


class JSONParser:
    @staticmethod
    def parse(content: str, source: str = "") -> List[Channel]:
        channels = []
        data = json.loads(content)
        if isinstance(data, list):
            for item in data:
                ch = JSONParser._item_to_channel(item, source)
                if ch:
                    channels.append(ch)
        elif isinstance(data, dict):
            items = data.get("channels", data.get("list", []))
            for item in items:
                ch = JSONParser._item_to_channel(item, source)
                if ch:
                    channels.append(ch)
        return channels

    @staticmethod
    def _item_to_channel(item: dict, source: str) -> Optional[Channel]:
        if not isinstance(item, dict):
            return None
        url = item.get("url", item.get("link", item.get("address", "")))
        if not url or not (url.startswith("http") or url.startswith(("udp://", "rtp://", "rtsp://"))):
            return None
        return Channel(
            name=item.get("name", item.get("title", "Unknown")),
            url=url,
            group=item.get("group", item.get("category", "")),
            logo=item.get("logo", item.get("icon", "")),
            tvg_id=item.get("tvg_id", ""),
            source=source,
            extra=item
        )


BLACKLIST_FILE = Path(__file__).parent.parent / "config" / "blacklist.txt"


def _yaml_scalar(value: str):
    """把 YAML 的简单字符串值转成 Python 字符串。"""
    value = value.strip()
    if not value:
        return ""
    if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
        return value[1:-1]
    return value


def load_name_rules(path: str | Path = NAME_RULES_FILE) -> list[dict]:
    """加载 `config/name_rules.yaml`，兼容该项目的简化 YAML 结构。"""
    path = Path(path)
    if not path.exists():
        return []

    rules = []
    current = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        stripped = line.lstrip()
        if stripped.startswith("- "):
            if current:
                rules.append(current)
            current = {}
            rest = stripped[2:].strip()
            if rest and ":" in rest:
                key, value = rest.split(":", 1)
                current[key.strip()] = _yaml_scalar(value)
            continue

        if current is None or ":" not in stripped:
            continue

        key, value = stripped.split(":", 1)
        current[key.strip()] = _yaml_scalar(value)

    if current:
        rules.append(current)

    return rules


def apply_name_rules(channels: List[Channel], rules: Optional[List[dict]] = None) -> List[Channel]:
    """应用名称清洗/重命名规则，统一修正频道名和分组。"""
    if rules is None:
        rules = load_name_rules()

    for ch in channels:
        name = ch.name
        for rule in rules:
            pattern = rule.get("filter")
            if not pattern:
                continue
            try:
                regex = re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                print(f"[WARNING] 名称规则编译失败 '{pattern}': {exc}")
                continue

            matched_before = bool(regex.fullmatch(name))
            if "replace" in rule:
                name = regex.sub(rule.get("replace", ""), name)

            if "rename" in rule and matched_before:
                name = rule["rename"]

            if "group" in rule and (matched_before or bool(regex.fullmatch(name))):
                ch.group = rule["group"]

        ch.name = name

    return channels


def load_blacklist_rules() -> dict:
    """加载黑名单规则"""
    rules = {
        "domains": [], "contains": [], "urls": [],
        "genres": [], "keywords": [], "regex": [],
    }

    if not BLACKLIST_FILE.exists():
        return rules

    with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if ":" in line:
                rule_type, rule_value = line.split(":", 1)
                rule_type = rule_type.strip().lower()
                rule_value = rule_value.strip()

                if rule_type == "domain":
                    rules["domains"].append(rule_value)
                elif rule_type == "contains":
                    rules["contains"].append(rule_value)
                elif rule_type == "genre":
                    rules["genres"].append(rule_value)
                elif rule_type == "keyword":
                    rules["keywords"].append(rule_value)
                elif rule_type == "regex":
                    try:
                        rules["regex"].append(re.compile(rule_value))
                    except re.error as e:
                        print(f"[WARNING] 正则编译失败 '{rule_value}': {e}")
            else:
                rules["urls"].append(line)

    return rules


def filter_genre(text: str, genres: list) -> str:
    """genre分组过滤"""
    if not genres:
        return text
    out, skip = [], False
    for line in text.strip().split("\n"):
        stripped = line.strip()
        if stripped.endswith(",#genre#"):
            skip = any(g in stripped for g in genres)
            if skip:
                continue
        if not skip:
            out.append(line)
    return "\n".join(out) + "\n"


def filter_keyword(text: str, keywords: list) -> str:
    """单行关键词过滤"""
    if not keywords:
        return text
    return "\n".join(l for l in text.strip().split("\n") 
                    if not any(k in l for k in keywords)) + "\n"


def apply_blacklist_filter(text: str, rules: dict) -> str:
    """应用黑名单过滤"""
    if rules.get("genres"):
        text = filter_genre(text, rules["genres"])
    if rules.get("keywords"):
        text = filter_keyword(text, rules["keywords"])
    return text


class SourceLoader:
    PARSERS = {
        "txt": TXTParser, "m3u": M3UParser,
        "m3u8": M3UParser, "json": JSONParser
    }

    @staticmethod
    def load(source_config: dict) -> List[Channel]:
        name = source_config.get("name", "unknown")
        url = source_config["url"]
        file_type = source_config.get("type", "m3u").lower()
        use_proxy = source_config.get("proxy", False)

        try:
            content = SourceLoader._fetch_content(url, use_proxy)

            blacklist_rules = load_blacklist_rules()
            content = apply_blacklist_filter(content, blacklist_rules)

            parser = SourceLoader.PARSERS.get(file_type, M3UParser)
            channels = parser.parse(content, source=name)
            channels = apply_name_rules(channels)

            isp = source_config.get("isp", "other")
            for ch in channels:
                ch.extra["isp"] = isp

            return channels
        except Exception as e:
            print(f"[ERROR] 加载源 {name} 失败: {e}")
            return []

    @staticmethod
    def _fetch_content(url: str, use_proxy: bool = False) -> str:
        proxies = None
        if use_proxy and PROXY_ENABLED:
            proxies = {"http": PROXY_URL, "https": PROXY_URL}

        if url.startswith("http"):
            headers = {"User-Agent": USER_AGENT}
            resp = requests.get(url, headers=headers, timeout=30, proxies=proxies)
            resp.raise_for_status()

            content_bytes = resp.content
            for enc in ["utf-8", "gbk", "gb2312", "big5"]:
                try:
                    return content_bytes.decode(enc)
                except UnicodeDecodeError:
                    continue

            return content_bytes.decode("utf-8", errors="ignore")
        else:
            with open(url, "r", encoding="utf-8") as f:
                return f.read()
