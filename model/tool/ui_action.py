# -*- coding: utf-8 -*-
# ============================================================
# ui_action.py —— 淘宝页面交互的两个小工具
# ------------------------------------------------------------
# 只解决一件事：**DrissionPage 的元素会"过期"**。
#
#   page.ele(X) 拿到的元素，内部记着一个 CDP 节点编号。
#   淘宝是前端局部刷新，DOM 一重建，这个编号就作废，
#   之后 .click() 会抛 ElementLostError（"元素对象已失效"）。
#
# 而人的操作不会遇到这个问题：人每次都是重新看一眼屏幕再点。
# 所以解决办法就是把"每步都重新看一眼"固化下来 —— 也就是本文件。
#
# 本文件只提供两样东西：
#
#   Ui          包住 page，提供 click / hover / fill
#               每次动作前重新查元素，失效就重查再做
#
#   wait_stable 反复读页面，连续两次读到一样的结果才算"稳定"
#               用来等排序/筛选后的列表重建完成
#
# 用法见文件末尾的示例。
# ============================================================

import time

from DrissionPage.errors import (
    ElementLostError, ContextLostError, ElementNotFoundError,
)

# 这两类异常的意思是"页面变了，手里的元素作废了"，可以重查重试
TRANSIENT = (ElementLostError, ContextLostError)


class UiGone(Exception):
    """找不到元素，或者元素被页面重渲染换掉了。"""


# ------------------------------------------------------------
# 一、Ui：每次动作前重新查元素
# ------------------------------------------------------------
class Ui:
    """包住 page，把"查元素 → 动作"绑在一起。不保存元素对象。

        ui = Ui(page)
        ui.click('xpath:.//div[text()="销量"]')
        ui.fill('xpath:.//input[contains(@placeholder,"最高价")]', "70")
    """

    def __init__(self, page, timeout=3, retries=1):
        self.page = page
        self.timeout = timeout      # 每次找元素的等待时间（秒）
        self.retries = retries      # 元素失效后重试几次

    def find(self, locator, timeout=None):
        """查一次元素；查不到抛 UiGone。"""
        element = self.page.ele(locator, timeout=timeout or self.timeout)
        # 注意：DP 找不到元素时返回的不是 None，而是一个"假元素"，
        # 一访问属性就抛 ElementNotFoundError，所以判断要用 if not element。
        if not element:
            raise UiGone("找不到元素：%s" % locator)
        return element

    def act(self, locator, do, timeout=None):
        """查一次 → 做一次；元素失效就重新查、再做一次。

        do 是一个接收元素的函数，例如：
            def do(element):
                element.click()
        """
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                return do(self.find(locator, timeout))
            except TRANSIENT + (UiGone, ElementNotFoundError) as e:
                last_error = e
                time.sleep(0.3)
        raise last_error

    def click(self, locator, timeout=None):
        def do(element):
            element.click()
        return self.act(locator, do, timeout)

    def hover(self, locator, timeout=None):
        def do(element):
            element.hover()
        return self.act(locator, do, timeout)

    def fill(self, locator, text, timeout=None):
        """点一下 → 清空 → 输入 → 回读确认。

        回读不相等也当失败重试 —— "输入没生效"和"元素被换掉"
        对调用方来说是一回事：都得重来。
        """
        text = str(text)

        def do(element):
            element.click()
            element.clear()
            element.input(text)
            if (element.value or "") != text:
                raise UiGone("填值未生效：期望 %r，实际 %r" % (text, element.value))

        return self.act(locator, do, timeout)


# ------------------------------------------------------------
# 二、wait_stable：等页面自己稳定下来
# ------------------------------------------------------------
def wait_stable(read, timeout=12, sample=0.5, need=2, require_nonempty=True):
    """反复调用 read() 采样，连续 need 次结果相同（且非空）→ 返回该结果。

    ⚠ read 必须是**函数**，不是数据：
        wait_stable(_card_ids)        ✅ 传函数本身，不加括号
        wait_stable(_card_ids())      ❌ 传的是一个写死的列表，
                                         内部没法再读第二次，会立刻判"稳定"

    为什么必须是函数：
      判断"稳不稳定"要隔一段时间读两次。传列表只能拿到某一瞬间的值，
      半秒后没有第二次可读，比较就失去意义。

    参数
      read             无参函数，调用一次返回当前状态（列表/集合/字符串）
      timeout          最多等几秒
      sample           每几秒读一次
      need             连续几次一样才算稳定（2 = 至少确认一次没再变）
      require_nonempty 空结果不算稳定 —— 切排序时列表会先清空再重建，
                       只看"变了"会在清空那一拍就通过

    返回
      稳定时的结果；超时则返回最后一次读到的东西（不算失败，
      因为筛选后内容可能本来就不变，是否报错交给调用方判断）。
    """
    start = time.time()
    previous = None
    same_count = 0

    while time.time() - start < timeout:
        time.sleep(sample)
        current = read()

        # 列表正在清空：不算稳定，继续等
        if require_nonempty and not current:
            previous, same_count = current, 0
            continue

        # 和上一次读到的一样 → 稳定计数 +1，否则清零重来
        if current == previous:
            same_count += 1
        else:
            same_count = 0

        if same_count >= need:
            return current

        previous = current

    return previous


# ------------------------------------------------------------
# 用法示例
# ------------------------------------------------------------
def main(args=None):
    """影刀 CodeFlow 入口占位：本模块是工具库，无独立流程。"""
    return {"ok": True}


if __name__ == "__main__":
    from DrissionPage import ChromiumPage

    page = ChromiumPage("127.0.0.1:9223")
    ui = Ui(page)

    def read_cards():
        """探针：读一次当前页面的卡片 id 列表。"""
        return page.run_js(
            'return Array.from(document.querySelectorAll(\'a[id^="item_id_"]\'))'
            '.map(function (e) { return e.id; });'
        ) or []

    ui.click('xpath:.//div[text()="销量"]')      # 点排序
    cards = wait_stable(read_cards)              # 等列表重建完成
    print("稳定后卡片数：", len(cards))
