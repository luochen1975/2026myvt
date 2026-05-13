class M3UExporter:
    # ... 原有方法不变 ...
    
    @staticmethod
    def export_all(channels: List[Channel], output_file: str, epg_url: str = ""):
        """导出所有频道（不分ISP）"""
        M3UExporter.export(channels, output_file, epg_url)
    
    @staticmethod
    def export_mobile_first(channels: List[Channel], output_file: str, epg_url: str = ""):
        """移动源优先排序导出"""
        # 移动源排前面，其他排后面
        mobile = [c for c in channels if c.extra.get('isp') == 'mobile']
        other = [c for c in channels if c.extra.get('isp') != 'mobile']
        
        # 各自按速度排序
        mobile.sort(key=lambda c: c.speed, reverse=True)
        other.sort(key=lambda c: c.speed, reverse=True)
        
        # 合并：移动优先
        sorted_channels = mobile + other
        
        M3UExporter.export(sorted_channels, output_file, epg_url)
        print(f"[OK] 移动优先M3U已导出: {output_file} (移动:{len(mobile)}, 其他:{len(other)})")
    
    @staticmethod
    def export_other(channels: List[Channel], output_file: str, epg_url: str = ""):
        """只导出非移动源"""
        other = [c for c in channels if c.extra.get('isp') != 'mobile']
        other.sort(key=lambda c: c.speed, reverse=True)
        M3UExporter.export(other, output_file, epg_url)
        print(f"[OK] 其他源M3U已导出: {output_file} ({len(other)}个)")


class TXTExporter:
    # ... 原有方法不变 ...
    
    @staticmethod
    def export_mobile_first(channels: List[Channel], output_file: str, include_speed: bool = False):
        """移动源优先排序导出TXT"""
        mobile = [c for c in channels if c.extra.get('isp') == 'mobile']
        other = [c for c in channels if c.extra.get('isp') != 'mobile']
        
        mobile.sort(key=lambda c: c.speed, reverse=True)
        other.sort(key=lambda c: c.speed, reverse=True)
        
        sorted_channels = mobile + other
        TXTExporter.export(sorted_channels, output_file, include_speed)
        print(f"[OK] 移动优先TXT已导出: {output_file} (移动:{len(mobile)}, 其他:{len(other)})")
    
    @staticmethod
    def export_other(channels: List[Channel], output_file: str, include_speed: bool = False):
        """只导出非移动源TXT"""
        other = [c for c in channels if c.extra.get('isp') != 'mobile']
        other.sort(key=lambda c: c.speed, reverse=True)
        TXTExporter.export(other, output_file, include_speed)
        print(f"[OK] 其他源TXT已导出: {output_file} ({len(other)}个)")
