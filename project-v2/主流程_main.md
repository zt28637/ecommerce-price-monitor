# main  (flow_id=main, 组=—, 块数=18)
# 转录时间 2026-11-08 00:36 · 来源 studio-mcp flow.blocks.list(detail) · 编号=画布块序号+1
# 指令名/参数名=影刀官方内置指令目录（见 tools/sb_blocks_zh.json）· 行尾[英文ID]=机器名，可 grep

001  调用流程  模块名称=process3  →login_open  [process.run]
002  调用流程  模块名称=process1  →login_gate  [process.run]
003  读取自定义数据  Key=login_state  [process.read_from_storage]
004  IF 条件  对象1=变量=登录状态  关系=!=  对象2=logged_in  操作符参数={}  [workflow.if]
005  读取自定义数据  Key=login_result  [process.read_from_storage]
006  IF 条件  对象1=表达式=登录结果 == 'browser_down' or 登录结果 == 'attach_failed'  关系=is true  操作符参数={}  [workflow.if]
007  调用流程  模块名称=process3  →login_open  [process.run]
008  调用流程  模块名称=process1  →login_gate  [process.run]
009  读取自定义数据  Key=login_state  [process.read_from_storage]
010  IF 条件  对象1=变量=登录状态重试  关系=!=  对象2=logged_in  操作符参数={}  [workflow.if]
011  打印日志  日志类型=error  日志内容="登录未通过（重建浏览器后仍失败），终止本轮"  [programing.log]
012  退出当前流程  [process.return]
013  End IF  [workflow.endif]
014  Else  [workflow.else]
015  打印日志  日志类型=error  日志内容="登录未通过，终止本轮"  [programing.log]
016  退出当前流程  [process.return]
017  End IF  [workflow.endif]
018  End IF  [workflow.endif]
