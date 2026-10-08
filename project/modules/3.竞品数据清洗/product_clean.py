"""
============================================================
③ 统一数据清洗（合并版）
============================================================
作用：读步骤②导出的 13 列原始 Excel → 逐字段清洗 → 输出干净的 Excel

上游：步骤② 详情页补采 + SKU采集 → runtime/product_allraw/
下游：product_ingest.py + sku_ingest.py（入库）

输入（13列，有表头，第2行起为数据）：
  第 1 列 | 商品ID         | 只trim
  第 2 列 | 商品名称        | 去HTML/实体/括号
  第 3 列 | 店铺名称        | 只trim
  第 4 列 | 商品主图链接     | 补https协议头
  第 5 列 | SKUID          | 只trim
  第 6 列 | SKU名称         | 枚举提取标准化（型号_版本_颜色）
  第 7 列 | SKU主图链接      | 补https协议头
  第 8 列 | 实际售价        | 去¥/区间取最低/掩码价丢弃
  第 9 列 | 原价           | 同上
  第10列  | 活动价格        | 同上
  第11列  | 销量           | 只保留数字
  第12列  | 采集时间        | 只trim
  第13列  | 采集方式        | 只trim (api / web)

输出（13列，有表头）→ runtime/product_clean/

调用方式（影刀）：
  product_clean.main(excel路径, 关键词, 时间, 输出路径)
============================================================
"""

import json
import os
import re
import sys

import openpyxl

# ============================================================
# 路径工具
# ============================================================

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULES_DIR = os.path.dirname(_MODULE_DIR)
if _MODULES_DIR not in sys.path:
    sys.path.insert(0, _MODULES_DIR)


# ============================================================
# 小天才电话手表 — 已知 SKU 属性枚举
# ============================================================

# 型号（正则匹配，长型号排在前面避免误匹配）
_MODELS = [
    (re.compile(r"(?i)Z6\s*Pro"),     "Z6Pro"),
    (re.compile(r"(?i)Z5\s*Pro"),     "Z5Pro"),
    (re.compile(r"(?i)Z10"),          "Z10"),
    (re.compile(r"(?i)Z9"),           "Z9"),
    (re.compile(r"(?i)Z8"),           "Z8"),
    (re.compile(r"(?i)Z7"),           "Z7"),
    (re.compile(r"(?i)Z6(?!\s*Pro)"), "Z6"),
    (re.compile(r"(?i)Z5(?!\s*Pro)"), "Z5"),
    (re.compile(r"(?i)D4"),           "D4"),
    (re.compile(r"(?i)D3"),           "D3"),
    (re.compile(r"(?i)D2"),           "D2"),
    (re.compile(r"(?i)Q7"),           "Q7"),
    (re.compile(r"(?i)Q5"),           "Q5"),
    (re.compile(r"(?i)Q2"),           "Q2"),
]

# 版本同义词 → 标准名
_VERSION_MAP = {
    "少年版": "少年版", "少年款": "少年版",
    "旗舰版": "旗舰版", "旗舰款": "旗舰版",
    "标准版": "标准版", "标准款": "标准版",
    "青春版": "青春版",
    "儿童版": "儿童版",
}

# 颜色同义词 → 标准名
_COLOR_MAP = {
    "茶金白": "茶金白", "少年白": "茶金白",
    "陨石灰": "陨石灰", "少年灰": "陨石灰",
    "天境蓝": "天境蓝", "天镜蓝": "天境蓝",
    "星云粉": "星云粉", "粉色":   "星云粉",
    "幻影黑": "幻影黑",
    "极光蓝": "极光蓝",
    "蜜桃粉": "蜜桃粉",
    "薄荷绿": "薄荷绿",
    "珊瑚红": "珊瑚红",
}

# SKU 噪音关键词
_SKU_NOISE_KEYWORDS = [
    "碎屏险", "质保", "保修", "延保", "只换不修",
    "电话卡", "贴膜", "表带", "保护壳", "保护套",
    "赠品", "套餐", "晒单", "好评", "签收",
    "充电头", "充电线", "数据线", "钢化膜",
    "收纳包", "手提袋", "礼盒",
]

# 不需要清洗、只做 trim 的列索引
_TRIM_COLS = {0, 2, 4, 11, 12}


# ============================================================
# 商品级清洗函数（来自旧 product_clean.py）
# ============================================================

def clean_product_name(raw_value: str) -> str:
    """
    清洗「商品名称」
    处理：
      1. 去掉 HTML 标签和实体
      2. 去掉 【】[] () 括号及其中内容
      3. / 替换为 -
      4. 合并多余空白
    示例：
      "小天才Z6Pro【少年版】(赠贴膜)" → "小天才Z6Pro"
    """
    if not raw_value:
        return ""

    text = str(raw_value)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;|&lt;|&gt;|&amp;|&#?\w+;", "", text)
    text = re.sub(r"【[^】]*】", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"（[^）]*）", "", text)
    text = text.replace("/", "-")
    text = re.sub(r"[\n\r\t]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def clean_image_url(raw_value: str) -> str:
    """
    清洗「图片链接」（兜底）
    正常路径：影刀采集时已用正则洗过，此处仅兜底。
    处理：// 开头补 https: + 提取原图 URL
    """
    if not raw_value:
        return ""

    url = str(raw_value).strip()
    if url.startswith("//"):
        url = "https:" + url

    match = re.search(r"https?://.*?\.(?:jpg|png|jpeg|webp)", url)
    if match:
        return match.group(0)
    return url


def clean_sales(raw_value: str) -> str:
    """清洗「销量」— 只保留数字"""
    if not raw_value:
        return ""
    return re.sub(r"\D", "", str(raw_value))


# ============================================================
# SKU 级清洗函数（来自旧 sku_clean.py）
# ============================================================

def _extract_model(text: str) -> str:
    for pattern, standard_name in _MODELS:
        if pattern.search(text):
            return standard_name
    return ""


def _extract_version(text: str) -> str:
    for raw_name, standard_name in _VERSION_MAP.items():
        if raw_name in text:
            return standard_name
    return ""


def _extract_color(text: str) -> str:
    for raw_name, standard_name in _COLOR_MAP.items():
        if raw_name in text:
            return standard_name
    return ""


def clean_sku_name(sku_name: str, product_name: str = "") -> str:
    """
    清洗 SKU 名称 → 标准格式 "型号_版本_颜色"

    流程：按分隔符拆 → 去括号包装 → 去噪音片段 → 枚举提取 → 拼接
    例："茶金白;少年版" + 商品名"小天才Z6Pro" → "Z6Pro_少年版_茶金白"
    """
    if not sku_name:
        return ""

    parts = [p.strip() for p in re.split(r"[;|丨]", str(sku_name)) if p.strip()]

    noise_pattern = "|".join(_SKU_NOISE_KEYWORDS)
    cleaned_parts = []

    for part in parts:
        part = re.sub(r"^\s*【[^】]*】", "", part)
        part = re.sub(r"^\s*（[^）]*）", "", part)
        part = re.sub(r"^\s*\[[^\]]*\]", "", part)
        part = re.sub(r"【[^】]*】\s*$", "", part)
        part = re.sub(r"（[^）]*）\s*$", "", part)
        part = re.sub(r"\[[^\]]*\]\s*$", "", part)
        part = re.sub(rf"【[^】]*?(?:{noise_pattern})[^】]*】", "", part)
        part = re.sub(rf"（[^）]*?(?:{noise_pattern})[^）]*）", "", part)
        part = re.sub(rf"\[[^\]]*?(?:{noise_pattern})[^\]]*\]", "", part)
        part = re.sub(r"\+.*$", "", part)
        part = re.sub(r"送[^\s;|丨]+$", "", part)
        part = part.strip()
        if part:
            cleaned_parts.append(part)

    cleaned_parts = [p for p in cleaned_parts if p not in _SKU_NOISE_KEYWORDS]
    clean_text = " ".join(cleaned_parts)

    model = _extract_model(clean_text)
    if not model and product_name:
        model = _extract_model(str(product_name))

    version = _extract_version(clean_text)
    color = _extract_color(clean_text)

    result_parts = [p for p in (model, version, color) if p]
    if result_parts:
        return "_".join(result_parts)

    return clean_text if clean_text else str(sku_name).strip()


def clean_sku_image_url(raw: str) -> str:
    """清洗 SKU 图片链接 — 补协议头 + 提取完整图片 URL"""
    if not raw:
        return ""

    url = str(raw).strip()
    if url.startswith("//"):
        url = "https:" + url

    match = re.search(
        r"https?://[^\s\"'<>]+?\.(?:jpg|png|jpeg|webp|gif)",
        url, re.IGNORECASE
    )
    if match:
        return match.group(0)

    match = re.search(r"https?://[^\s\"'<>]+", url)
    return match.group(0) if match else url


def clean_price(raw: str) -> str:
    """
    清洗价格 — 只保留数字和小数点
    "¥79.9" → "79.9"  |  "128-168" → "128"（取最低）
    "?" → ""（掩码价丢弃）
    """
    if not raw:
        return ""

    text = str(raw).strip()
    if "?" in text:
        return ""

    text = text.replace("¥", "").replace("￥", "").replace("元", "")
    text = text.replace(",", "").replace("，", "").replace(" ", "").replace("\xa0", "")
    text = text.strip()

    # 区间价取最低
    if "-" in text or "~" in text or "—" in text:
        parts = re.split(r"[-~—]+", text)
        numbers = []
        for p in parts:
            m = re.search(r"[\d.]+", p.strip())
            if m:
                try:
                    numbers.append((float(m.group(0)), m.group(0)))
                except ValueError:
                    continue
        if numbers:
            return min(numbers, key=lambda x: x[0])[1]

    match = re.search(r"[\d.]+", text)
    if match:
        num_str = match.group(0).rstrip(".")
        try:
            float(num_str)
            return num_str
        except ValueError:
            return ""

    return ""


# ============================================================
# 13 列表头（与步骤②导出结构一致）
# ============================================================

_HEADERS = [
    "商品ID",        # 第 1 列
    "商品名称",       # 第 2 列 ← 清洗
    "店铺名称",       # 第 3 列
    "商品主图链接",    # 第 4 列 ← 清洗
    "SKUID",         # 第 5 列
    "SKU名称",       # 第 6 列 ← 清洗
    "SKU主图链接",    # 第 7 列 ← 清洗
    "实际售价",       # 第 8 列 ← 清洗
    "原价",          # 第 9 列 ← 清洗
    "活动价格",       # 第 10列 ← 清洗
    "销量",          # 第 11列 ← 清洗
    "采集时间",       # 第 12列
    "采集方式",       # 第 13列 (api / web)
]


# ============================================================
# 主流程
# ============================================================

def _safe_path(p):
    """修复影刀传参时被 Python 转义的路径"""
    if p is None:
        return None
    s = str(p)
    for i in range(1, 10):
        s = s.replace(chr(i), '\\' + str(i))
    s = s.replace('\r', '\\r')
    s = s.replace('\n', '\\n')
    s = s.replace('\f', '\\f')
    s = s.replace('\v', '\\v')
    return s


def clean_excel(filepath: str, keyword: str = "", timestamp: str = "",
                out_path=None, include_keywords=None) -> dict:
    """
    读步骤②导出的 13 列原始 Excel → 逐行清洗 → 输出

    参数:
        filepath         : 步骤②导出的原始 Excel（13列，有表头）
        keyword          : 搜索关键词（用于默认输出文件名）
        timestamp        : 采集时间（用于默认输出文件名）
        out_path         : 输出路径。不传则自动生成 runtime/product_clean/{关键词}_{时间}.xlsx
        include_keywords : SKU 名称过滤关键词列表，如 ["Z6Pro"]
                           清洗后 SKU 名称不含任意关键词 → 跳过该行
                           空/None → 不过滤

    返回:
        {"ok": True, "cleaned_path": "...", "rows": N, "skipped": N}
    """
    filepath = _safe_path(filepath)
    out_path = _safe_path(out_path)

    filepath = os.path.normpath(os.path.abspath(
        str(filepath).strip().strip("\"'")))

    wb_in = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws_in = wb_in.active

    wb_out = openpyxl.Workbook()
    ws_out = wb_out.active

    row_count = 0
    skipped = 0

    # 写表头
    ws_out.append(list(_HEADERS))

    # min_row=2：跳过第1行表头
    for row in ws_in.iter_rows(min_row=2, values_only=True):
        if not row or row[0] is None:
            continue

        values = list(row)
        while len(values) < len(_HEADERS):
            values.append("")

        # ---- 逐列清洗 ----
        cleaned = []
        for i, cell_value in enumerate(values):
            text = str(cell_value) if cell_value is not None else ""

            if i == 1:   # 商品名称
                text = clean_product_name(text)

            elif i == 3:  # 商品主图链接
                text = clean_image_url(text)

            elif i == 5:  # SKU名称
                product_name = str(values[1]) if len(values) > 1 and values[1] is not None else ""
                text = clean_sku_name(text, product_name)

            elif i == 6:  # SKU主图链接
                text = clean_sku_image_url(text)

            elif i in (7, 8, 9):  # 实际售价 / 原价 / 活动价格
                text = clean_price(text)

            elif i == 10:  # 销量
                text = clean_sales(text)

            elif i in _TRIM_COLS:
                text = text.strip()

            cleaned.append(text)

        # ---- 过滤：实际售价为空的行不入库 ----
        if not cleaned[7]:
            skipped += 1
            continue

        # ---- 过滤：SKU 名称不含关键词的跳过（用清洗前的原始值匹配）----
        if include_keywords:
            if isinstance(include_keywords, str):
                include_keywords = json.loads(include_keywords)
            if isinstance(include_keywords, list):
                kws = [str(k).strip().lower() for k in include_keywords if str(k).strip()]
                raw_sku = str(values[5] or "").lower()
                if kws and not any(kw in raw_sku for kw in kws):
                    skipped += 1
                    continue

        ws_out.append(cleaned)
        row_count += 1

    wb_in.close()

    # ---- 确定输出路径 ----
    if not out_path:
        if not keyword:
            basename = os.path.splitext(os.path.basename(filepath))[0]
            keyword = basename.split("_")[0] if "_" in basename else basename
        if not timestamp:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y年%m月%d日%H时%M分")

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        out_path = os.path.join(project_root, "runtime", "product_clean",
                                f"{keyword}_{timestamp}.xlsx")

    out_path = os.path.normpath(os.path.abspath(
        str(out_path).strip().strip("\"'")))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    wb_out.save(out_path)
    wb_out.close()

    return {"ok": True, "cleaned_path": out_path, "rows": row_count,
            "skipped": skipped}


def main(filepath: str, keyword: str = "", timestamp: str = "",
         out_path=None, include_keywords=None) -> dict:
    """
    影刀入口

    用法：
        filepath         = 步骤②导出的 product_allraw Excel 路径
        keyword          = glv['搜索关键词']
        timestamp        = glv['当前时间']
        out_path         = 清洗输出路径（可选）
        include_keywords = glv['包含关键词']（可选，如 ["Z6Pro"]）
    """
    return clean_excel(filepath, keyword=keyword, timestamp=timestamp,
                       out_path=out_path, include_keywords=include_keywords)


# ============================================================
# 本地调试
# ============================================================
if __name__ == "__main__":
    demo_input = r"../../runtime/product_allraw/demo.xlsx"
    result = clean_excel(demo_input, keyword="小天才Z6pro")
    print(json.dumps(result, ensure_ascii=False, indent=2))
