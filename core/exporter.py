from typing import List, Dict
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from core.parser import Channel
from config.settings import ISP_GROUPS

class M3UExporter:
    @staticmethod
    def export(channels: List[Channel], output_file: str, epg_url: str = ""):
        lines = ['#EXTM3U']
        if epg_url:
            lines[0] += f' url-tvg="{epg_url}"'
        
        for ch in channels:
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
    
    @staticmethod
    def export_by_template(grouped_channels: Dict, output_dir: str):
        """按模板分组导出M3U"""
        filepath = Path(output_dir) / "result.m3u"
        
        lines = ['#EXTM3U']
        
        for group_name, sub_groups in grouped_channels.items():
            for sub_name, channels in sub_groups.items():
                for ch in channels:
                    # 组播源标记
                    is_multicast = ch.url.strip().lower().startswith(('udp://', 'rtp://', 'rtsp://'))
                    multicast_tag = "[组播]" if is_multicast else ""
                    
                    extinf = f'#EXTINF:-1 group-title="{group_name}-{sub_name}"'
                    extinf += f',{ch.name}{multicast_tag}'
                    lines.append(extinf)
                    lines.append(ch.url)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"[OK] M3U已导出: {filepath}")

class TXTExporter:
    @staticmethod
    def export(channels: List[Channel], output_file: str, include_speed: bool = False):
        lines = []
        current_group = ""
        for ch in channels:
            if ch.group and ch.group != current_group:
                lines.append(f"\n{ch.group},#genre#")
                current_group = ch.group
            
            line = f"{ch.name},{ch.url}"
            if include_speed and ch.speed > 0:
                line += f"  [{ch.speed:.0f}KB/s]"
            if ch.group and not current_group:
                line += f"#{ch.group}"
            lines.append(line)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"[OK] TXT已导出: {output_file} ({len(channels)}个频道)")
    
    @staticmethod
    def export_by_template(grouped_channels: Dict, output_file: str):
        """按模板分组导出TXT"""
        lines = []
        
        for group_name, sub_groups in grouped_channels.items():
            # 一级分组标题
            lines.append(f"\n❤️{group_name},#group#")
            
            for sub_name, channels in sub_groups.items():
                # 二级分组标题
                lines.append(f"\n❤️{sub_name},#genre#")
                
                for ch in channels:
                    # 组播源标记
                    is_multicast = ch.url.strip().lower().startswith(('udp://', 'rtp://', 'rtsp://'))
                    multicast_tag = " [组播]" if is_multicast else ""
                    
                    lines.append(f"{ch.name}{multicast_tag},{ch.url}")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"[OK] TXT已导出: {output_file}")

class LogExporter:
    @staticmethod
    def export_speed_log(channels: List[Channel], log_file: str):
        lines = [
            f"# 测速日志 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# 总计: {len(channels)} 个频道",
            f"# {'名称':<<20} {'分组':<<15} {'ISP':<<8} {'类型':<<6} {'速度(KB/s)':<<12} {'URL'}",
            "-" * 120
        ]
        
        sorted_ch = sorted(channels, key=lambda c: c.speed, reverse=True)
        for ch in sorted_ch:
            status = "✓" if ch.speed > 50 else "✗"
            isp = ch.extra.get('isp', 'other')
            is_multicast = "组播" if ch.url.strip().lower().startswith(('udp://', 'rtp://', 'rtsp://')) else "单播"
            lines.append(
                f"{status} {ch.name:<20} {ch.group:<15} {isp:<8} {is_multicast:<6} {ch.speed:>10.1f}  {ch.url[:60]}"
            )
        
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
