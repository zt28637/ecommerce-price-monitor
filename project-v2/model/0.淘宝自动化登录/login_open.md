# login_open  (flow_id=process3, 组=0.淘宝自动化登录, 块数=4)
# 转录时间 2026-11-08 22:19 · 来源 studio-mcp flow.blocks.list(detail) · 编号=画布块序号+1
# 指令名/参数名=影刀官方内置指令目录（见 tools/sb_blocks_zh.json）· 行尾[英文ID]=机器名，可 grep

001  调用模块  模块名称=login_browser  方法名称=ensure  方法参数列表=group_array=[]  返回值类型=dict  [process.invoke_module]
002  保存自定义数据  读取Key=browser_ok  数据内容=表达式=浏览器结果['ok']  [process.write_to_storage]
003  保存自定义数据  读取Key=browser_detail  数据内容=表达式=浏览器结果['detail']  [process.write_to_storage]
004  退出当前流程  [process.return]
