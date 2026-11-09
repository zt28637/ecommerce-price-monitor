# 使用提醒:
# 1. xbot包提供软件自动化、数据表格、Excel、日志、AI等功能
# 2. package包提供访问当前应用数据的功能，如获取元素、访问全局变量、资源文件等功能
# 3. 当此模块作为流程独立运行时执行main函数
# 4. 可视化流程中可以通过"调用模块"的指令使用此模块

import json
import xbot
from xbot import print, sleep
from .import package
from .package import variables as glv


def main(args):
    # 单文件运行时 args 为空字典，自动用测试数据
    if isinstance(args, dict) and len(args) == 0:
        args = json.dumps([
            {"商品ID": "826399795851", "商品名称": "【重磅新品】小天才电话手表z7pro新款防水定位前后双摄4G全网通学生儿童视频通话z6pro少年版正品官方旗舰店",
             "店铺名称": "小天才智能手表旗舰店", "商品主图链接": "https://gw.alicdn.com/imgextra/O1CN01mo2Dmx1E4XBCvkrRe_!!2217726390298-0-yinheaigc.jpg_580x580q90.jpg_.webp",
             "SKUID": "6152851227093", "SKU名称": "主播推荐 Z6 Pro少年版陨石灰",
             "SKU图片链接": "http://img.alicdn.com/imgextra/i2/2217726390298/O1CN01TEAlce1E4X9BQiHTM_!!2217726390298.jpg",
             "实际售价": "999.0", "原价": "2198.0", "活动价格": "",
             "销量": "4000+人收货", "采集时间": "2026-08-05", "数据来源": "api"},
            {"商品ID": "826399795851", "商品名称": "【重磅新品】小天才电话手表z7pro新款防水定位前后双摄4G全网通学生儿童视频通话z6pro少年版正品官方旗舰店",
             "店铺名称": "小天才智能手表旗舰店", "商品主图链接": "https://gw.alicdn.com/imgextra/O1CN01mo2Dmx1E4XBCvkrRe_!!2217726390298-0-yinheaigc.jpg_580x580q90.jpg_.webp",
             "SKUID": "6152851227092", "SKU名称": "主播推荐 Z6 Pro少年版茶金白",
             "SKU图片链接": "http://img.alicdn.com/imgextra/i2/2217726390298/O1CN01EZBrJu1E4X9BQfnd3_!!2217726390298.jpg",
             "实际售价": "999.0", "原价": "2198.0", "活动价格": "",
             "销量": "4000+人收货", "采集时间": "2026-08-05", "数据来源": "api"},
            {"商品ID": "826399795851", "商品名称": "【重磅新品】小天才电话手表z7pro新款防水定位前后双摄4G全网通学生儿童视频通话z6pro少年版正品官方旗舰店",
             "店铺名称": "小天才智能手表旗舰店", "商品主图链接": "https://gw.alicdn.com/imgextra/O1CN01mo2Dmx1E4XBCvkrRe_!!2217726390298-0-yinheaigc.jpg_580x580q90.jpg_.webp",
             "SKUID": "6152850371697", "SKU名称": "主播推荐 Z6 Pro 天境蓝",
             "SKU图片链接": "http://img.alicdn.com/imgextra/i3/2217726390298/O1CN01j4IQjG1E4X9BqEKWJ_!!2217726390298.jpg",
             "实际售价": "999.0", "原价": "2198.0", "活动价格": "",
             "销量": "4000+人收货", "采集时间": "2026-08-05", "数据来源": "api"},
            {"商品ID": "826399795851", "商品名称": "【重磅新品】小天才电话手表z7pro新款防水定位前后双摄4G全网通学生儿童视频通话z6pro少年版正品官方旗舰店",
             "店铺名称": "小天才智能手表旗舰店", "商品主图链接": "https://gw.alicdn.com/imgextra/O1CN01mo2Dmx1E4XBCvkrRe_!!2217726390298-0-yinheaigc.jpg_580x580q90.jpg_.webp",
             "SKUID": "6152850371698", "SKU名称": "主播推荐 Z6 Pro 星云粉",
             "SKU图片链接": "http://img.alicdn.com/imgextra/i2/2217726390298/O1CN01PMcWdE1E4X9BXFnHL_!!2217726390298.jpg",
             "实际售价": "999.0", "原价": "2198.0", "活动价格": "",
             "销量": "4000+人收货", "采集时间": "2026-08-05", "数据来源": "api"},
        ], ensure_ascii=False)

    sku_json = args

    # ── 解析输入 ──
    if isinstance(sku_json, str):
        rows = json.loads(sku_json)
    else:
        rows = sku_json

    if not rows:
        # 下架/异常商品静默跳过会传空数组进来：直接返回，不往表里写任何占位值
        # （旧版此处 set_cell(1,1,"NO_DATA") 会覆盖账本首格——2026-10-08 移除）
        return {"ok": True, "rows": 0}

    # ── 获取起始行号 ──
    try:
        r = int(glv['当前行'])
    except Exception:
        r = 1

    # ── 逐行写入 ──
    for row in rows:
        xbot.app.databook.set_cell(r, 1,  str(row.get("商品ID", "")))
        xbot.app.databook.set_cell(r, 2,  str(row.get("商品名称", "")))
        xbot.app.databook.set_cell(r, 3,  str(row.get("店铺名称", "")))
        xbot.app.databook.set_cell(r, 4,  str(row.get("商品主图链接", "")))
        xbot.app.databook.set_cell(r, 5,  str(row.get("SKUID", "")))
        xbot.app.databook.set_cell(r, 6,  str(row.get("SKU名称", "")))
        xbot.app.databook.set_cell(r, 7,  str(row.get("SKU图片链接", "")))
        xbot.app.databook.set_cell(r, 8,  str(row.get("实际售价", "")))
        xbot.app.databook.set_cell(r, 9,  str(row.get("原价", "")))
        xbot.app.databook.set_cell(r, 10, str(row.get("活动价格", "")))
        xbot.app.databook.set_cell(r, 11, str(row.get("销量", "")))
        xbot.app.databook.set_cell(r, 12, str(row.get("采集时间", "")))
        xbot.app.databook.set_cell(r, 13, str(row.get("数据来源", "")))
        glv['当前行'] = r + 1
        r += 1

    return {"ok": True, "rows": len(rows)}
