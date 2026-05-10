读取m3u/txt/json、整合去重测速、输出txt/m3u、使用config.cpython-314.pyc加速
iptv-processor/
├── .github/
│   └── workflows/
│       └── update.yml          # GitHub Actions 自动工作流
├── config/                     # 配置目录（会被编译加速）
│   ├── __init__.py
│   ├── settings.py             # 主配置（会被编译为.pyc）
│   ├── sources.json            # 订阅源列表
│   ├── template.txt            # 频道模板
│   └── blacklist.txt           # URL黑名单
├── core/                       # 核心处理模块
│   ├── __init__.py
│   ├── parser.py               # m3u/txt/json 解析器
│   ├── merger.py               # 源整合去重
│   ├── speed_tester.py         # 测速模块
│   └── exporter.py             # 输出生成器
├── utils/
│   ├── __init__.py
│   ├── cache.py                # 测速缓存
│   └── logger.py               # 日志工具
├── output/                     # 输出目录
│   ├── result.m3u
│   ├── result.txt
│   └── speed_test.log
├── tests/
├── main.py                     # 入口文件
├── requirements.txt
└── README.md