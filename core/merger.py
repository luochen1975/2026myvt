#!/usr/bin/env python3
"""频道合并器 - 支持自动分组和数量限制"""
from __future__ import annotations

import re
import ipaddress
from collections import OrderedDict, defaultdict
from pathlib import Path
from urllib.parse import urlparse
from typing import List, Dict, Tuple

from core.parser import Channel, load_blacklist_rules


def is_ipv6_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return False
        ip = ipaddress.ip_address(host)
        return isinstance(ip, ipaddress.IPv6Address)
    except (ValueError, Exception):
        return False


def auto_group_by_name(channels: list[Channel]) -> dict:
    """按频道名自动分组"""

    groups = OrderedDict()
    grouped_urls_set = set()

    groups["❤️Radio"] = []
    for ch in channels:
        name_lower = ch.name.lower()
        if "radio" in name_lower or "qingting" in name_lower:
            groups["❤️Radio"].append(ch)
            grouped_urls_set.add(ch.url)

    groups["❤️歌舞"] = []
    for ch in channels:
        if ch.url in grouped_urls_set:
            continue
        if any(kw in ch.name for kw in ["歌曲", "合集", "精选", "舞曲"]):
            groups["❤️歌舞"].append(ch)
            grouped_urls_set.add(ch.url)

    groups["❤️新电视"] = []
    for ch in channels:
        if ch.url in grouped_urls_set:
            continue
        name_lower = ch.name.lower()
        if any(kw in name_lower for kw in ["newtv", "ihot", "iptv"]):
            groups["❤️新电视"].append(ch)
            grouped_urls_set.add(ch.url)

    groups["❤️央视"] = []
    for ch in channels:
        if ch.url in grouped_urls_set:
            continue
        if "CCTV" in ch.name or "央视" in ch.name:
            groups["❤️央视"].append(ch)
            grouped_urls_set.add(ch.url)

    groups["❤️卫视"] = []
    for ch in channels:
        if ch.url in grouped_urls_set:
            continue
        if "卫视" in ch.name:
            groups["❤️卫视"].append(ch)
            grouped_urls_set.add(ch.url)

    province_map = {
        "❤️北京": ["北京", "BTV", "北京卫视", "北京新闻", "北京文艺", "北京科教", "北京影视", "北京财经", "北京体育", "北京生活", "北京青年", "北京纪实", "北京通州", "北京怀柔", "北京顺义", "北京昌平", "北京大兴", "北京丰台", "北京海淀", "北京西城", "北京东城", "北京朝阳", "北京石景山", "北京门头沟", "北京房山", "北京平谷", "北京密云", "北京延庆"],
        "❤️天津": ["天津", "天视", "天津卫视", "天津新闻", "天津文艺", "天津影视频道", "天津都市", "天津体育", "天津教育", "天津相声", "天津滨海", "天津西青", "天津北辰", "天津东丽", "天津津南", "天津武清", "天津宝坻", "天津静海", "天津宁河", "天津蓟州", "天津河东", "天津河西", "天津南开", "天津河北", "天津红桥", "天津和平"],
        "❤️上海": ["上海", "东方", "上视", "SMG", "东方卫视", "上海新闻综合", "上海第一财经", "上海纪实人文", "上海五星体育", "上海娱乐", "上海都市", "上海教育", "上海外语", "上海法治", "上海生活", "上海金山", "上海松江", "上海青浦", "上海奉贤", "上海嘉定", "上海宝山", "上海闵行", "上海浦东", "上海崇明", "上海黄浦", "上海静安", "上海徐汇", "上海长宁", "上海普陀", "上海虹口", "上海杨浦"],
        "❤️重庆": ["重庆", "重庆卫视", "渝", "重庆新闻", "重庆影视", "重庆科教", "重庆都市", "重庆娱乐", "重庆公共", "重庆时尚", "重庆区县", "重庆万州", "重庆涪陵", "重庆黔江", "重庆江北", "重庆沙坪坝", "重庆九龙坡", "重庆南岸", "重庆北碚", "重庆渝北", "重庆巴南", "重庆长寿", "重庆江津", "重庆合川", "重庆永川", "重庆南川", "重庆綦江", "重庆大足", "重庆璧山", "重庆铜梁", "重庆潼南", "重庆荣昌", "重庆开州", "重庆梁平", "重庆武隆"],
        "❤️河北": ["河北", "石家庄", "唐山", "秦皇岛", "邯郸", "邢台", "保定", "张家口", "承德", "沧州", "廊坊", "衡水", "河北卫视", "河北经济", "河北都市", "河北影视", "河北少儿", "河北公共", "河北农民", "河北杂技", "石家庄新闻综合", "石家庄娱乐", "石家庄生活", "石家庄都市", "石家庄财经"],
        "❤️山西": ["山西", "太原", "大同", "阳泉", "长治", "晋城", "朔州", "晋中", "运城", "忻州", "临汾", "吕梁", "山西卫视", "山西经济与科技", "山西影视频道", "山西社会与法治", "山西公共", "山西少儿", "山西黄河", "太原新闻", "太原经济生活", "太原社教法制", "太原影视频道", "太原百姓"],
        "❤️辽宁": ["辽宁", "沈阳", "大连", "鞍山", "抚顺", "本溪", "丹东", "锦州", "营口", "阜新", "辽阳", "盘锦", "铁岭", "朝阳", "葫芦岛", "辽宁卫视", "辽宁都市", "辽宁影视剧", "辽宁生活", "辽宁体育", "辽宁教育", "辽宁经济", "辽宁公共", "辽宁北方", "辽宁宜佳", "沈阳新闻", "沈阳经济", "沈阳生活", "沈阳公共", "沈阳影视", "大连新闻综合", "大连生活", "大连公共", "大连财经", "大连体育", "大连少儿", "大连影视"],
        "❤️吉林": ["吉林", "长春", "吉林", "四平", "辽源", "通化", "白山", "松原", "白城", "延边", "吉林卫视", "吉林都市", "吉林生活", "吉林影视", "吉林乡村", "吉林公共", "吉林综艺", "吉林7频道", "长春综合", "长春娱乐", "长春市民", "长春经济", "长春汽开"],
        "❤️黑龙江": ["黑龙江", "哈尔滨", "齐齐哈尔", "鸡西", "鹤岗", "双鸭山", "大庆", "伊春", "佳木斯", "七台河", "牡丹江", "黑河", "绥化", "大兴安岭", "黑龙江卫视", "黑龙江新闻法治", "黑龙江都市", "黑龙江影视频道", "黑龙江文体", "黑龙江公共", "黑龙江科教", "黑龙江农业", "黑龙江少儿", "哈尔滨新闻综合", "哈尔滨生活", "哈尔滨娱乐", "哈尔滨影视"],
        "❤️江苏": ["江苏", "南京", "无锡", "徐州", "常州", "苏州", "南通", "连云港", "淮安", "盐城", "扬州", "镇江", "泰州", "宿迁", "江苏卫视", "江苏城市", "江苏综艺", "江苏影视", "江苏教育", "江苏体育休闲", "江苏公共", "江苏国际", "优漫卡通", "南京新闻综合", "南京教科", "南京生活", "南京娱乐", "南京十八", "南京少儿", "苏州新闻综合", "苏州社会经济", "苏州文化生活", "苏州电影娱乐"],
        "❤️浙江": ["浙江", "杭州", "宁波", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州", "舟山", "台州", "丽水", "浙江卫视", "浙江新闻", "浙江经济生活", "浙江科教", "浙江影视娱乐", "浙江民生休闲", "浙江经视", "浙江少儿", "浙江国际", "钱江都市", "杭州综合", "杭州明珠", "杭州生活", "杭州影视", "杭州少儿", "杭州导视", "宁波新闻综合", "宁波经济生活", "宁波都市文体", "宁波影视剧", "温州新闻综合", "温州经济科教", "温州都市生活", "嘉兴新闻综合", "湖州新闻综合", "绍兴新闻综合", "金华新闻综合", "衢州新闻综合", "舟山新闻综合", "台州新闻综合", "丽水新闻综合"],
        "❤️安徽": ["安徽", "合肥", "芜湖", "蚌埠", "淮南", "马鞍山", "淮北", "铜陵", "安庆", "黄山", "滁州", "阜阳", "宿州", "六安", "亳州", "池州", "宣城", "安徽卫视", "安徽经济生活", "安徽影视频道", "安徽综艺体育", "安徽公共", "安徽科教", "安徽农业", "安徽国际", "合肥新闻", "合肥生活", "合肥教育", "合肥财经", "合肥故事", "合肥文体"],
        "❤️福建": ["福建", "福州", "厦门", "莆田", "三明", "泉州", "漳州", "南平", "龙岩", "宁德", "东南卫视", "海峡卫视", "福建综合", "福建新闻", "福建电视剧", "福建经济", "福建体育", "福建公共", "福建少儿", "福州新闻", "福州影视", "福州生活", "福州少儿", "厦门新闻", "厦门生活", "厦门影视", "厦门综艺"],
        "❤️江西": ["江西", "南昌", "景德镇", "萍乡", "九江", "新余", "鹰潭", "赣州", "吉安", "宜春", "抚州", "上饶", "江西卫视", "江西新闻", "江西都市", "江西经济生活", "江西影视", "江西公共", "江西少儿", "江西教育", "江西红色经典", "南昌新闻", "南昌都市", "南昌资讯", "南昌影视娱乐"],
        "❤️山东": ["山东", "济南", "青岛", "淄博", "枣庄", "东营", "烟台", "潍坊", "济宁", "泰安", "威海", "日照", "莱芜", "临沂", "德州", "聊城", "滨州", "菏泽", "山东卫视", "山东齐鲁", "山东体育", "山东农科", "山东公共", "山东新闻", "山东影视", "山东综艺", "山东生活", "山东少儿", "山东教育", "济南新闻综合", "济南都市", "济南娱乐", "济南影视", "济南商务", "济南少儿", "青岛新闻综合", "青岛经济生活", "青岛影视", "青岛都市", "青岛娱乐"],
        "❤️河南": ["河南", "郑州", "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡", "焦作", "濮阳", "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口", "驻马店", "济源", "河南卫视", "河南都市", "河南民生", "河南法制", "河南电视剧", "河南新闻", "河南公共", "河南乡村", "河南国际", "梨园春", "郑州新闻综合", "郑州商都", "郑州文体旅游", "郑州影视戏曲", "郑州教育", "郑州都市", "郑州经济生活"],
        "❤️湖北": ["湖北", "武汉", "黄石", "十堰", "宜昌", "襄阳", "鄂州", "荆门", "孝感", "荆州", "黄冈", "咸宁", "随州", "恩施", "仙桃", "潜江", "天门", "神农架", "湖北卫视", "湖北经视", "湖北综合", "湖北公共", "湖北影视", "湖北教育", "湖北生活", "湖北美嘉", "湖北垄上", "武汉新闻综合", "武汉电视剧", "武汉科技生活", "武汉经济", "武汉文体", "武汉外语", "武汉少儿", "武汉教育"],
        "❤️湖南": ["湖南", "长沙", "株洲", "湘潭", "衡阳", "邵阳", "岳阳", "常德", "张家界", "益阳", "郴州", "永州", "怀化", "娄底", "湘西", "湖南卫视", "湖南经视", "湖南都市", "湖南娱乐", "湖南电视剧", "湖南公共", "湖南电影", "湖南教育", "湖南国际", "金鹰卡通", "金鹰纪实", "快乐购", "长沙新闻", "长沙政法", "长沙女性", "长沙经贸", "长沙公共", "长沙影视", "长沙娱乐"],
        "❤️广东": ["广东", "广州", "深圳", "珠海", "汕头", "佛山", "韶关", "湛江", "肇庆", "江门", "茂名", "惠州", "梅州", "汕尾", "河源", "阳江", "清远", "东莞", "中山", "潮州", "揭阳", "云浮", "广东卫视", "大湾区卫视", "珠江频道", "广东新闻", "广东公共", "广东经济科教", "广东体育", "广东影视", "广东少儿", "广东移动", "广东综艺", "广东国际", "广州综合", "广州新闻", "广州影视", "广州法治", "广州竞赛", "广州经济", "广州少儿", "广州购物", "深圳都市", "深圳电视剧", "深圳财经生活", "深圳娱乐", "深圳体育健康", "深圳公共", "深圳少儿", "深圳移动电视", "深圳宝安", "深圳龙岗"],
        "❤️海南": ["海南", "海口", "三亚", "三沙", "儋州", "五指山", "琼海", "文昌", "万宁", "东方", "定安", "屯昌", "澄迈", "临高", "白沙", "昌江", "乐东", "陵水", "保亭", "琼中", "海南卫视", "海南新闻", "海南经济", "海南文旅", "海南公共", "海南少儿", "海南影视", "海南电广", "海口综合", "海口生活娱乐", "海口经济", "海口法制", "海口旅游", "三亚新闻", "三亚公共"],
        "❤️四川": ["四川", "成都", "自贡", "攀枝花", "泸州", "德阳", "绵阳", "广元", "遂宁", "内江", "乐山", "南充", "眉山", "宜宾", "广安", "达州", "雅安", "巴中", "资阳", "阿坝", "甘孜", "凉山", "四川卫视", "四川新闻", "四川经济", "四川文化旅游", "四川影视文艺", "四川科教", "四川乡村", "四川公共", "四川妇女儿童", "四川康巴藏语", "四川峨眉电影", "成都新闻综合", "成都经济资讯", "成都都市生活", "成都影视文艺", "成都公共", "成都少儿", "成都高新", "成都金牛", "成都武侯", "成都成华", "成都锦江", "成都青羊", "成都郫都", "成都龙泉驿", "成都新都", "成都温江", "成都双流", "成都青白江"],
        "❤️贵州": ["贵州", "贵阳", "遵义", "六盘水", "安顺", "毕节", "铜仁", "黔西南", "黔东南", "黔南", "贵州卫视", "贵州公共", "贵州影视文艺", "贵州科教健康", "贵州经济", "贵州5频道", "贵州移动", "贵阳新闻综合", "贵阳经济生活", "贵阳都市", "贵阳影视", "贵阳法制"],
        "❤️云南": ["云南", "昆明", "曲靖", "玉溪", "保山", "昭通", "丽江", "普洱", "临沧", "楚雄", "红河", "文山", "西双版纳", "大理", "德宏", "怒江", "迪庆", "云南卫视", "云南都市", "云南娱乐", "云南公共", "云南少儿", "云南国际", "云南科教", "云南经济生活", "云南影视", "澜湄国际", "昆明新闻综合", "昆明经济生活", "昆明影视娱乐", "昆明科教", "昆明公共", "昆明安宁", "昆明呈贡", "昆明官渡", "昆明西山", "昆明盘龙", "昆明五华", "昆明晋宁", "昆明东川", "昆明宜良", "昆明石林", "昆明富民", "昆明嵩明", "昆明禄劝", "昆明寻甸"],
        "❤️陕西": ["陕西", "西安", "铜川", "宝鸡", "咸阳", "渭南", "延安", "汉中", "榆林", "安康", "商洛", "陕西卫视", "陕西新闻", "陕西都市青春", "陕西生活", "陕西影视", "陕西公共", "陕西体育休闲", "陕西农林科技", "陕西秦腔", "陕西教育", "西安新闻综合", "西安白鸽都市", "西安影视", "西安资讯", "西安教育", "西安乐活", "西安丝路", "西安商务", "西安健康", "西安文化", "西安音乐", "西安戏曲"],
        "❤️甘肃": ["甘肃", "兰州", "嘉峪关", "金昌", "白银", "天水", "武威", "张掖", "平凉", "酒泉", "庆阳", "定西", "陇南", "临夏", "甘南", "甘肃卫视", "甘肃经济", "甘肃文化影视频道", "甘肃公共应急", "甘肃都市", "甘肃少儿", "甘肃移动", "甘肃数字", "兰州新闻综合", "兰州生活经济", "兰州文旅", "兰州公共", "兰州综艺体育"],
        "❤️青海": ["青海", "西宁", "海东", "海北", "黄南", "海南州", "果洛", "玉树", "海西", "青海卫视", "青海新闻综合", "青海经济生活", "青海都市", "青海影视", "青海公共", "安多藏语", "康巴藏语", "青海移动", "西宁新闻", "西宁生活服务", "西宁文旅", "西宁教育"],
        "❤️台湾": ["台湾", "台北", "新北", "桃园", "台中", "台南", "高雄", "基隆", "新竹", "嘉义", "TVBS", "中天", "东森", "三立", "民视", "台视", "中视", "华视", "公视", "纬来", "非凡", "年代", "东森新闻", "TVBS新闻", "三立新闻", "民视新闻", "台视新闻", "中视新闻", "华视新闻", "东森财经", "东森电影", "东森戏剧", "东森综合", "东森超视", "东森幼幼", "TVBS欢乐", "TVBS精彩", "三立都会", "三立台湾", "三立国际", "民视无线", "民视交通", "民视新闻台", "台视综合", "台视财经", "中视经典", "中视菁采", "华视教育", "华视新闻", "公视2", "公视3", "小公视", "客家", "原视", "国会", "TaiwanPlus"],
        "❤️内蒙古": ["内蒙古", "呼和浩特", "包头", "乌海", "赤峰", "通辽", "鄂尔多斯", "呼伦贝尔", "巴彦淖尔", "乌兰察布", "兴安", "锡林郭勒", "阿拉善", "内蒙古卫视", "内蒙古新闻", "内蒙古经济生活", "内蒙古影视", "内蒙古文体娱乐", "内蒙古农牧", "内蒙古少儿", "内蒙古蒙语", "呼和浩特新闻综合", "呼和浩特都市生活", "呼和浩特影视娱乐", "包头新闻综合", "包头经济", "包头生活", "包头影视", "包头教育", "鄂尔多斯新闻", "鄂尔多斯经济", "鄂尔多斯城市", "鄂尔多斯影视"],
        "❤️广西": ["广西", "南宁", "柳州", "桂林", "梧州", "北海", "防城港", "钦州", "贵港", "玉林", "百色", "贺州", "河池", "来宾", "崇左", "广西卫视", "广西综艺旅游", "广西新闻", "广西科教", "广西公共", "广西影视", "广西国际", "南宁新闻综合", "南宁影视娱乐", "南宁都市生活", "南宁公共", "南宁科教", "柳州新闻", "桂林新闻", "桂林公共"],
        "❤️西藏": ["西藏", "拉萨", "日喀则", "昌都", "林芝", "山南", "那曲", "阿里", "西藏卫视", "藏语", "西藏影视文化", "西藏经济生活", "西藏新闻", "拉萨综合", "拉萨藏语"],
        "❤️宁夏": ["宁夏", "银川", "石嘴山", "吴忠", "固原", "中卫", "宁夏卫视", "宁夏公共", "宁夏经济", "宁夏影视", "宁夏少儿", "银川公共", "银川生活", "银川文体", "银川新闻综合", "石嘴山综合", "吴忠综合", "固原综合", "中卫综合"],
        "❤️新疆": ["新疆", "乌鲁木齐", "克拉玛依", "吐鲁番", "哈密", "昌吉", "博尔塔拉", "巴音郭楞", "阿克苏", "克孜勒苏", "喀什", "和田", "伊犁", "塔城", "阿勒泰", "石河子", "阿拉尔", "图木舒克", "五家渠", "北屯", "铁门关", "双河", "可克达拉", "昆玉", "胡杨河", "新星", "新疆卫视", "新疆汉语", "新疆维语", "新疆哈语", "新疆少儿", "新疆影视", "新疆经济生活", "新疆体育健康", "新疆教育", "新疆新闻", "新疆法制报", "兵团卫视", "兵团", "乌鲁木齐新闻综合", "乌鲁木齐影视", "乌鲁木齐都市", "乌鲁木齐旅游", "乌鲁木齐娱乐", "乌鲁木齐科教", "乌鲁木齐经济"],
        "❤️香港": ["香港", "TVB", "翡翠", "明珠", "本港", "亚视", "有线", "开电视", "香港国际", "香港卫视", "凤凰卫视", "凤凰资讯", "凤凰香港", "星空", "Channel[V]", "ViuTV", "Now", "香港电台", "RTHK", "香港商业", "新城", "无线", "J2", "TVB经典", "TVB新闻", "TVB娱乐", "TVB明珠", "TVB翡翠", "TVB互动", "TVB生活", "TVB为食", "TVB8", "TVB星河", "TVBS", "TVBS新闻", "TVBS欢乐", "TVBS精彩", "香港开电视", "香港国际财经", "香港赛马", "美亚", "天映", "华娱", "东风", "星空华文", "凤凰中文", "凤凰欧洲", "凤凰美洲", "凤凰澳洲"],
        "❤️澳门": ["澳门", "澳视", "澳亚", "澳广视", "澳门莲花", "澳门资讯", "澳门体育", "澳门综艺", "澳门MACAU", "澳视葡文", "澳视高清", "澳视澳门", "澳亚卫视", "澳门卫视", "澳门莲花", "澳门互动", "澳视卫星", "澳视生活", "澳视新闻", "澳视体育", "澳视综艺", "澳视文化", "澳视教育", "澳视经济", "澳视旅游", "澳视音乐", "澳门电台", "澳门莲花卫视", "澳门有线电视", "澳门天浪"],
    }

    for group_name, keywords in province_map.items():
        matched = []
        for ch in channels:
            if ch.url in grouped_urls_set:
                continue
            if any(kw in ch.name for kw in keywords):
                matched.append(ch)
                grouped_urls_set.add(ch.url)
        if matched:
            groups[group_name] = matched

    remaining = [c for c in channels if c.url not in grouped_urls_set]
    if remaining:
        groups["❤️其他频道"] = remaining

    result = OrderedDict()
    for group_name, channels_list in groups.items():
        if channels_list:
            result[group_name] = OrderedDict()
            result[group_name]["全部"] = channels_list

    return result


class ChannelMerger:
    """
    频道合并器：
    - merge(): 仅去重，不做数量限制
    - limit_by_type(): 测速后按类型限制数量
    - limit_by_group(): 分组后限制每组数量
    """

    def __init__(
        self,
        multicast_limit: int = 4,
        mobile_multicast_limit: int = 6,
        unicast_limit: int = 15,
        max_per_group: int = 300
    ):
        self.multicast_limit = multicast_limit
        self.mobile_multicast_limit = mobile_multicast_limit
        self.unicast_limit = unicast_limit
        self.max_per_group = max_per_group

    def merge(self, channels: list[Channel]) -> list[Channel]:
        """仅去重：按URL去重，保留所有（测速后决定取舍）"""
        seen = {}
        for ch in channels:
            if ch.url not in seen:
                seen[ch.url] = ch
            else:
                existing = seen[ch.url]
                if ch.speed is not None and existing.speed is None:
                    seen[ch.url] = ch
                elif ch.speed is not None and existing.speed is not None and ch.speed > existing.speed:
                    seen[ch.url] = ch
        return list(seen.values())

    def _is_mobile(self, ch: Channel) -> bool:
        """
        判断是否为移动源（URL特征 + IPv6前缀 + isp字段）
        优化版：避免误匹配，支持各省移动域名和IPv6 2409前缀
        """
        url_low = ch.url.lower().strip()

        # 1. URL 中的移动域名特征（带点分隔，避免误匹配）
        mobile_domains = [
            "chinamobile.com", "cmcc", "mobiletv", ".migu.",
            "mobaibox", "bestv", "bcs.ott", "ott.mobai",
            "zj.chinamobile", "gd.chinamobile", "js.chinamobile",
            "sh.chinamobile", "bj.chinamobile", "sd.chinamobile",
            "hn.chinamobile", "hb.chinamobile", "ah.chinamobile",
            "fj.chinamobile", "sc.chinamobile", "jx.chinamobile",
            "ln.chinamobile", "sn.chinamobile", "cq.chinamobile",
            "he.chinamobile", "sx.chinamobile", "nm.chinamobile",
            "hl.chinamobile", "jl.chinamobile", "zj.cmcc",
        ]
        if any(d in url_low for d in mobile_domains):
            return True

        # 2. IPv6 前缀（2409 = 中国移动）
        if "[2409:" in url_low or "2409:" in url_low:
            return True

        # 3. isp 字段（从 Channel 对象读取）
        isp = getattr(ch, "isp", "") or ch.extra.get("isp", "")
        if isp and ("移动" in str(isp) or "mobile" in str(isp).lower()):
            return True

        # 4. 组播地址中移动内网特征（依赖 isp/source 字段）
        if url_low.startswith(("udp://[ff15:", "rtp://[ff15:", "udp://[ff35:", "rtp://[ff35:")):
            if isp == "移动" or ch.source == "移动" or ch.extra.get("source") == "移动":
                return True

        return False

    def classify(self, ch: Channel) -> Tuple[str, bool]:
        """分类频道类型"""
        url = ch.url.lower().strip()
        is_multicast = url.startswith(("udp://", "rtp://", "rtsp://")) or url.startswith(("http://239.", "http://233.", "http://232."))
        is_mobile = self._is_mobile(ch)
        if is_multicast:
            return ("mobile_multicast" if is_mobile else "multicast"), is_multicast
        return ("mobile_unicast" if is_mobile else "unicast"), False

    def limit_by_type(self, channels: list[Channel]) -> list[Channel]:
        """
        测速后按类型限制数量：
        - 只保留有速度的频道（无速度一律丢弃）
        - 移动组播：保留最快的 MOBILE_MULTICAST_LIMIT 个
        - 普通组播：保留最快的 MULTICAST_LIMIT 个
        - 移动单播：有速度的全保留（不限数量）
        - 普通单播：保留最快的 UNICAST_LIMIT 个
        """
        # 先过滤掉无速度的
        speed_ok = [c for c in channels if c.speed is not None]

        buckets = {
            "multicast": [],
            "mobile_multicast": [],
            "unicast": [],
            "mobile_unicast": []
        }

        for ch in speed_ok:
            ctype, _ = self.classify(ch)
            buckets[ctype].append(ch)

        def sort_speed(chs):
            return sorted(chs, key=lambda x: x.speed, reverse=True)

        # 组播各自限制数量
        limited_mc = sort_speed(buckets["multicast"])[:self.multicast_limit]
        limited_mmc = sort_speed(buckets["mobile_multicast"])[:self.mobile_multicast_limit]

        # 单播：普通限制，移动不限
        limited_uc = sort_speed(buckets["unicast"])[:self.unicast_limit]
        limited_muc = sort_speed(buckets["mobile_unicast"])  # 不限制数量

        result = limited_mc + limited_mmc + limited_uc + limited_muc

        def final_sort_key(x):
            is_mc = x.url.lower().strip().startswith(("udp://", "rtp://", "rtsp://", "http://239.", "http://233.", "http://232."))
            return (0 if is_mc else 1, -(x.speed or 0))

        return sorted(result, key=final_sort_key)

    def limit_by_group(self, channels: list[Channel]) -> list[Channel]:
        """
        分组后限制每组数量 - 方案A：
        - 移动源全保留（不限制数量）
        - 其他源按速度排序，保留前 max_per_group 个
        """
        mobile = [c for c in channels if self._is_mobile(c)]
        other = [c for c in channels if not self._is_mobile(c)]

        # 其他源按速度排序，限制数量
        other.sort(key=lambda x: x.speed if x.speed is not None else -1, reverse=True)
        other_limited = other[:self.max_per_group]

        # 移动源全保留，不限制
        return mobile + other_limited
