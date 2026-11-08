# -*- coding: utf-8 -*-
"""登录入口（影刀 CodeFlow）：判活 → 快速进入 → 人工兜底。

职责边界（2026-11-08 优化）：
  · 浏览器启动/复用归 login_browser.ensure（DP），本模块只 attach 判活。
  · 账密自动登录默认关闭（ALLOW_PASSWORD=False）；扫码 / 人工优先。
  · wait_manual() 负责人工等待：确保登录页 → 二维码截图 → 轮询 URL / 认证 cookie。

画布契约（login_gate / login_qr / main 均按此消费）：
    main() -> {
        "state":  "logged_in" | "cold_down",
        "method": "auto" | "quick_enter" | "password" | "manual" | "",
        "result": "ok" | "risk" | "structure_error" | "browser_down" |
                  "attach_failed" | "cred_missing" | "budget_blocked" |
                  "kicked_twice" | "manual_required" | "captcha" |
                  "slider" | "password_failed" | "timeout",
        "need_manual": bool,   # True 时画布调 login_qr 等待人工登录（密码/短信/扫码均可）
        "stop": bool,          # True 时 main 应终止本轮，不再往下跑
        "login_at": str,       # 真实登录成功时间（ISO），未登录为空
        "budget": {...},       # 预算判定明细，便于排查
        "detail": str,         # 人类可读的一句话
    }

登录预算（风控看频率不看方式）：
  · 每 24h 最多 1 次真实登录；快速进入 / 已登录不算。
  · 登录后 24h 内又失效 → 判为被踢：不自动重登，记冷却 + 告警；人工仍可兜底。
  · 同一天连续被踢 2 次 → 当天停跑（kicked_twice），人工也不再拉起。
  · 任何自动失败不重试；账密只是预算内的一次可选尝试。

凭据与台账都在仓库外（%USERPROFILE%\\.tb_rpa\\）：
  · taobao_cred.txt    可选：第 1 行账号，第 2 行密码；默认不启用（ALLOW_PASSWORD=False）
  · login_state.json   预算/冷却/被踢台账（覆盖写）
运行记录写 project-v2/runtime/run_log/login/<ts>.json（不写账号密码）。
"""

import datetime
import json
import os
import socket
import sys
import time

# ---- 路径：仓库版与影刀 CodeFlow 版共用同一份源码 ----
try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:                      # CodeFlow 内联执行时可能没有 __file__
    HERE = ""

HOME = os.path.expanduser("~")
TB_DIR = os.path.join(HOME, ".tb_rpa")
CRED_PATH = os.environ.get("TB_RPA_CRED") or os.path.join(TB_DIR, "taobao_cred.txt")
STATE_PATH = os.environ.get("TB_RPA_STATE") or os.path.join(TB_DIR, "login_state.json")

_PROJECT_CANDIDATES = [
    os.environ.get("TB_RPA_PROJECT_V2"),
    os.path.normpath(os.path.join(HERE, "..", "..")) if HERE else "",
    r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\project-v2",
]
_TOOL_CANDIDATES = [
    os.environ.get("TB_RPA_TOOLBOX"),
    os.path.normpath(os.path.join(HERE, "..", "tool")) if HERE else "",
    r"F:\Programs\RPA自动化\1-淘宝竞品价格监控自动化\project-v2\model\tool",
]


def _first_dir(candidates, required=None):
    """返回第一个存在的目录；required 指定必须存在的相对文件/目录，防止误命中。"""
    for p in candidates:
        if not p or not os.path.isdir(p):
            continue
        if required and not os.path.exists(os.path.join(p, required)):
            continue
        return p
    return ""


# 注意：影刀 CodeFlow 里 HERE=<app>/xbot_robot，HERE/../.. 会是 apps 目录；
# 用 model/ 和 feishu_notify.py 做标记，确保命中的是仓库 project-v2。
PROJECT_V2 = _first_dir(_PROJECT_CANDIDATES, required="model")
TOOLBOX = _first_dir(_TOOL_CANDIDATES, required="feishu_notify.py")
if TOOLBOX and TOOLBOX not in sys.path:
    sys.path.insert(0, TOOLBOX)

try:
    from DrissionPage import ChromiumPage
except ImportError:                    # 离线编译/单测不装 DP 也能导入
    ChromiumPage = None

# 影刀 process.invoke_module 不会把模块目录放进 sys.path；补上才能导入同目录 CodeFlow
if HERE and HERE not in sys.path:
    sys.path.insert(0, HERE)

import classify_login

PORT = 9223
HOME_URL = "https://www.taobao.com/"
LOGIN_URL = ("https://login.taobao.com/member/login.jhtml"
             "?redirectURL=https%3A%2F%2Fwww.taobao.com%2F")
LOGIN_HOSTS = ("login.taobao.com", "login.tmall.com")
SETTLE_TIMEOUT = 5                     # 判活前等页面/cookie 稳定，避免启动后误判未登录
SETTLE_POLL = 0.5

BUDGET_HOURS = 24
COOLDOWN_HOURS = 24
MAX_KICKS_PER_DAY = 2
QUICK_ENTER_WAIT = 10                  # 点快速进入后最多等 10s
PASSWORD_WAIT = 8                      # 提交账密后最多等 8s（淘宝跳转偶尔较慢）

# 登录层定位：扫码/人工优先；需要无人值守时再打开账密自动登录
ALLOW_PASSWORD = False
WAIT_TIMEOUT = 180                     # wait_manual 默认最多 3 分钟
WAIT_POLL = 2                          # 人工等待轮询间隔（秒）
QR_SELECTORS = ("#login-qrcode", ".qrcode-img", ".login-qrcode",
                "img[src*='qrcode']", "canvas.qrcode")
QR_DIR = os.path.join(PROJECT_V2, "runtime", "login") if PROJECT_V2 else ""


# ====================================================================== 时间/台账
def _now():
    return datetime.datetime.now()


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S") if dt else ""


def _parse(ts):
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(str(ts)[:19], fmt)
        except ValueError:
            continue
    return None


def _load_state():
    """读台账；坏文件按空台账处理，绝不因台账崩流程。"""
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_PATH)
    except OSError:
        pass


def _empty_state():
    return {
        "last_login_at": "",
        "last_login_method": "",
        "cooldown_until": "",
        "kick_count": 0,
        "kick_date": "",
        "last_seen_at": "",
        "last_state": "",
        "xlly_expire": "",
    }


def _write_run_log(res, budget, before, after):
    """运行记录：只放决策与状态，不放账号密码。"""
    try:
        if PROJECT_V2:
            out_dir = os.path.join(PROJECT_V2, "runtime", "run_log", "login")
        else:
            out_dir = os.path.join(TB_DIR, "run_log")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, _now().strftime("%Y%m%d-%H%M%S") + ".json")
        payload = {"at": _iso(_now()), "result": res, "budget": budget,
                   "state_before": before, "state_after": after}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
    except (OSError, TypeError):
        pass


# ====================================================================== 预算决策
def budget_decision(now, state, need_real_login=True):
    """纯函数：返回 {allow, reason, until, last_login_at, kick_count}。

    reason: already_logged_in / ok / cooldown / budget_24h / kicked_twice
    """
    state = state or {}
    last = _parse(state.get("last_login_at"))
    cool = _parse(state.get("cooldown_until"))
    kicks = int(state.get("kick_count") or 0)
    kick_date = state.get("kick_date") or ""
    today = now.strftime("%Y-%m-%d")

    if not need_real_login:
        return {"allow": True, "reason": "already_logged_in",
                "until": "", "last_login_at": state.get("last_login_at") or "",
                "kick_count": kicks}

    if kicks >= MAX_KICKS_PER_DAY and kick_date == today:
        return {"allow": False, "reason": "kicked_twice",
                "until": "", "last_login_at": state.get("last_login_at") or "",
                "kick_count": kicks}

    if cool and now < cool:
        return {"allow": False, "reason": "cooldown",
                "until": _iso(cool), "last_login_at": state.get("last_login_at") or "",
                "kick_count": kicks}

    if last and (now - last) < datetime.timedelta(hours=BUDGET_HOURS):
        # 24h 内登录过、现在却又未登录 = 早失效/被踢
        return {"allow": False, "reason": "budget_24h",
                "until": _iso(last + datetime.timedelta(hours=BUDGET_HOURS)),
                "last_login_at": _iso(last), "kick_count": kicks}

    return {"allow": True, "reason": "ok", "until": "",
            "last_login_at": _iso(last), "kick_count": kicks}


def record_kick(now, state):
    """记一次被踢：同日累加，跨日重置；并设 24h 冷却。"""
    state = state or {}
    today = now.strftime("%Y-%m-%d")
    if state.get("kick_date") != today:
        state["kick_date"] = today
        state["kick_count"] = 0
    state["kick_count"] = int(state.get("kick_count") or 0) + 1
    state["cooldown_until"] = _iso(now + datetime.timedelta(hours=COOLDOWN_HOURS))
    state["last_state"] = "kicked"
    return state


def record_login(now, state, method):
    """真实登录成功：写 last_login_at、清冷却。

    当日的被踢计数**不清零**——设计要的是“同一天连续 2 次被踢”，
    人工重登后再被踢也要能累计；跨日才重置。
    """
    state = state or _empty_state()
    today = now.strftime("%Y-%m-%d")
    if state.get("kick_date") != today:
        state["kick_count"] = 0
        state["kick_date"] = ""
    state["last_login_at"] = _iso(now)
    state["last_login_method"] = method
    state["cooldown_until"] = ""
    state["last_state"] = "logged_in"
    state["last_seen_at"] = _iso(now)
    return state


def decide_action(page_state, budget, has_cred):
    """纯函数：把页面状态 + 预算判定映射成动作。

    动作：already_logged_in / quick_enter / password / manual / cold_down
    """
    if page_state in ("auto",):
        return "already_logged_in"
    if page_state == "confirm":
        return "quick_enter"
    if page_state == "risk":
        return "cold_down"
    if page_state == "not_login":
        if not budget.get("allow"):
            return "manual"            # 预算拦截：不自动登，交给人工
        return "password" if has_cred else "manual"
    return "manual"                    # structure_error 等：人工兜底


# ====================================================================== 浏览器动作
def _port_open(port=PORT, timeout=1.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def _attach():
    """只 attach 现有 9223；端口没开就明确报 browser_down，绝不让 DP 自起临时 profile。"""
    if ChromiumPage is None:
        return None, "attach_failed"
    if not _port_open():
        return None, "browser_down"
    try:
        return ChromiumPage("127.0.0.1:%d" % PORT), ""
    except Exception:
        return None, "attach_failed"


def _on_login_page(url):
    return any(h in (url or "") for h in LOGIN_HOSTS)


def _wait_leave_login(page, seconds):
    """轮询 URL 离开登录域；返回最终 URL。"""
    end = time.time() + seconds
    url = page.url or ""
    while time.time() < end:
        if not _on_login_page(url):
            return url
        time.sleep(0.5)
        try:
            url = page.url or url
        except Exception:
            break
    return url


def _quick_enter(page):
    """点「快速进入」；返回 ok / not_found / failed。"""
    js = """
    return (function () {
      var btns = document.querySelectorAll('button.fm-button.fm-submit');
      for (var i = 0; i < btns.length; i++) {
        var b = btns[i];
        if (b.className.indexOf('password-login') >= 0) continue;
        if ((b.innerText || '').indexOf('快速进入') >= 0) {
          b.click(); return 'ok';
        }
      }
      var b2 = document.querySelector('button.fm-button.fm-submit:not(.password-login)');
      if (b2) { b2.click(); return 'ok'; }
      return 'not_found';
    })()
    """
    try:
        return page.run_js(js)
    except Exception:
        return "failed"


def _fill_and_submit(page, account, password):
    """JS 填值并提交；不依赖元素库。返回 ok/captcha/structure_error。"""
    args = json.dumps([account, password], ensure_ascii=False)
    js = """
    return (function (input) {
      var id = document.querySelector('#fm-login-id');
      var pw = document.querySelector('#fm-login-password');
      var btn = document.querySelector('button.fm-button.fm-submit.password-login');
      if (!id || !pw || !btn) return 'structure_error';
      if (id.offsetParent === null || btn.offsetParent === null) return 'structure_error';
      var cc = document.querySelector('#fm-login-checkcode');
      if (cc && cc.offsetParent !== null) return 'captcha';
      var set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      set.call(id, input[0]); id.dispatchEvent(new Event('input', {bubbles: true}));
      set.call(pw, input[1]); pw.dispatchEvent(new Event('input', {bubbles: true}));
      var cb = document.querySelector('#fm-agreement-checkbox');
      if (cb && !cb.checked) cb.click();
      btn.click();
      return 'ok';
    })(%s)
    """ % args
    try:
        return page.run_js(js)
    except Exception:
        return "structure_error"


def _failure_reason(page):
    """提交后仍没登录时，区分风控/验证码/滑块/密码错误。"""
    js = """
    return (function () {
      if (location.href.indexOf('sec.taobao.com') >= 0) return 'risk';
      var c = document.querySelector('#fm-login-checkcode');
      if (c && c.offsetParent !== null) return 'captcha';
      var s = document.querySelector('#nc_1_n1z, .nc-container, #baxia-dialog');
      if (s) return 'slider';
      return 'password_failed';
    })()
    """
    try:
        return page.run_js(js)
    except Exception:
        return "password_failed"


def _xlly_expire(page):
    """尽量读 xlly_s 到期时间；读不到返回空串。到期 ≠ 会话失效，只做预警。"""
    try:
        data = page.run_cdp("Network.getCookies", urls=["https://www.taobao.com/"])
        for c in (data or {}).get("cookies", []):
            if c.get("name") == "xlly_s" and c.get("expires", -1) > 0:
                return _iso(datetime.datetime.fromtimestamp(c["expires"]))
    except Exception:
        pass
    return ""


# ====================================================================== 告警/凭据
def _read_cred():
    """返回 (账号, 密码)；文件缺失/不足两行返回 None。"""
    try:
        with open(CRED_PATH, encoding="utf-8") as f:
            lines = [x.strip() for x in f.read().splitlines() if x.strip()]
    except OSError:
        return None
    return (lines[0], lines[1]) if len(lines) >= 2 else None


def _send_via(module_name, text, title):
    mod = __import__(module_name)
    return mod.send_text(text, title=title)


def alert(text, title="登录告警"):
    """公开告警入口：飞书优先，钉钉回退；都没配置时返回 skipped，不抛错。"""
    last = {"status": "skipped", "error": "未配置通知渠道"}
    for name in ("feishu_notify", "dingtalk_notify"):
        try:
            res = _send_via(name, text, title)
            if isinstance(res, dict) and res.get("status") != "skipped":
                return res
            last = res if isinstance(res, dict) else last
        except Exception as e:
            last = {"status": "error", "error": "%s: %s" % (type(e).__name__, e)}
    return last


# ====================================================================== 结果/编排
def _result(state, method, result, need_manual=False, stop=False,
            login_at="", budget=None, detail=""):
    return {
        "state": state,
        "method": method or "",
        "result": result,
        "need_manual": bool(need_manual),
        "need_qr": bool(need_manual),      # 兼容旧画布字段名
        "stop": bool(stop),
        "login_at": login_at or "",
        "budget": budget or {},
        "detail": detail or "",
    }


def mark_login(method="manual"):
    """画布在人工登录成功后调用：写真实登录台账。"""
    now = _now()
    state = record_login(now, _load_state(), method)
    _save_state(state)
    return {"ok": True, "last_login_at": state["last_login_at"], "method": method}


def _attempt_quick_enter(page, st, budget):
    """确认面板 → 点快速进入 → 等 URL 离开 login。"""
    clicked = _quick_enter(page)
    if clicked == "ok":
        url = _wait_leave_login(page, QUICK_ENTER_WAIT)
        if not _on_login_page(url) and classify_login._nick_ok(page):
            return _result("logged_in", "quick_enter", "ok", budget=budget,
                           detail="快速进入成功")
    st["last_seen_at"] = _iso(_now())
    st["last_state"] = "confirm_but_stuck"
    _save_state(st)
    return _result("cold_down", "quick_enter", "manual_required",
                   need_manual=True, budget=budget,
                   detail="确认面板存在但快速进入失败，转人工")


def _attempt_password(page, st, budget, cred):
    """预算内一次账密尝试；失败按 captcha/slider/risk 分流。"""
    # 页面不在登录域时先导航到登录页。login_open 只在缺浏览器时打开登录页，
    # 已登录复用不再强制导航，避免每次跑 main 都刷新首页。
    if not _on_login_page(page.url or ""):
        try:
            page.get(LOGIN_URL)
            time.sleep(2)
        except Exception:
            pass
    fill = _fill_and_submit(page, cred[0], cred[1])
    if fill != "ok":
        if fill == "structure_error":
            alert("登录告警 | 结果=structure_error | 方式=password")
        return _result("cold_down", "password", fill,
                       need_manual=fill in ("captcha", "structure_error"),
                       budget=budget,
                       detail="账密表单不可用或出现验证码，转人工")
    url = _wait_leave_login(page, PASSWORD_WAIT)
    page_state = "not_login"
    try:
        page_state = classify_login.classify_login(page, url)
    except Exception:
        pass

    if page_state in ("auto", "confirm"):
        if page_state == "confirm":
            _quick_enter(page)
            _wait_leave_login(page, QUICK_ENTER_WAIT)
        now = _now()
        new_state = record_login(now, st, "password")
        new_state["xlly_expire"] = _xlly_expire(page)
        _save_state(new_state)
        return _result("logged_in", "password", "ok", login_at=_iso(now),
                       budget=budget, detail="账密登录成功")

    reason = _failure_reason(page)
    if reason == "risk":
        alert("登录告警 | 结果=risk | 方式=password")
        return _result("cold_down", "password", "risk", budget=budget,
                       detail="账密提交后进入风控页")
    return _result("cold_down", "password", reason,
                   need_manual=reason in ("captcha", "slider", "password_failed"),
                   budget=budget, detail="账密失败，转人工")


def _settle_page(page, timeout=None):
    """等页面离开 about:blank 且认证 cookie 落盘；返回最新 URL。"""
    timeout = SETTLE_TIMEOUT if timeout is None else timeout
    end = time.time() + timeout
    url = ""
    while time.time() < end:
        try:
            url = page.url or url
        except Exception:
            pass
        if url and "about:blank" not in url:
            try:
                if classify_login.auth_ok(page):
                    return url
            except Exception:
                pass
        time.sleep(SETTLE_POLL)
    try:
        return page.url or url
    except Exception:
        return url


def _main():
    now = _now()
    st = _load_state()
    st["last_seen_at"] = _iso(now)

    page, err = _attach()
    if page is None:
        alert("登录告警 | 结果=%s" % err)
        st["last_state"] = err
        _save_state(st)
        return _result("cold_down", "", err, stop=True,
                       detail="浏览器 9223 不可用：%s" % err)

    try:
        url = _settle_page(page)
        page_state = classify_login.classify_login(page, url)
    except Exception:
        page_state = "structure_error"

    # 会话有效但页面停在登录页（旧标签/跳转中）：按已登录处理，不误转人工
    if page_state == "not_login":
        try:
            if classify_login.auth_ok(page):
                page_state = "auto"
        except Exception:
            pass

    xlly = _xlly_expire(page)
    if xlly:
        st["xlly_expire"] = xlly

    # 已登录：不消耗预算
    if page_state == "auto":
        st["last_state"] = "logged_in"
        _save_state(st)
        return _result("logged_in", "auto", "ok", budget=budget_decision(
            now, st, need_real_login=False), detail="会话有效（自动判活）")

    if page_state == "confirm":
        res = _attempt_quick_enter(page, st, budget_decision(now, st, False))
        if res["state"] == "logged_in":
            st["last_state"] = "logged_in"
            _save_state(st)
        return res

    if page_state == "risk":
        alert("登录告警 | 结果=risk")
        st["last_state"] = "risk"
        _save_state(st)
        return _result("cold_down", "", "risk", stop=True, detail="当前已在风控页")

    # 页面结构不认识：不消耗预算、不记被踢，直接人工
    if page_state == "structure_error":
        st["last_state"] = "manual_required"
        _save_state(st)
        return _result("cold_down", "", "structure_error", need_manual=True,
                       budget=budget_decision(now, st, False),
                       detail="登录页结构异常，转人工")

    # 需要真实登录：先算预算
    cred = _read_cred()
    budget = budget_decision(now, st, need_real_login=True)

    if budget.get("reason") == "budget_24h":
        # 早失效/被踢：记一次 + 冷却 + 告警；仍允许人工兜底
        st = record_kick(now, st)
        _save_state(st)
        budget = budget_decision(now, st, need_real_login=True)
        alert("登录告警 | 结果=budget_24h | 24h 内已登录过又失效，"
              "已记冷却至 %s，自动登录不再尝试" % st.get("cooldown_until", ""))
        return _result("cold_down", "", "budget_blocked", need_manual=True,
                       budget=budget, detail="24h 内重复登录，已冷却，转人工")

    if budget.get("reason") == "kicked_twice":
        st["last_state"] = "kicked_twice"
        _save_state(st)
        alert("登录告警 | 结果=kicked_twice | 今日连续被踢 2 次，当天停跑")
        return _result("cold_down", "", "kicked_twice", stop=True,
                       budget=budget, detail="今日连续被踢 2 次，停跑")

    action = decide_action(page_state, budget, bool(cred))
    if action == "password" and ALLOW_PASSWORD and cred:
        return _attempt_password(page, st, budget, cred)

    if action == "cold_down":
        st["last_state"] = "risk"
        _save_state(st)
        return _result("cold_down", "", "risk", stop=True, budget=budget,
                       detail="风控页")

    # manual：页面结构异常/无凭据/冷却中，统一交人工
    st["last_state"] = "manual_required"
    _save_state(st)
    reason = "cred_missing" if not cred else "manual_required"
    return _result("cold_down", "", reason, need_manual=True, budget=budget,
                   detail="转人工登录（密码/短信/扫码均可）")


# ====================================================================== 人工登录（DP）
def _find_qr(page):
    """在主页面与各 iframe 里找二维码元素；找不到返回 None。"""
    for sel in QR_SELECTORS:
        try:
            ele = page.ele(sel, timeout=1)
        except Exception:
            ele = None
        if ele:
            return ele
    try:
        for frame in page.get_frames():
            for sel in QR_SELECTORS:
                try:
                    ele = frame.ele(sel, timeout=0.5)
                except Exception:
                    ele = None
                if ele:
                    return ele
    except Exception:
        pass
    return None


def _capture_qr(page):
    """二维码截图到 runtime/login/qr_<ts>.png；找不到元素时退回整页截图。"""
    if not QR_DIR:
        return ""
    try:
        os.makedirs(QR_DIR, exist_ok=True)
        path = os.path.join(QR_DIR, "qr_%s.png" % _now().strftime("%Y%m%d-%H%M%S"))
        ele = _find_qr(page)
        if ele is not None:
            try:
                ele.get_screenshot(path=path)
                return path
            except Exception:
                pass
        page.get_screenshot(path=path)
        return path
    except Exception:
        return ""


def wait_manual(timeout=WAIT_TIMEOUT):
    """人工登录等待（DP）：确保登录页 → 截二维码 → 轮询离开登录域。

    返回与 main() 同结构的 dict；成功时写真实登录台账并返回 logged_in/manual。
    超时 / 风控 / 浏览器不可用均返回 cold_down，由画布决定告警与终止。
    """
    st = _load_state()
    st["last_seen_at"] = _iso(_now())

    page, err = _attach()
    if page is None:
        st["last_state"] = err or "browser_down"
        _save_state(st)
        res = _result("cold_down", "", err or "browser_down", stop=True,
                      detail="浏览器 9223 不可用：%s" % err)
        _write_run_log(res, {}, st, st)
        return res

    # 入口就已登录：按复用返回，不写 last_login_at（不算真实登录）
    try:
        if classify_login.auth_ok(page):
            if _on_login_page(page.url or ""):
                try:
                    page.get(HOME_URL)
                    time.sleep(1)
                except Exception:
                    pass
            st["last_state"] = "logged_in"
            _save_state(st)
            res = _result("logged_in", "auto", "ok",
                          detail="会话有效（人工等待前已登录）")
            _write_run_log(res, {}, st, st)
            return res
    except Exception:
        pass

    url = page.url or ""
    if not _on_login_page(url):
        try:
            page.get(LOGIN_URL)
            time.sleep(2)
            url = page.url or ""
        except Exception:
            pass

    qr_path = _capture_qr(page)
    try:
        import xbot
        xbot.app.logging.info(
            "login_entry: 请在浏览器完成登录（密码 / 短信 / 扫码均可），"
            "最多等 %d 秒；二维码=%s" % (timeout, qr_path or "未找到"))
    except Exception:
        pass

    end = time.time() + timeout
    while time.time() < end:
        time.sleep(WAIT_POLL)
        try:
            url = page.url or url
        except Exception:
            continue
        if "sec.taobao.com" in url:
            st["last_state"] = "risk"
            _save_state(st)
            res = _result("cold_down", "", "risk", stop=True, detail="登录后跳风控页")
            _write_run_log(res, {}, st, st)
            alert("登录告警 | 结果=risk | 方式=manual")
            return res
        if not _on_login_page(url) and classify_login.auth_ok(page):
            now = _now()
            st = record_login(now, st, "manual")
            st["xlly_expire"] = _xlly_expire(page)
            _save_state(st)
            res = _result("logged_in", "manual", "ok", login_at=_iso(now),
                          detail="人工登录成功")
            _write_run_log(res, {}, st, st)
            return res

    st["last_state"] = "manual_timeout"
    _save_state(st)
    res = _result("cold_down", "", "timeout", stop=True, detail="人工登录超时")
    _write_run_log(res, {}, st, st)
    alert("登录告警 | 结果=timeout | 方式=manual")
    return res


def _log_result(res):
    try:
        import xbot
        xbot.app.logging.info("login_entry: %s" % (res,))
    except Exception:
        pass


def main(args=None):
    before = _load_state()
    try:
        res = _main()
    except Exception as e:                      # 兜底：绝不让登录层裸抛
        res = _result("cold_down", "", "structure_error", stop=True,
                      detail="%s: %s" % (type(e).__name__, e))
    after = _load_state()
    _log_result(res)
    _write_run_log(res, res.get("budget") or {}, before, after)
    return res


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
