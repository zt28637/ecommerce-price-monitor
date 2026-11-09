# login_qr  (flow_id=process2, 组=0.淘宝自动化登录, 块数=9)
# 来源 studio-mcp flow.blocks.list(detail) · 编号=画布块序号+1
# 指令名/参数名=影刀官方内置指令目录（见 tools/sb_blocks_zh.json）· 行尾[英文ID]=机器名，可 grep

001  调用模块  模块名称=login_entry  方法名称=wait_manual  方法参数列表=group_array=[]  返回值类型=dict  [process.invoke_module]
002  保存自定义数据  读取Key=login_state  数据内容=表达式=结果['state']  [process.write_to_storage]
003  保存自定义数据  读取Key=login_method  数据内容=表达式=结果['method']  [process.write_to_storage]
004  保存自定义数据  读取Key=login_result  数据内容=表达式=结果['result']  [process.write_to_storage]
005  保存自定义数据  读取Key=last_login_at  数据内容=表达式=结果['login_at']  [process.write_to_storage]
006  IF 条件  对象1=表达式=结果['result']  关系=!=  对象2=ok  操作符参数={}  [workflow.if]
007  调用模块  模块名称=login_entry  方法名称=alert  方法参数列表=group_array=[text=expression=f"登录告警 | 结果={结果['result']} | 方式=manual";title=登录告警]  返回值类型=dict  [process.invoke_module]
008  End IF  [workflow.endif]
009  退出当前流程  [process.return]
