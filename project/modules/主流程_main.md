# main  (flow_id=main, 组=—, 块数=27)
# 转录时间 2026-10-08 17:30 · 来源 studio-mcp flow.blocks.list(detail) · 编号=画布块序号+1
# 指令名/参数名=影刀官方内置指令目录（见 tools/sb_blocks_zh.json）· 行尾[英文ID]=机器名，可 grep

001  调用流程  模块名称=process65  →00自动化登录  [process.run]
002  调用流程  模块名称=process51  →商品数据采集  [process.run]
003  获取当前日期时间  [datetime.now]
004  日期时间转换为文本  日期时间=变量=当前时间  时间格式=%Y年%m月%d日%H时%M分  [datetime.to_string]
005  数据表格导出  文件夹=custom  文件夹路径=F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\project\runtime\product_raw  文件名称=拼接=[商品_;变量=当前时间;.xlsx]  export_header=表达式=False  [programing.databook.export_data]
006  打印日志  日志类型=info  日志内容=变量=竞品商品原始数据Excel  [programing.log]
007  清空数据表格  [programing.databook.remove_all_rows]
008  调用流程  模块名称=process62  arguments.竞品商品原始数据Excel=表达式=竞品商品原始数据Excel  →B-SKU数据采集  [process.run]
009  获取当前日期时间  [datetime.now]
010  日期时间转换为文本  日期时间=变量=当前时间  时间格式=%Y年%m月%d日%H时%M分  [datetime.to_string]
011  数据表格导出  文件夹=custom  文件夹路径=F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\project\runtime\product_alllraw  文件名称=拼接=[竞品_;变量=当前时间;.xlsx]  export_header=表达式=True  [programing.databook.export_data]
012  设置变量  变量类型=str  变量值=表达式=f"F:/Programs/RPA自动化/1-淘宝竞品价格监控自动化/project/runtime/product_clean/竞品_{当前时间}.xlsx"  [programing.variable]
013  获取当前日期时间  [datetime.now]
014  日期时间转换为文本  日期时间=变量=当前时间  时间格式=%Y年%m月%d日%H时%M分  [datetime.to_string]
015  调用模块  模块名称=product_clean  方法名称=main  方法参数列表=group_array=[filepath=variable=竞品原始Excel;;timestamp=variable=当前时间;out_path=variable=竞品清洗Excel;]  返回值类型=any  [process.invoke_module]
016  设置变量  变量类型=str  变量值=表达式=f"F:/Programs/RPA自动化/1-淘宝竞品价格监控自动化/project/runtime/product_clean/竞品_{当前时间}.xlsx"  [programing.variable]
017  获取当前日期时间  [datetime.now]
018  日期时间转换为文本  日期时间=变量=当前时间  时间格式=%Y年%m月%d日%H时%M分  [datetime.to_string]
019  调用模块  模块名称=report  方法名称=main  方法参数列表=group_array=[excel_path=variable=竞品清洗Excel;output_path=variable=竞品清洗Excel;;timestamp=variable=当前时间]  返回值类型=any  [process.invoke_module]
020  设置变量  变量类型=str  变量值=表达式=f"F:/Programs/RPA自动化/1-淘宝竞品价格监控自动化/project/runtime/report/竞品_{当前时间}.xlsx"  [programing.variable]
021  获取当前日期时间  [datetime.now]
022  日期时间转换为文本  日期时间=变量=当前时间  时间格式=%Y年%m月%d日%H时%M分  [datetime.to_string]
023  调用模块  模块名称=report  方法名称=main  方法参数列表=group_array=[excel_path=variable=竞品清洗Excel;output_path=variable=竞品报表Excel;;timestamp=variable=当前时间]  返回值类型=any  [process.invoke_module]
024  设置变量  变量类型=str  变量值=F:/Programs/RPA自动化/1-淘宝竞品价格监控自动化/project/config/database.json  [programing.variable]
025  调用模块  模块名称=product_ingest  方法名称=main  方法参数列表=group_array=[cleaned_path=variable=竞品清洗Excel;config_path=variable=config_path]  返回值类型=any  [process.invoke_module]
026  调用模块  模块名称=sku_ingest  方法名称=main  方法参数列表=group_array=[cleaned_path=variable=竞品清洗Excel;config_path=variable=config_path]  返回值类型=any  [process.invoke_module]
027  调用模块  模块名称=alert  方法名称=main  方法参数列表=group_array=[config_path=variable=config_path;webhook_url=variable=glv['dingtalk_webhook'];keyword=variable=glv['dingtalk_secret'];drop_pct=expression=5.0]  返回值类型=any  [process.invoke_module]

## 审核疑点（2026-09-30 · 对照模块 .py 签名交叉核对，仅记录，未改画布）
- **011 路径拼写**：导出目录 `product_alllraw`（3个l），磁盘实际为 `runtime/product_allraw` → 会静默新建错误目录，下游按实际名找不到文件
- **019 多余且有害的 report 调用**：`output_path=input 竞品清洗Excel`（report.py 会覆盖清洗产物），023 再调用时读到的已是被日报覆盖的文件而非 13 列清洗表；015→019→023 三连里 019 疑似返工遗留，应删（023 单独保留即可，或改 output_path）
- **027 alert keyword 传错**：alert.py 的 `keyword` 是"搜索关键词（拼消息标题）"，画布传了 `glv['dingtalk_secret']`（钉钉加签密钥）→ 标题出现密钥字样=泄露；且 alert.py 本身不实现加签，机器人若为"加签"型则发送会 401（若是"自定义关键词"型，此参数应传关键词文本而非 secret）
- **012/016 重复赋值**：`竞品清洗Excel` 同一表达式赋值两次（冗余无害）

> 复核 2026-10-08（重转录后逐条对照新画布）：**四条疑点在原位置全部仍成立**（011/012/016/019/023/027 块号未变）。
