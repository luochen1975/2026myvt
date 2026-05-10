from typing import List
from datetime import datetime
from core.parser import Channel

class M3UExporter:
    """M3U格式导出"""
    
    @staticmethod
    def export(channels: List[Channel], output_file: str, epg_url: str = ""):
        lines = ['#EXTM3U']
        
        if epg_url:
            lines[0] += f' url-tvg="{epg_url}"'
        
        for ch in channels:
            # EXTINF行
            extinf = f'#EXTINF:-1'
            
            attrs = []
            if ch.tvg_id:
                attrs.append(f'tvg-id="{ch.tvg_id}"')
            if ch.tvg_name:
                attrs.append(f'tvg-name="{ch.tvg_name}"')
            if ch.logo:
                attrs.append(f'tvg-logo="{ch.logo}"')
            if ch.group:
                attrs.append(f'group-title="{ch.group}"')
            
            if attrs:
                extinf += ' ' + ' '.join(attrs)
            
            extinf += f',{ch.name}'
            lines.append(extinf)
            lines.append(ch.url)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"[OK] M3U已导出: {output_file} ({len(channels)}个频道)")

class TXTExporter:
    """TXT格式导出"""
    
    @staticmethod
    def export(channels: List[Channel], output_file: str, include_speed: bool = False):
        lines = []
        
        current_group = ""
        for ch in channels:
            # 分组标题
            if ch.group and ch.group != current_group:
                lines.append(f"\n{ch.group},#genre#")
                current_group = ch.group
            
            # 频道行
            line = f"{ch.name},{ch.url}"
            if include_speed and ch.speed > 0:
                line += f"  [{ch.speed:.0f}KB/s]"
            if ch.group and not current_group:
                line += f"#{ch.group}"
                
            lines.append(line)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"[OK] TXT已导出: {output_file} ({len(channels)}个频道)")

class LogExporter:
    """测速日志导出"""
    
    @staticmethod
    def export_speed_log(channels: List[Channel], log_file: str):
        lines = [
            f"# 测速日志 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# 总计: {len(channels)} 个频道",
            f"# {'名称':<20} {'分组':<15} {'速度(KB/s)':<12} {'URL'}",
            "-" * 100
        ]
        
        # 排序：速度快的在前
        sorted_ch = sorted(channels, key=lambda c: c.speed, reverse=True)
        
        for ch in sorted_ch:
            status = "✓" if ch.speed > 200 else "✗"
            lines.append(
                f"{status} {ch.name:<20} {ch.group:<15} {ch.speed:>10.1f}  {ch.url[:60]}"
            )
        
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))