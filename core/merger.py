    def limit_by_type(self, channels: list[Channel]) -> list[Channel]:
        """
        测速后按类型限制数量：
        - 组播源：按测速结果排序（ffmpeg给的虚拟值或真实值）
        - 单播源：按速度排序
        """
        multicast = []
        mobile_multicast = []
        unicast = []
        mobile_unicast = []
        
        for ch in channels:
            url = ch.url.lower().strip()
            is_mc = url.startswith(('udp://', 'rtp://', 'rtsp://')) or \
                    url.startswith(('http://239.', 'http://233.', 'http://232.'))
            is_mobile = (
                'mobile' in url or 'cmcc' in url or 
                getattr(ch, 'isp', '') == 'mobile' or
                ch.extra.get('isp') == 'mobile'
            )
            
            if is_mc:
                if is_mobile:
                    mobile_multicast.append(ch)
                else:
                    multicast.append(ch)
            else:
                if is_mobile:
                    mobile_unicast.append(ch)
                else:
                    unicast.append(ch)
        
        # 统一排序函数：speed=None放最后
        def sort_speed(chs):
            return sorted(chs, key=lambda x: x.speed if x.speed is not None else -1, reverse=True)
        
        # 组播也按速度排序（ffmpeg测的虚拟值或真实值）
        limited_mc = sort_speed(multicast)[:self.multicast_limit]
        limited_mmc = sort_speed(mobile_multicast)[:self.mobile_multicast_limit]
        
        # 单播
        limited_uc = sort_speed(unicast)[:self.unicast_limit]
        limited_muc = sort_speed(mobile_unicast)[:self.unicast_limit]
        
        result = limited_mc + limited_mmc + limited_uc + limited_muc
        
        # 最终排序：组播优先（speed>90000的虚拟值），然后按速度
        def final_sort_key(x):
            is_virt = x.speed is not None and x.speed > 90000
            return (0 if is_virt else 1, -(x.speed or 0))
        
        return sorted(result, key=final_sort_key)
