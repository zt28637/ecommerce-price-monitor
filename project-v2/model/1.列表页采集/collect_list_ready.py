from DrissionPage import ChromiumPage
from urllib.parse import quote
import os, socket, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
TOOL = os.path.normpath(os.path.join(HERE, "..", "tool"))
if os.path.isdir(TOOL) and TOOL not in sys.path:
    sys.path.insert(0, TOOL)

from ui_action import Ui, wait_stable
from risk_page import block_reason
from scroll_to_bottom import _card_ids
from filter_product import load_rules

PORT = 9223
DEFAULT_ADDR = "127.0.0.1:%d" % PORT

PRODUCT_CARD_XPATH = 'xpath:.//a[starts-with(@id,"item_id_")]'
SALE_TAB_XPATH = 'xpath:.//div[text()="销量"]'
RANGE_TAB_XPATH = 'xpath:.//div[text()="区间"]'
MIN_PRICE_INPUT_XPATH = 'xpath:.//input[contains(@placeholder,"最低价")]'
MAX_PRICE_INPUT_XPATH = 'xpath:.//input[contains(@placeholder,"最高价")]'

class BrowserDown(RuntimeError):
    """9223 上没有可用浏览器：必须由登录层先启动，本模块绝不自己拉起。"""


class ReadyFailed(RuntimeError):
    """进搜索页的准备阶段失败：被风控 / 未登录 / 空结果 / 筛选没做成。

    reason: 'not_login' | 'risk_page' | 'no_card' | 'prepare_failed' | 'filter_failed'
    detail: 证据串，如 'url:sec.taobao.com'、'text:请拖动滑块'
    """

    def __init__(self, reason, detail=""):
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail or reason


def _park_mouse(page):
    """把光标挪到页面角落：光标停在按钮上时，再次 hover 同一位置不一定触发弹层。"""
    try:
        page.actions.move_to((5, 5))
    except Exception:
        pass    # 挪不动就算了，不因为光标姿势把流程卡死


def _ensure_ok(page, stage):
    """被拦就抛 ReadyFailed；没被拦什么也不做。"""
    hit = block_reason(page)
    if hit:
        reason, evidence = hit
        raise ReadyFailed(reason, "%s：%s" % (stage, evidence))


def _port_open(port=PORT, timeout=1.0):
    """端口探活：先探再 attach，避免 DP 在端口关着时自起一个未登录的临时 profile。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def attach_page(addr=DEFAULT_ADDR, port=PORT):
    """只 attach 现有浏览器，与登录层 / 详情层同一套（127.0.0.1:9223）。"""
    if not _port_open(port):
        raise BrowserDown(
            "浏览器 %s 未启动：请先跑登录层（0.淘宝自动化登录）拉起 %d，再采集列表页"
            % (addr, port))
    try:
        return ChromiumPage(addr)
    except Exception as e:
        raise BrowserDown("连不上 %s：%s" % (addr, e))


def collect_list_ready(addr=DEFAULT_ADDR, port=PORT):
    page = attach_page(addr, port)
    ui = Ui(page)
    # 搜索词与价格区间都来自 targets.json，不在代码里写死
    cfg = load_rules()
    try:
        page.get("https://s.taobao.com/search?q=%s" % quote(cfg["keyword"]))
    except Exception as e:
        raise ReadyFailed(
            "prepare_failed", "打开搜索页失败：%s: %s" % (type(e).__name__, e))
    # 进页先判：登录墙 / 滑块 / 访问频繁，命中就给可读 reason，不在下面裸抛元素超时
    _ensure_ok(page, "进搜索页")
    try:
        page.ele(PRODUCT_CARD_XPATH, timeout=20)
    except Exception:
        # 没卡片有两种：被拦（上面漏判，如拦在 iframe 里）或真空结果；分清楚再报
        hit = block_reason(page)
        if hit:
            raise ReadyFailed(hit[0], "等待卡片时：%s" % hit[1])
        raise ReadyFailed(
            "no_card", "搜索页 20 秒内没有商品卡片（无结果，或页面结构已变）")
    # 每次点击前先查询
    try:
        ui.click(SALE_TAB_XPATH, timeout=20)
    except Exception as e:
        raise ReadyFailed(
            "prepare_failed", "切换销量排序失败：%s: %s" % (type(e).__name__, e))
    # 重渲染处理
    wait_stable(lambda: _card_ids(page), timeout=12)
    # 价格区间整段由 targets.json 决定：min/max 都是 0 就整段跳过
    # （白悬停、白点「确定」= 平白多暴露一次风控）
    lo = int(cfg["min_price"] or 0)
    hi = int(cfg["max_price"] or 0)
    if lo or hi:
        # 光标还停在「销量」上；先挪开再重新悬停，否则第二次 hover 不一定弹出价格面板
        _park_mouse(page)
        time.sleep(0.4)
        try:
            ui.hover(RANGE_TAB_XPATH, timeout=20)
        except Exception as e:
            raise ReadyFailed(
                "prepare_failed", "展开价格区间失败：%s: %s" % (type(e).__name__, e))
    # 弹窗元素捕获 —— 方法 A：F12 冻结页面后抄 XPath（悬浮弹窗首选）
    #   1. 页面按 F12，切到 Sources 面板
    #   2. 鼠标移到「区间」上让价格弹窗出现，保持鼠标不动
    #   3. 按 F8（或 Ctrl+\）暂停脚本，页面顶部出现 "Paused in debugger"
    #   4. 切到 Elements，Ctrl+F 搜“最低价 / 最高价”，右键节点 → Copy → Copy XPath / Copy selector
        # ============================================================
        # 条件生效判定：点「确定」前后对比卡片 ID 快照
        # ------------------------------------------------------------
        # 解决什么问题：
        #   筛选是**前端局部重渲染**（SPA，URL 不变），点击成功 ≠ 列表已经换完。
        #   所以点之前拍一张卡片 ID 快照，点之后轮询到「快照变了且稳定」为止。
        #
        # 不这样做会出三种问题，而且**三种都不会报错**：
        #
        #   1. 空窗期采到 0 张
        #      筛选时列表会先被清空。若此时直接进入滚动，页面变矮会被判成"已触底"，
        #      cards=0 连续两轮不变 → scroll_to_bottom 判底成功 → collect 拿到 0 张卡
        #      → 记 no_card 退出。而列表可能 6 秒后才渲染出来，这一页就白丢了。
        #
        #   2. 半渲染，静默少采（最危险）
        #      卡片是分批插入的。滚到一半卡片数稳定在 30 张，判底成功；
        #      parse 解析出 30 条，row_ids == cards 校验通过 → 落盘 30 条。
        #      注意：那个校验只保证"解析和 DOM 一致"，不保证"DOM 拿全了"，
        #      所以数据少了三分之一，流程全程绿灯，没人能发现。
        #
        #   3. 条件压根没生效
        #      弹窗没展开 / 「确定」没点到 / 输入被清空，脚本照样往下跑，采的是全量。
        #      本地 filter_item 会把超区间的行过滤掉，所以数据不会错，
        #      但白翻页、白暴露风控；15 秒超时是唯一能看见的信号。
        #
        # 判据为什么用快照而不是 URL：
        #   筛选走的是前端局部刷新，URL 不变（与切换排序同款，已确认），只能读 DOM。
        #
        # 两个实现细节：
        #   · 必须要求 now 非空 —— 重渲染有空窗期，只判"变了"会在列表清空那一刻就通过
        #   · 超时不判失败 —— 筛完商品可能恰好全在区间内（ID 集合不变），
        #     这种情况等多久都不会"变"，交给下一步抽卡验价兜底
        # ============================================================
        # 下限 → 上限 → 确定 是一条链，任何一环失败整体失败。
        # 不能像原来那样各段各 try：下限填失败被吞掉后，上限照样填、「确定」照样点，
        # 页面会正常返回一个"只有上限生效"的结果集 —— 日志全绿，数据却是区间外的。
        try:
            before = _card_ids(page)
            if lo:
                ui.fill(MIN_PRICE_INPUT_XPATH, str(lo))
            if hi:
                ui.fill(MAX_PRICE_INPUT_XPATH, str(hi))
            ui.click('xpath:.//div[text()="确定"]', timeout=20)
            after = wait_stable(lambda: _card_ids(page))
        except Exception as e:
            raise ReadyFailed(
                "filter_failed",
                "价格区间筛选未完成（min=%s max=%s）：%s: %s"
                % (lo, hi, type(e).__name__, e))
        changed = bool(after) and after != before
        print("筛选%s：%d → %d 张" % ("生效" if changed else "未见变化", len(before), len(after)))
    else:
        print("targets.json 未配置价格区间（min/max 均为 0），跳过价格筛选")
    # 筛选是最容易触发风控的动作；交付 page 前再确认一次没被拦
    _ensure_ok(page, "筛选后")
    return page


def main(args=None):
    """影刀 CodeFlow 入口占位：本模块是工具库。"""
    return {"ok": True}
