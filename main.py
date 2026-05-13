    # 5. 按模板分组导出
    log.info("[5/5] 导出结果...")
    
    # 先扁平化所有频道（用于ISP分组导出）
    all_channels_flat = []
    for group in grouped_channels.values():
        for sub_group in group.values():
            all_channels_flat.extend(sub_group)
    
    # 按模板分组导出（原有）
    TXTExporter.export_by_template(grouped_channels, str(OUTPUT_DIR / "result.txt"))
    log.info(f"  ✓ TXT 模板导出完成")
    
    M3UExporter.export_by_template(grouped_channels, str(OUTPUT_DIR))
    log.info(f"  ✓ M3U 模板导出完成")
    
    # 新增：按ISP分组导出
    # 全部频道
    M3UExporter.export_all(all_channels_flat, str(OUTPUT_DIR / "result-all.m3u"))
    log.info(f"  ✓ 全部M3U导出完成")
    
    # 移动优先
    M3UExporter.export_mobile_first(all_channels_flat, str(OUTPUT_DIR / "result-mobile-first.m3u"))
    TXTExporter.export_mobile_first(all_channels_flat, str(OUTPUT_DIR / "result-mobile-first.txt"))
    log.info(f"  ✓ 移动优先导出完成")
    
    # 其他源
    M3UExporter.export_other(all_channels_flat, str(OUTPUT_DIR / "result-other.m3u"))
    TXTExporter.export_other(all_channels_flat, str(OUTPUT_DIR / "result-other.txt"))
    log.info(f"  ✓ 其他源导出完成")
    
    # 速度日志
    LogExporter.export_speed_log(all_channels_flat, str(LOG_DIR / "speed_test.log"))
    log.info(f"  ✓ 测速日志导出完成")
