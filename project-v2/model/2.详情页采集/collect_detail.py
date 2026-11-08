"""详情页采集编排：打开详情页 → 等待/滚动 → 取 HTML → 解析 → 落盘。

分工：
  · parse_detail.py      纯解析（HTML → 商品 + SKU）
  · detail_storage.py    落盘（ICE JSON / 异常 HTML / JSONL / 台账）
  · 本文件               只做编排、节流、登录态与异常分支

输入优先级：urls > product_ids > list_jsonl
  · urls        逗号分隔或 list，直接打开
  · product_ids 逗号分隔或 list，按 item.taobao.com 拼
  · list_jsonl  读列表采集产物，取 passed=True 的 detail_url

节流默认 60–120 秒（设计 §2.8 的 90s ± 30s）；快速测试传 interval_min=0, interval_max=0。
"""

import os
import sys

# 影刀 process.invoke_module 不会把模块目录放进 sys.path；补上才能导入同目录 CodeFlow
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _MODULE_DIR and _MODULE_DIR not in sys.path:
    sys.path.insert(0, _MODULE_DIR)

try:  # 允许脱离影刀离线运行
    import xbot
    from xbot import print, sleep
except ImportError:
    xbot = None
try:
    from . import package
    from .package import variables as glv
except ImportError:
    try:
        import package
        from package import variables as glv
    except ImportError:
        package = None
        glv = None

try:
    from . import detail_storage, parse_detail
except ImportError:  # 直接 python collect_detail.py 时
    import detail_storage
    import parse_detail

import json
import random
import time
from urllib.parse import parse_qs, urlparse

DEFAULT_ADDR = "127.0.0.1:9223"
DEFAULT_WAIT_TIMEOUT = 20
DEFAULT_WAIT_POLL = 0.5
DEFAULT_WAIT_JITTER_MIN = 1.0
DEFAULT_WAIT_JITTER_MAX = 2.5
DEFAULT_SCROLL_ROUNDS = 3
DEFAULT_INTERVAL_MIN = 60
DEFAULT_INTERVAL_MAX = 120
SAMPLE = r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\project-v2\runtime\samples\小天才电话手表详情1.html"


def _log(msg):
    if xbot is not None:
        try:
            xbot.app.logging.info(msg)
            return
        except Exception:
            pass
    print(msg)


def _as_list(v):
    if not v:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v).replace("\n", ",").split(",") if x.strip()]


def _detail_url(product_id, platform=None):
    pid = str(product_id)
    if str(platform or "").lower() == "tmall":
        return "https://detail.tmall.com/item.htm?id=%s" % pid
    return "https://item.taobao.com/item.htm?id=%s" % pid


def _check_login(page):
    """登录自检：URL 落 login = 被踢；tracknick 必须是非空值。"""
    url = getattr(page, "url", "") or ""
    if "login.taobao.com" in url:
        return False, "kicked"
    has_nick = page.run_js('return /(?:^|; )tracknick=[^;]+/.test(document.cookie);')
    if not has_nick:
        return False, "not_login"
    return True, "ok"


# ------------------------------------------------------------
# SKU 价格补全：复用页面自己的 mtop 接口（无点击 / 无 pisk）
#   快路径：已知 api + 最小 exParams（id + skuId）
#   动态兜底：快路径失败时，点一次 SKU 从网络里发现当前接口/参数模板
# ------------------------------------------------------------
PRICE_API_ALL = "mtop.taobao.pcdetail.data.get"
PRICE_API_HINT = "mtop.taobao.pcdetail.data.adjust"
PRICE_API_V = "1.0"
PRICE_API_TYPE = "GET"
PRICE_API_DATA_TYPE = "jsonp"
DETAIL_V = "3.3.2"


def _jsonp_to_dict(text):
    if isinstance(text, (dict, list)):
        return text
    s = str(text or "")
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(s[i:j + 1])
    except Exception:
        return None


def _click_sku(page):
    js = """
    var els=Array.from(document.querySelectorAll('[data-vid]')).filter(function(e){
      return e.getAttribute('data-disabled')!=='true';
    });
    if(!els.length) return 'NO_SKU';
    els[els.length>1?1:0].click();
    return 'clicked';
    """
    return page.run_js(js)


def _mtop_ready(page):
    return page.run_js(
        "return !!(window.lib && window.lib.mtop && (window.lib.mtop.request || window.lib.mtop));"
    )


def _minimal_price_data(item_id, sku_id):
    ex = {
        "id": str(item_id),
        "skuId": str(sku_id),
        "modules": "skuClick",
        "quantity": 1,
        "uniqueId": "%s_quantity1_%d" % (sku_id, int(time.time() * 1000)),
        "actionType": "skuClick",
        "hidePcOtherSkuPrice": True,
    }
    return {
        "id": str(item_id),
        "detail_v": DETAIL_V,
        "exParams": json.dumps(ex, separators=(",", ":"), ensure_ascii=False),
    }


def _mtop_price(page, api, v, type_, data_type, data, sku_id, timeout=10):
    js = """
    var d = %s; window.__sku_price_result = null;
    try {
      window.lib.mtop.request({api:%s, v:%s, type:%s, dataType:%s, data:d})
        .then(function(r){window.__sku_price_result={ok:true,r:r};})
        .catch(function(e){window.__sku_price_result={ok:false,e:String(e)};});
      return 'sent';
    } catch(e) { return 'ERR '+e; }
    """ % (json.dumps(data, ensure_ascii=False), json.dumps(api), json.dumps(v),
           json.dumps(type_), json.dumps(data_type))
    sent = page.run_js(js)
    if sent != "sent":
        return None, sent
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(0.3)
        raw = page.run_js(
            "return window.__sku_price_result ? JSON.stringify(window.__sku_price_result) : null")
        if not raw:
            continue
        r = json.loads(raw)
        if not r.get("ok"):
            return None, r.get("e")
        resp = r.get("r") or {}
        ret = resp.get("ret") or []
        if any(isinstance(x, str) and (x.startswith("FAIL") or x.startswith("RISK")) for x in ret):
            return None, "ret=%s" % ret
        s2i = (((resp.get("data") or {}).get("skuCore") or {}).get("sku2info") or {})
        info = s2i.get(str(sku_id)) or {}
        price = (info.get("price") or {}).get("priceText")
        if price:
            return price, None
        return None, "no_price"
    return None, "timeout"


def _mtop_all_prices(page, item_id, timeout=12):
    """一次拉全量 SKU 价：mtop.taobao.pcdetail.data.get。返回 {sku_id: priceText}。"""
    js = """
    var d = {id: %s}; window.__sku_all = null;
    try {
      window.lib.mtop.request({api: %s, v: '1.0', type: 'GET', dataType: 'jsonp', data: d})
        .then(function(r){window.__sku_all={ok:true,r:r};})
        .catch(function(e){window.__sku_all={ok:false,e:String(e)};});
      return 'sent';
    } catch(e) { return 'ERR '+e; }
    """ % (json.dumps(str(item_id)), json.dumps(PRICE_API_ALL))
    sent = page.run_js(js)
    if sent != "sent":
        return None, sent
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(0.3)
        raw = page.run_js("return window.__sku_all ? JSON.stringify(window.__sku_all) : null")
        if not raw:
            continue
        r = json.loads(raw)
        if not r.get("ok"):
            return None, r.get("e")
        resp = r.get("r") or {}
        ret = resp.get("ret") or []
        if any(isinstance(x, str) and (x.startswith("FAIL") or x.startswith("RISK")) for x in ret):
            return None, "ret=%s" % ret
        s2i = (((resp.get("data") or {}).get("skuCore") or {}).get("sku2info") or {})
        prices = {}
        for k, v in s2i.items():
            if not isinstance(v, dict):
                continue
            p = (v.get("price") or {}).get("priceText")
            if p:
                prices[str(k)] = p
        if prices:
            return prices, None
        return None, "no_price"
    return None, "timeout"


def _discover_price_api(page, timeout=10):
    """点一次 SKU，从页面自己的请求里发现价格接口与 data 模板。"""
    if not _mtop_ready(page):
        return None
    page.listen.start()
    try:
        time.sleep(0.3)
        if _click_sku(page) == "NO_SKU":
            return None
        end = time.time() + timeout
        while time.time() < end:
            try:
                p = page.listen.wait(count=1, timeout=0.5)
            except Exception:
                p = False
            if not p:
                continue
            url = p.url or ""
            if "mtop" not in url:
                continue
            q = parse_qs(urlparse(url).query)
            api = (q.get("api") or [None])[0]
            body = _jsonp_to_dict(p.response.body)
            if not api and isinstance(body, dict):
                api = body.get("api")
            if not api or not isinstance(body, dict):
                continue
            s2i = (((body.get("data") or {}).get("skuCore") or {}).get("sku2info") or {})
            if not any(isinstance(x, dict) and (x.get("price") or {}).get("priceText")
                       for x in s2i.values()):
                continue
            data_param = (q.get("data") or [None])[0]
            req_data = None
            if data_param:
                try:
                    req_data = json.loads(data_param)
                except Exception:
                    req_data = None
            if not req_data:
                pd = p.request.postData
                req_data = pd if isinstance(pd, dict) else None
            if not req_data:
                continue
            data_type = (q.get("dataType") or [None])[0]
            if not data_type:
                data_type = "jsonp" if (q.get("callback") or q.get("type") == ["jsonp"]) else "json"
            return {
                "api": api,
                "v": (q.get("v") or ["1.0"])[0],
                "type": (p.method or "GET").upper(),
                "dataType": data_type,
                "data": req_data,
            }
        return None
    finally:
        try:
            page.listen.stop()
        except Exception:
            pass


def collect_sku_prices(page, item_id, skus, max_calls=0, interval=(1.0, 3.0),
                       dynamic=True, call_budget=None, pause_every=0, pause_seconds=0,
                       retries=1, use_all_api=True):
    """补全 SKU 价。返回 (prices, meta)。

    主路径：data.get 一次全量；兜底：adjust 逐 SKU + 动态发现。
    call_budget：本次最多允许的 API 调用数；None=不限。
    pause_every / pause_seconds：每 N 次调用长休。
    meta: calls / errors / risk / budget_exhausted / api
    """
    if not skus:
        return {}, {"api": None, "calls": 0, "errors": [], "risk": False, "budget_exhausted": False}
    targets = skus[:max_calls] if max_calls and len(skus) > max_calls else skus
    if not targets:
        return {}, {"api": None, "calls": 0, "errors": [], "risk": False, "budget_exhausted": False}

    prices = {}
    calls = 0
    errors = []
    risk = False
    budget_exhausted = False
    retries_used = 0

    # 1) 一次拉全量（首选，1 请求/商品；可重试；连续失败可熔断）
    all_prices, all_err = None, None
    if use_all_api:
        for attempt in range(max(0, int(retries)) + 1):
            if call_budget is not None and calls >= call_budget:
                budget_exhausted = True
                break
            all_prices, all_err = _mtop_all_prices(page, item_id)
            calls += 1
            if attempt > 0:
                retries_used += 1
            if pause_every and calls % pause_every == 0:
                time.sleep(pause_seconds)
            if all_prices:
                break
            if all_err and ("RISK" in str(all_err) or "FAIL_SYS" in str(all_err)):
                risk = True
                break
            if attempt < retries:
                time.sleep(random.uniform(2, 5))
    else:
        all_err = "disabled"

    if budget_exhausted and not all_prices:
        return {}, {"api": None, "calls": calls, "errors": errors,
                    "risk": risk, "budget_exhausted": True, "retries": retries_used,
                    "data_get_ok": False, "all_err": all_err}
    if all_prices:
        for sku in targets:
            sid = str(sku.get("sku_id"))
            if all_prices.get(sid):
                prices[sid] = all_prices[sid]
        if len(prices) == len(targets):
            return prices, {"api": PRICE_API_ALL, "calls": calls, "errors": [],
                            "risk": risk, "budget_exhausted": False, "retries": retries_used,
                            "data_get_ok": True, "all_err": all_err}
    else:
        errors.append("data.get: %s" % all_err)

    # 2) 兜底：adjust 逐 SKU 补缺
    first = None
    for sku in targets:
        sid = str(sku.get("sku_id"))
        if sid not in prices:
            first = sid
            break
    if not first:
        return prices, {"api": PRICE_API_ALL, "calls": calls, "errors": errors,
                        "risk": risk, "budget_exhausted": False,
                        "data_get_ok": bool(all_prices), "all_err": all_err}

    if call_budget is not None and calls >= call_budget:
        return prices, {"api": PRICE_API_ALL, "calls": calls, "errors": errors,
                        "risk": risk, "budget_exhausted": True,
                        "data_get_ok": bool(all_prices), "all_err": all_err}

    template = None
    data = _minimal_price_data(item_id, first)
    price, err = _mtop_price(page, PRICE_API_HINT, PRICE_API_V, PRICE_API_TYPE,
                            PRICE_API_DATA_TYPE, data, first)
    calls += 1
    if pause_every and calls % pause_every == 0:
        time.sleep(pause_seconds)
    if err and ("RISK" in str(err) or "FAIL_SYS" in str(err)):
        risk = True
    if price:
        template = {"api": PRICE_API_HINT, "v": PRICE_API_V, "type": PRICE_API_TYPE,
                    "dataType": PRICE_API_DATA_TYPE, "data": data}
        prices[first] = price
    elif dynamic and not risk:
        template = _discover_price_api(page)
        calls += 1
        if not template:
            return prices, {"api": None, "calls": calls,
                            "errors": errors + [str(err), "discover_failed"],
                            "risk": risk, "budget_exhausted": budget_exhausted}
    else:
        return prices, {"api": PRICE_API_HINT, "calls": calls, "errors": errors + [str(err)],
                        "risk": risk, "budget_exhausted": budget_exhausted}

    for i, sku in enumerate(targets):
        sid = str(sku.get("sku_id"))
        if not sid or sid in prices:
            continue
        if call_budget is not None and calls >= call_budget:
            budget_exhausted = True
            break
        d = dict(template.get("data") or {})
        ex = d.get("exParams")
        if isinstance(ex, str):
            try:
                ex = json.loads(ex)
            except Exception:
                ex = None
        if not isinstance(ex, dict):
            ex = {}
        ex["id"] = str(item_id)
        ex["skuId"] = sid
        ex["modules"] = "skuClick"
        ex["actionType"] = "skuClick"
        ex["quantity"] = ex.get("quantity", 1)
        ex["uniqueId"] = "%s_quantity1_%d" % (sid, int(time.time() * 1000))
        ex["hidePcOtherSkuPrice"] = True
        d["id"] = str(item_id)
        if "detail_v" not in d:
            d["detail_v"] = DETAIL_V
        d["exParams"] = json.dumps(ex, separators=(",", ":"), ensure_ascii=False)
        price, err = _mtop_price(page, template["api"], template.get("v", "1.0"),
                                 template.get("type", "GET"),
                                 template.get("dataType", "jsonp"), d, sid)
        calls += 1
        if pause_every and calls % pause_every == 0:
            time.sleep(pause_seconds)
        if price:
            prices[sid] = price
        else:
            errors.append("%s: %s" % (sid, err))
            if err and ("RISK" in str(err) or "FAIL_SYS" in str(err)):
                risk = True
                break
        _log("[SKU价] %s -> %s%s" % (sid, price, (" err=%s" % err) if err else ""))
        if i < len(targets) - 1:
            time.sleep(random.uniform(interval[0], max(interval[0], interval[1])))
    return prices, {"api": template.get("api"), "calls": calls, "errors": errors,
                    "risk": risk, "budget_exhausted": budget_exhausted,
                    "retries": retries_used,
                    "data_get_ok": bool(all_prices), "all_err": all_err}


def _read_list_urls(path, limit=0):
    """从列表 JSONL 取 detail_url（只取 passed=True 或没有 passed 字段的行）。"""
    urls, seen = [], set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("passed") is False:
                continue
            # 用 product_id 重拼规范链，不用卡片原 href：
            #   · 推广位是 click/mclick.simba 跳转链，多一次重定向，且等于给竞品广告点一下
            #   · 普通位是协议相对 //item.taobao.com，脱离浏览器上下文就是坏链接
            #   · 原链带 skuId= 等跟踪参数，会让详情页预选某个 SKU，干扰 SKU 全量采集
            # product_id 与卡片链接内 id 实测 46/46 一致，重拼无损。
            pid = row.get("product_id")
            url = (_detail_url(pid, row.get("platform")) if pid
                   else row.get("detail_url"))
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
                if limit and len(urls) >= limit:
                    break
    return urls


def _flatten(result, crawl_date, crawl_ts, url=""):
    """商品 + SKU → 一行一个 SKU。"""
    base = {
        "crawl_date": crawl_date,
        "crawl_ts": crawl_ts,
        "product_id": result.get("product_id"),
        "title": result.get("title"),
        "shop": result.get("shop"),
        "item_price": result.get("item_price"),
        "item_price_raw": result.get("item_price_raw"),
        "price_desc": result.get("price_desc"),
        "item_price_scope": result.get("item_price_scope"),
        "hide_other_price": result.get("hide_other_price"),
        "price_coverage": result.get("price_coverage"),
        "price_complete": result.get("price_complete"),
        "flags": result.get("flags"),
        "retry_count": result.get("retry_count"),
        "url": url,
    }
    rows = []
    for sku in result.get("skus") or []:
        row = dict(base)
        row.update(sku)
        rows.append(row)
    return rows


def _retryable_reason(reason):
    """页面级可重试原因：渲染/ICE 缺失/打开超时。登录失效、风控、结构问题不重试。"""
    r = str(reason or "")
    return any(r.startswith(x) for x in ("ice_missing", "res_missing", "item_missing",
                                         "open_error", "timeout"))


RISK_URL_MARKERS = ("login.taobao.com", "sec.taobao.com", "_____tmd_____",
                    "punish", "x5sec", "captcha")
RISK_TEXT_MARKERS = ("请拖动滑块", "滑块验证", "安全验证", "人机验证", "访问受限",
                     "哎哟喂", "系统繁忙", "请稍后再试", "访问过于频繁", "Too Many Requests")
RISK_DOM_SELECTOR = ("#nc_1_n1z, .nc-container, #baxia-dialog, "
                     "[id*=captcha], iframe[src*=captcha]")


def _risk_reason(page):
    """风控页识别：URL / 可见文本 / 可见验证元素。命中返回原因，否则 None。"""
    url = (getattr(page, "url", "") or "").lower()
    for m in RISK_URL_MARKERS:
        if m in url:
            return "url:%s" % m
    try:
        text = page.run_js(
            "return document.body ? document.body.innerText.slice(0,5000) : ''") or ""
    except Exception:
        text = ""
    for m in RISK_TEXT_MARKERS:
        if m in text:
            return "text:%s" % m
    try:
        hit = page.run_js(
            "var e=document.querySelector(%s);"
            "if(!e) return false;"
            "var s=getComputedStyle(e);"
            "return e.offsetParent!==null && s.display!=='none' && s.visibility!=='hidden';"
            % json.dumps(RISK_DOM_SELECTOR))
    except Exception:
        hit = False
    if hit:
        return "dom:%s" % RISK_DOM_SELECTOR
    return None


def _api_state(root):
    """API 用量台账：{date, calls, risk_until}。按天重置 calls，保留冷却。"""
    today = time.strftime("%Y%m%d")
    path = os.path.join(root or detail_storage.DEFAULT_ROOT, "state", "api_usage.json")
    state = {"date": today, "calls": 0, "risk_until": 0, "page_risk_until": 0}
    try:
        with open(path, "r", encoding="utf-8") as f:
            s = json.load(f)
        if str(s.get("date")) == today:
            state["calls"] = int(s.get("calls") or 0)
        state["risk_until"] = float(s.get("risk_until") or 0)
        state["page_risk_until"] = float(s.get("page_risk_until") or 0)
    except Exception:
        pass
    return state, path


def _save_api_state(path, state):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        part = path + ".part"
        with open(part, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(part, path)
    except Exception as e:
        _log("[API台账] 写入失败：%s" % e)


def collect_one(page, url, product_id=None, wait_timeout=DEFAULT_WAIT_TIMEOUT,
                wait_poll=DEFAULT_WAIT_POLL, jitter=(DEFAULT_WAIT_JITTER_MIN, DEFAULT_WAIT_JITTER_MAX),
                scroll_rounds=DEFAULT_SCROLL_ROUNDS):
    """打开一个详情页并解析。返回 (html, result)。

    先打开再判登录；然后等 sku2info 出现（最多 wait_timeout 秒），
    再随机停留 jitter 秒；不再固定 sleep 8 秒。
    """
    page.get(url)
    try:
        page.wait.doc_loaded(timeout=20)
    except Exception:
        pass

    if "login.taobao.com" in (page.url or ""):
        return None, {"ok": False, "reason": "kicked", "product_id": product_id, "skus": [], "flags": []}
    ok, why = _check_login(page)
    if not ok:
        return None, {"ok": False, "reason": why, "product_id": product_id, "skus": [], "flags": []}

    risk = _risk_reason(page)
    if risk:
        return page.html, {"ok": False, "reason": "risk: %s" % risk, "risk": True,
                           "product_id": product_id, "skus": [], "flags": ["risk_page"]}

    # 等详情数据出现；慢页面/懒加载不再靠猜固定秒数
    waited = 0.0
    while waited < wait_timeout:
        try:
            ready = page.run_js(
                'return document.documentElement.innerHTML.indexOf(\'"sku2info"\') >= 0;')
        except Exception:
            ready = False
        if ready:
            break
        time.sleep(wait_poll)
        waited += wait_poll

    # 拟人停留：数据出现后再随机停 1–2.5s
    time.sleep(random.uniform(jitter[0], max(jitter[0], jitter[1])))

    for _ in range(max(0, int(scroll_rounds))):
        try:
            page.scroll.down(random.randint(400, 800))
        except Exception:
            pass
        time.sleep(random.uniform(0.5, 1.2))

    risk = _risk_reason(page)
    if risk:
        return page.html, {"ok": False, "reason": "risk: %s" % risk, "risk": True,
                           "product_id": product_id, "skus": [], "flags": ["risk_page"]}

    html = page.html
    result = parse_detail.parse_detail(html, product_id=product_id)
    return html, result


def main(args=None, **kwargs):
    """编排入口。返回本轮统计 dict。"""
    cfg = {}
    if isinstance(args, dict):
        cfg.update(args)
    cfg.update(kwargs)

    urls = _as_list(cfg.get("urls"))
    if not urls:
        pids = _as_list(cfg.get("product_ids"))
        urls = [_detail_url(p) for p in pids]
    if not urls and cfg.get("list_jsonl"):
        urls = _read_list_urls(cfg["list_jsonl"], int(cfg.get("limit") or 0))
    offset = int(cfg.get("offset") or 0)
    if offset:
        urls = urls[offset:]
    limit = int(cfg.get("limit") or 0)
    if limit:
        urls = urls[:limit]
    if not urls:
        return {"ok": False, "reason": "no_input", "requested": 0, "done": 0, "failed": 0}

    from DrissionPage import ChromiumPage  # 仅运行期需要

    interval_min = cfg.get("interval_min")
    interval_max = cfg.get("interval_max")
    interval_min = DEFAULT_INTERVAL_MIN if interval_min is None else float(interval_min)
    interval_max = DEFAULT_INTERVAL_MAX if interval_max is None else float(interval_max)
    wait_timeout = float(cfg.get("wait_timeout")
                         if cfg.get("wait_timeout") is not None else DEFAULT_WAIT_TIMEOUT)
    wait_poll = float(cfg.get("wait_poll")
                      if cfg.get("wait_poll") is not None else DEFAULT_WAIT_POLL)
    wait_jitter_min = float(cfg.get("wait_jitter_min")
                            if cfg.get("wait_jitter_min") is not None else DEFAULT_WAIT_JITTER_MIN)
    wait_jitter_max = float(cfg.get("wait_jitter_max")
                            if cfg.get("wait_jitter_max") is not None else DEFAULT_WAIT_JITTER_MAX)
    scroll_rounds = int(cfg.get("scroll_rounds") if cfg.get("scroll_rounds") is not None else DEFAULT_SCROLL_ROUNDS)
    fill_sku_prices = bool(cfg.get("fill_sku_prices") or False)
    max_sku_calls = int(cfg.get("max_sku_calls") or 0)
    sku_interval_min = float(
        cfg.get("sku_interval_min") if cfg.get("sku_interval_min") is not None else 1.0)
    sku_interval_max = float(
        cfg.get("sku_interval_max") if cfg.get("sku_interval_max") is not None else 3.0)
    max_api_run = int(cfg.get("max_api_calls_per_run")
                      if cfg.get("max_api_calls_per_run") is not None else 30)
    max_api_day = int(cfg.get("max_api_calls_per_day")
                      if cfg.get("max_api_calls_per_day") is not None else 90)
    api_pause_every = int(cfg.get("api_pause_every")
                          if cfg.get("api_pause_every") is not None else 10)
    api_pause_seconds = float(cfg.get("api_pause_seconds")
                              if cfg.get("api_pause_seconds") is not None else 60)
    risk_cooldown_min = float(cfg.get("risk_cooldown_min")
                              if cfg.get("risk_cooldown_min") is not None else 60)
    api_state, api_state_path = _api_state(cfg.get("root"))
    api_run_calls = 0
    api_skipped_budget = 0
    api_skipped_cooldown = 0
    api_risk = False
    retry_times = int(cfg.get("retry_times") if cfg.get("retry_times") is not None else 1)
    api_retry_times = int(cfg.get("api_retry_times") if cfg.get("api_retry_times") is not None else 1)
    api_retries = 0
    data_get_fail_limit = int(cfg.get("data_get_fail_limit")
                              if cfg.get("data_get_fail_limit") is not None else 3)
    batch_size = int(cfg.get("batch_size") if cfg.get("batch_size") is not None else 20)
    batch_pause_seconds = float(cfg.get("batch_pause_seconds")
                                if cfg.get("batch_pause_seconds") is not None else 120)
    use_data_get = True
    data_get_fail_streak = 0
    data_get_ok = data_get_fail = adjust_used = api_products = 0
    risk_hits = 0
    risk_detail = None

    page_risk_until = float(api_state.get("page_risk_until") or 0)
    if time.time() < page_risk_until:
        _log("[详情] 风控冷却中，跳过本轮（至 %s）"
             % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(page_risk_until)))
        return {"ok": False, "reason": "page_risk_cooldown",
                "page_risk_until": page_risk_until}

    page = ChromiumPage(cfg.get("addr", DEFAULT_ADDR))
    run = detail_storage.new_run(root=cfg.get("root"))
    crawl_date = time.strftime("%Y-%m-%d")
    done = failed = partial = rows_total = 0
    errors = []
    reason = "ok"

    for i, url in enumerate(urls, 1):
        _log("[详情] (%d/%d) %s" % (i, len(urls), url))
        page_retries = 0
        while True:
            try:
                html, result = collect_one(
                    page, url, wait_timeout=wait_timeout, wait_poll=wait_poll,
                    jitter=(wait_jitter_min, wait_jitter_max),
                    scroll_rounds=scroll_rounds)
            except Exception as e:
                html, result = None, {"ok": False, "reason": "open_error: %s" % e}
            if result.get("ok") or result.get("reason") in ("kicked", "not_login"):
                break
            if not _retryable_reason(result.get("reason")) or page_retries >= retry_times:
                break
            page_retries += 1
            _log("[详情] 重试 %d/%d：%s（%s）"
                 % (page_retries, retry_times, url, result.get("reason")))
            time.sleep(random.uniform(3, 6))
        result["retry_count"] = page_retries

        if result.get("risk"):
            reason = "risk"
            risk_hits += 1
            risk_detail = {"index": i, "url": url, "reason": result.get("reason")}
            detail_storage.save_html_gz("risk_%d" % i, html or "", run)
            api_state["page_risk_until"] = time.time() + risk_cooldown_min * 60
            _save_api_state(api_state_path, api_state)
            _log("[详情] 命中风控页（%s），立即停本轮，冷却 %.0f 分钟"
                 % (result.get("reason"), risk_cooldown_min))
            break

        if not result.get("ok"):
            if result.get("reason") in ("kicked", "not_login"):
                reason = result["reason"]
                failed += 1
                errors.append({"url": url, "reason": result["reason"], "retry": page_retries})
                _log("[详情] 第 %d 个登录态异常（%s），停止本轮" % (i, result["reason"]))
                break
            failed += 1
            if html is None:
                errors.append({"url": url, "reason": result.get("reason") or "open_error",
                               "retry": page_retries})
                _log("[详情] 打开失败：%s（重试 %d 次）" % (result.get("reason"), page_retries))
                continue
            path, _ = detail_storage.save_html_gz(result.get("product_id") or "unknown", html or "", run)
            errors.append({"url": url, "reason": result.get("reason") or "parse_failed",
                           "html": path, "retry": page_retries})
            _log("[详情] 解析失败：%s → %s" % (result.get("reason"), path))
            continue

        # 单个商品的处理整段兜底：补价/落盘/写 JSONL 任一环节抛错，
        # 都不能终结整轮（否则剩余商品不采、run_log 也不写）。
        try:
            # 部分价 / 0 价：data.get 一次补全；受预算/冷却/暂停约束
            if (fill_sku_prices or max_sku_calls) and result.get("sku_count") and not result.get("price_complete"):
                now = time.time()
                if api_risk or now < float(api_state.get("risk_until") or 0):
                    api_skipped_cooldown += 1
                    _log("[详情] API 冷却中，跳过补价：%s" % result["product_id"])
                elif api_run_calls >= max_api_run or int(api_state.get("calls") or 0) >= max_api_day:
                    api_skipped_budget += 1
                    _log("[详情] API 预算用尽（run=%d/%d day=%d/%d），跳过补价：%s"
                         % (api_run_calls, max_api_run, int(api_state.get("calls") or 0),
                            max_api_day, result["product_id"]))
                else:
                    remaining = min(max_api_run - api_run_calls,
                                    max_api_day - int(api_state.get("calls") or 0))
                    prices, api_meta = collect_sku_prices(
                        page, result["product_id"], result["skus"],
                        max_calls=max_sku_calls,
                        interval=(sku_interval_min, sku_interval_max),
                        call_budget=remaining,
                        pause_every=api_pause_every,
                        pause_seconds=api_pause_seconds,
                        retries=api_retry_times,
                        use_all_api=use_data_get,
                    )
                    used = int(api_meta.get("calls") or 0)
                    api_run_calls += used
                    api_retries += int(api_meta.get("retries") or 0)
                    api_state["calls"] = int(api_state.get("calls") or 0) + used
                    if api_meta.get("data_get_ok"):
                        data_get_ok += 1
                        data_get_fail_streak = 0
                    elif api_meta.get("all_err") and use_data_get:
                        data_get_fail += 1
                        data_get_fail_streak += 1
                        if data_get_fail_streak >= data_get_fail_limit:
                            use_data_get = False
                            _log("[详情] data.get 连续失败 %d 次，本轮切换 adjust" % data_get_fail_streak)
                    if api_meta.get("api") and not api_meta.get("data_get_ok"):
                        adjust_used += 1
                    if prices:
                        api_products += 1
                    if api_meta.get("risk"):
                        api_risk = True
                        api_state["risk_until"] = now + risk_cooldown_min * 60
                    _save_api_state(api_state_path, api_state)
                    if prices:
                        for s in result["skus"]:
                            p = prices.get(s["sku_id"])
                            if p:
                                try:
                                    s["price"] = float(p)
                                except (TypeError, ValueError):
                                    pass
                        priced = [s for s in result["skus"] if s["price"] is not None]
                        result["price_coverage"] = "%d/%d" % (len(priced), len(result["skus"]))
                        result["price_complete"] = len(priced) == len(result["skus"])
                        if "sku_price_api" not in result["flags"]:
                            result["flags"].append("sku_price_api")
                        if result["price_complete"]:
                            result["flags"] = [f for f in result["flags"] if f != "partial_sku_price"]
                    _log("[详情] SKU 价补全：api=%s calls=%d coverage=%s flags=%s"
                         % (api_meta.get("api"), used, result["price_coverage"], result["flags"]))

            # 正常：存 ICE JSON + 展开 SKU 写 JSONL
            try:
                ice = parse_detail.extract_ice(html)
                detail_storage.save_ice(result["product_id"], ice, run)
            except Exception as e:
                detail_storage.save_html_gz(result["product_id"], html, run)
                errors.append({"url": url, "reason": "ice_save_error: %s" % e})
                _log("[详情] ICE 落盘失败：%s" % e)

            rows = _flatten(result, crawl_date, run["ts"], url)
            rows_total = detail_storage.append_rows(rows, run)
            done += 1
            if "partial_sku_price" in (result.get("flags") or []):
                partial += 1

            # 设计 §2.4e 的异常触发：SKU 自检不过 / 价格全空
            if ("sku_count_mismatch" in result.get("flags", [])
                    or "masked_price" in result.get("flags", [])):
                detail_storage.save_html_gz(result["product_id"], html, run)

            _log("[详情] %s | %d SKU | 价格覆盖 %s | flags=%s"
                 % (result["product_id"], result["sku_count"], result["price_coverage"], result["flags"]))
        except Exception as e:
            failed += 1
            errors.append({"url": url, "reason": "item_error: %s" % e})
            _log("[详情] 商品处理异常，跳过：%s（%s）" % (url, e))
            continue

        if i < len(urls) and interval_max > 0:
            time.sleep(random.uniform(interval_min, max(interval_min, interval_max)))
        if batch_size and i % batch_size == 0 and i < len(urls):
            pause = batch_pause_seconds * random.uniform(0.8, 1.2)
            _log("[详情] 批次暂停 %.0fs（已处理 %d/%d）" % (pause, i, len(urls)))
            time.sleep(pause)

    meta = {
        "ok": reason == "ok" and failed == 0,
        "reason": reason,
        "requested": len(urls),
        "done": done,
        "failed": failed,
        "partial_sku_price": partial,
        "rows": rows_total,
        "jsonl": run["jsonl_path"],
        "api_calls": api_run_calls,
        "api_day_calls": int(api_state.get("calls") or 0),
        "api_skipped_budget": api_skipped_budget,
        "api_skipped_cooldown": api_skipped_cooldown,
        "api_risk": api_risk,
        "api_retries": api_retries,
        "api_products": api_products,
        "data_get_ok": data_get_ok,
        "data_get_fail": data_get_fail,
        "adjust_used": adjust_used,
        "use_data_get": use_data_get,
        "batches": ((len(urls) + batch_size - 1) // batch_size) if batch_size else 1,
        "risk_hits": risk_hits,
        "risk_detail": risk_detail,
        "page_risk_until": float(api_state.get("page_risk_until") or 0),
        "errors": errors,
    }
    detail_storage.save_run_log(run, meta)
    _log("[详情] 完成：%s" % meta)
    return meta


def _sample_mode(path):
    """离线：用本地 HTML 跑解析 + 落盘，不碰浏览器。"""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        html = f.read()
    result = parse_detail.parse_detail(html)
    run = detail_storage.new_run(root=os.path.join(detail_storage.DEFAULT_ROOT, "_sample"))
    if result.get("ok"):
        detail_storage.save_ice(result["product_id"], parse_detail.extract_ice(html), run)
        rows = _flatten(result, time.strftime("%Y-%m-%d"), run["ts"], path)
        detail_storage.append_rows(rows, run)
    meta = {
        "ok": result.get("ok"),
        "mode": "sample",
        "reason": result.get("reason"),
        "product_id": result.get("product_id"),
        "sku_count": result.get("sku_count"),
        "price_coverage": result.get("price_coverage"),
        "flags": result.get("flags"),
        "jsonl": run["jsonl_path"],
    }
    detail_storage.save_run_log(run, meta)
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    return meta


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] == "sample":
        _sample_mode(sys.argv[2] if len(sys.argv) > 2 else SAMPLE)
    else:
        arg = sys.argv[1] if len(sys.argv) > 1 else ""
        if arg.isdigit():
            print(json.dumps(main({"product_ids": [arg], "interval_min": 0, "interval_max": 0}),
                             ensure_ascii=False, indent=1))
        elif arg:
            print(json.dumps(main({"urls": [arg], "interval_min": 0, "interval_max": 0}),
                             ensure_ascii=False, indent=1))
        else:
            print(__doc__)
