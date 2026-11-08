from lxml import etree
# 数据采集目标
#   ┌ #  字段              类型      定位（XPath，相对卡片）                       默认值    备注
#   │ 1  product_id        str       .//a[starts-with(@id,"item_id_")]            无      列表页去重依据
#   │ 2  title             str       .//div[contains(@class,"title")]/@title       ""        取 title 属性，不是 innerText
#   │ 3  price             float     .//div[contains(@class,"priceInt")]/text()   None
#   │ 4  sales             str       .//span[contains(@class,"realSales")]/text()  ""        保留原文，不把「1万」转 10000
#   │ 5  shop_name         str       .//span[contains(@class,"shopNameText")]/text() ""      店铺名
#   │ 6  prov_city         str       .//div[contains(@class,"procity")]/span/text() ""       " ".join 全部 span；直辖市只 1 个，不拆省/市
#   │ 7  main_image_url    str       .//img[contains(@class,"mainPic")]/@src        ""        带尺寸参数，随视口变，不稳定
#   │ 8  detail_url        str       卡片自身 @href                                ""        可能是 simba 跳转链，非规范直链
#   │ 9  platform          str       从 detail_url 推断（非 XPath）                "unknown" 只有 taobao / tmall / unknown
#   │ 10 is_promoted       int       从 detail_url 推断（非 XPath）                0         0/1；推广是「投放」维度，不是平台
#   └
def parse_list(html):
    """解析列表页 HTML，返回每个商品卡片的原始数据"""
    tree = etree.HTML(html)
    product_cards = tree.xpath('//a[starts-with(@id, "item_id_")]')

    product_list = []
    for card in product_cards:
        product_id = card.xpath('./@id')[0].replace("item_id_", "")
        product_title = card.xpath('.//div[contains(@class,"title")]/@title')
        # 价格由整数段 + 小数段拼接（45 + .1 → 45.1）；缺失时给 None
        price_text = "".join(
            card.xpath('.//div[contains(@class,"priceInt")]/text()')
            + card.xpath('.//div[contains(@class,"priceFloat")]/text()')
        ).strip()
        try:
            product_price = float(price_text) if price_text else None
        except ValueError:
            product_price = None
        sales = card.xpath('.//span[contains(@class,"realSales")]/text()')
        shop_name = card.xpath('.//span[contains(@class,"shopNameText")]/text()')
        prov_city = " ".join(card.xpath('.//div[contains(@class,"procity")]/span/text()'))
        main_image_url = card.xpath('.//img[contains(@class,"mainPic")]/@src')
        href = card.xpath("./@href")[0] if card.xpath("./@href") else ""
        platform = "tmall" if "detail.tmall.com" in href else (
              "taobao" if "item.taobao.com" in href else "unknown")
        is_promoted = 1 if (href and platform == "unknown") else 0
        detail_url = ("https://detail.tmall.com/item.htm?id=%s" % product_id
              if platform == "tmall" else
              "https://item.taobao.com/item.htm?id=%s" % product_id)
        product_list.append({
            "product_id": product_id,
            "title": product_title[0] if product_title else "",
            "price": product_price,
            "sales": sales[0] if sales else "",
            "shop_name": shop_name[0] if shop_name else "",
            "prov_city": prov_city,
            "main_image_url": main_image_url[0] if main_image_url else "",
            "detail_url": detail_url,
            "platform": platform,
            "is_promoted": is_promoted
        })
    return product_list


def main(args=None):
    """影刀 CodeFlow 入口占位：本模块是工具库。"""
    return {"ok": True}
