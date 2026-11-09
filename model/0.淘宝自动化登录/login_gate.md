# login_gate  (flow_id=process1, 组=0.淘宝自动化登录, 块数=16)
# 来源 studio-mcp flow.blocks.list(detail) · 编号=画布块序号+1
# 指令名/参数名=影刀官方内置指令目录（见 tools/sb_blocks_zh.json）· 行尾[英文ID]=机器名，可 grep

001  Try  [programing.try]
002  调用模块  模块名称=login_entry  方法名称=main  方法参数列表=group_array=[]  返回值类型=dict  [process.invoke_module]
003  保存自定义数据  读取Key=login_state  数据内容=表达式=结果['state']  [process.write_to_storage]
004  保存自定义数据  读取Key=login_method  数据内容=表达式=结果['method']  [process.write_to_storage]
005  保存自定义数据  读取Key=login_result  数据内容=表达式=结果['result']  [process.write_to_storage]
006  保存自定义数据  读取Key=last_login_at  数据内容=表达式=结果['login_at']  [process.write_to_storage]
007  IF 条件  对象1=表达式=结果['need_manual']  关系=is true  操作符参数={}  [workflow.if]
008  调用流程  模块名称=process2  →login_qr  [process.run]
009  End IF  [workflow.endif]
010  Catch  [programing.catch]
011  保存自定义数据  读取Key=login_state  数据内容=cold_down  [process.write_to_storage]
012  保存自定义数据  读取Key=login_result  数据内容=表达式=str(exception)  [process.write_to_storage]
013  调用模块  模块名称=login_entry  方法名称=alert  方法参数列表=group_array=[text=登录流程异常;title=登录告警]  返回值类型=dict  [process.invoke_module]
014  退出当前流程  [process.return]
015  End Try  [programing.endtry]
016  退出当前流程  [process.return]
