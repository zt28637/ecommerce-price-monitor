# ⑥ 竞品数据看板 — 原理、依据与踩坑（Metabase）

> **作用**：MySQL 三表 → 4 个视图 → 10 个问题（图）→ 1 个看板，供人工探索与对外演示
> **形态**：Metabase 单文件 jar，原生 Java 进程。**不用 Docker**，本机也没装 Docker
> **数据源**：`price_monitor`，BI 侧只读
> **实测环境**：Windows 11 ｜ MySQL 8.0.30 ｜ Metabase v0.63.18.2 ｜ Corretto JDK 21.0.12.1 ｜ 搭建日期 2026-09-25
>
> **本篇只讲"为什么"和"哪里会炸"**。动手执行请走两份 SOP：
> · 从零搭建（含 10 张图 SQL、验收）→ [6-0看板搭建.md](6-0看板搭建.md)
> · 日常启停 / 排障 / 备份 / 回滚 → [6-1日常运维.md](6-1日常运维.md)

---

## 1. 先建立三条认知（不然后面全糊）

**① Metabase 不存你的业务数据。** 它是"会画图的网页版 SQL 客户端"。你每刷新一次看板，它就去 MySQL 现跑一次 SQL 重新画。图不是截图、不是文件、不是缓存副本。所以**采集数据一旦入库，看板自动就有，不需要"同步到 BI"**。

**② 看板上的每一张图 = 一段存在 Metabase 配置里的 SQL（内部叫"问题 / Question"）。** 点开任意图的标题就能看到那段 SQL，改了立刻生效。BI 工具的全部魔力也就到此为止，没有黑盒。建图全部走**原生查询**而非拖拽：视图已把逻辑收敛好，写 SQL 比拖拽直白，也方便 review 数字来源。

**③ 业务数据和 BI 配置是两个不同的数据库，物理隔开。** 这是最容易搞混的地方：

| 东西 | 存在哪 | 谁能改 | 删了会怎样 |
|------|--------|--------|-----------|
| **业务数据**（商品/SKU/价格） | MySQL `price_monitor` | 你的 ①②③④ 采集入库流程 | 与 Metabase 无关 |
| **4 个视图**（`v_*`） | 也在 MySQL `price_monitor` 里，但**不占空间**，只是"存好的查询" | [init_bi_views.sql](../../config/init_bi_views.sql) | 图全报错，业务数据一根毛没动 |
| **BI 配置**（管理员、数据源连接、10 段 SQL、图的摆放位置、颜色） | `F:\Programs\metabase\metabase.db\`（H2 文件，Metabase 自己的库） | Metabase 界面 | 看板全没，业务数据完好 |
| **程序本体** | `F:\Programs\metabase\metabase.jar`（633MB） | 手动升级 | 网页打不开，上面两行都还在 |

一句话：**「看板」这个东西 = 第三行那份配置**。第一、二行本来就在。这也是为什么卸载回滚零风险（6-1 §E）：BI 是纯只读旁挂。

---

## 2. 整体架构

```
   MySQL: price_monitor                    Metabase (java -jar)              浏览器
┌──────────────────────────┐          ┌──────────────────────────┐    ┌──────────────┐
│ 原始三表（采集流程写入）  │          │  配置库 metabase.db       │    │              │
│  competitor_product  63  │          │   ├ 管理员账号             │    │              │
│  competitor_sku     232  │◀─只读查询─┤   ├ 数据源连接(指向我库)   │───▶│ localhost   │
│  price_history      819  │          │   └ 10 个"问题"= 10 段SQL │    │ :3000       │
│         │                │          └──────────────────────────┘    │  = 看板      │
│         ▼                │                    ▲                     │  10 张图     │
│  视图 4 个（本模块建）    │────────────────────┘                     └──────────────┘
│  v_price_daily      252  │   ← 去重后的日快照，图一律查这里
│  v_price_change           │   ← 带环比、历史最低
│  v_sku_latest             │   ← SKU 三档价 + 折扣率
│  v_shop_summary           │   ← 店铺汇总
└──────────────────────────┘
```

**当前实例状态**：数据源 `db_id = 2`（`db_id=1` 是 Metabase 自带 Sample Database，SQLite 演示库，可删不影响本项目）。

---

## 3. 视图层：本模块唯一的"技术含量"

### 3.1 不建视图会怎样：一个会让数字静默出错的真问题

`price_history` 是 **append-only** 设计的 —— [sku_ingest.py](../4.竞品数据汇总/sku_ingest.py) 每跑一次采集就往里**追加一批**，不覆盖。一天手动跑 4 次，同一条价格就有 4 行。

2026-09-25 实测：

| 指标 | 实测值 |
|------|--------|
| `price_history` 总行数 | **819** |
| 不同的 `(product_id, sku_name, crawl_date)` 组合 | **252** |
| 同一组合最多重复次数 | **32** |
| 每天实际有几次采集时间戳 | 07-25 有 **4** 次，08-05 有 **3** 次 |

所以如果直接拿 `price_history` 画"每日均价"，**跑得多的那天会被当成样本量大、均价被重复值拉扯，图上点位数虚高 3 倍，但看起来一切正常**。这是 BI 最危险的一类错：不是报错，是静默出假数。

### 3.2 解决办法：`v_price_daily` 一天只留最后一次

```sql
CREATE OR REPLACE VIEW v_price_daily AS
SELECT product_id, product_name, shop_name, sku_name, sku_id,
       crawl_date, crawl_time, price, sales
FROM (
    SELECT h.product_id, p.product_name, p.shop_name, h.sku_name, h.sku_id,
           h.crawl_date, h.crawl_time, h.price, p.sales,
           ROW_NUMBER() OVER (
               PARTITION BY h.product_id, h.sku_name, h.crawl_date   -- 分组：某商品某SKU某天
               ORDER BY h.crawl_time DESC, h.id DESC                 -- 排序：时间最新的排第1
           ) AS rn
    FROM price_history h
    JOIN competitor_product p ON p.product_id = h.product_id          -- 顺手拼上商品名/店铺名
) t
WHERE rn = 1;                                                        -- 只留每组第 1 条
```

三个点值得记：

- `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ... DESC)` 是"**分组取 Top1**"的标准写法，MySQL 8.0 才支持（5.7 不行，得用子查询绕）
- `ORDER BY h.crawl_time DESC, h.id DESC` 里第二个排序键不能省 —— 同一次采集是批量插入的，`crawl_time` 会**完全相同**，不加 `id` 兜底则同批内取哪条不确定
- 顺手 JOIN 了 `competitor_product`，因为 BI 里只有 `product_id` 人看不懂；这样图例直接显示商品名/店铺名，不用每段 SQL 重复 JOIN

视图 DDL 全部用 `CREATE OR REPLACE`，**可以反复重跑**，改完直接再执行，不用先 DROP。执行方式见 6-0 步骤007（含无 mysql.exe 时的 pymysql 片段）。

### 3.3 四个视图各管什么

| 视图 | 一句话职责 | 关键字段 | 喂给哪些图 |
|------|-----------|---------|-----------|
| `v_price_daily` | 按日去重后的价格快照（**看板唯一取数入口**） | `crawl_date` `price` `product_name` `shop_name` `sku_name` | 趋势折线、KPI |
| `v_price_change` | 在日快照上加环比 | `prev_price` `price_diff` `change_pct` `min_price_before` | 降价榜、历史新低 |
| `v_sku_latest` | SKU 当前三档价 + 折扣率 | `sku_price` `original_price` `discount_rate` `detail_url` | 明细表、价格分布、折扣榜 |
| `v_shop_summary` | 店铺维度汇总 | `avg_price` `min_price` `max_price` `sku_count` | 店铺对比 |

`v_price_change` 里有两个口径细节，是为了一件事：**让看板的数字和 ⑤ 钉钉告警的判定完全一致**，避免"钉钉说破底线了、看板却说没有"。

```sql
-- ① 环比：取上一日的价，不是"前一行的价"
LAG(price) OVER (PARTITION BY product_id, sku_name ORDER BY crawl_date) AS prev_price

-- ② 历史最低：**不含当日**。alert.py 判定"今日价 < 历史最低价（排除今日自身）"
--    窗口框架 ROWS ... AND 1 PRECEDING 就是"到前一行止"，正好等于"排除今天"
MIN(price) OVER (
    PARTITION BY product_id, sku_name ORDER BY crawl_date
    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
) AS min_price_before
```

如果这里用 `MIN(price) OVER (PARTITION BY ...)`（不带 ORDER 和框架），那是"含当日的历史最低"，今日价永远 ≥ 它，**「历史新低」这张表会恒为空**。这是个很容易写错、错了还不报错的坑。

### 3.4 两个 MySQL 视图的限制（实测）

- **视图里能用 FROM 子查询吗？** MySQL 文档把"SELECT 不能含 FROM 子查询"列为视图限制，但**实测 8.0.30 允许**（`v_price_daily` 就是这么写的）。别照抄老文档改写，先跑一次看看。真被拒时改用 `WHERE NOT EXISTS` 相关子查询。
- **改了视图结构（加/删列）之后**，Metabase 不会立刻知道，字段列表还是旧的 → 管理 → 数据库 → `price_monitor` → 拉到底「**手动同步**」。只改视图**内容**（列名不变）则不用同步。

---

## 4. Metabase SQL 写法两特性

- **中文列别名要用反引号包** `` AS `涨跌幅%` ``，含 `%`、空格、括号的别名不加反引号会报语法错。
- **想让图能被人筛选，就把字段做成参数化模板**（本模块暂未用，加筛选器时再看）：SQL 里写 `[[AND shop_name = {{shop}}]]`，`[[ ]]` 内是"参数为空时整段忽略"，然后在模板变量里声明 `shop` 类型为 Text，就能挂看板的下拉筛选器。

---

## 5. 踩坑总表

| 现象 | 原因 | 解法 |
|------|------|------|
| 启动即 `NoClassDefFoundError: java/util/SequencedCollection` | Metabase v0.6x 需 **Java 21+**，本机是 Java 17。`SequencedCollection` 是 Java 21 新增标准库类，看到名字即可断定版本问题 | 自带 Corretto JDK 21，启动脚本优先用它 |
| JDK 从 Adoptium/GitHub 只有 90 KB/s | GitHub Release 国内慢 | 换 Corretto（AWS CDN），实测 2.85 MB/s，快 30 倍 |
| 趋势图点数异常多、均价偏 | `price_history` 同日多次采集未去重（819→252） | 一律查 `v_price_daily` |
| 「历史新低」表恒为空 | 用了含当日的 `MIN(price)` | 改用 `ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING` |
| 打开网页 503 / 卡在 initializing | 首次 migration 要 1–2 分钟（建H2+全部迁移） | 等；看日志确认在跑 |
| 看板一片"无法处理此请求" | Metabase 比 MySQL 先启动 | 手动同步或重启 Metabase |
| 中文店铺名在柱图上全被切 | 竖向柱 + 长中文类名（39店×3系列塞10×8格子，每根<5px） | 改横向条形 + TOP N 截断，明细留给表格图 |
| 指标卡只显示一个数 | Scalar 只认 1 行 1 列 | 想多 KPI 同排就建多个卡，或用表格 |
| 中文别名报语法错 | 别名含 `%`、括号、空格 | 用反引号包起来 |
| 改完视图字段不刷新 | 元数据缓存 | 「手动同步」 |
| 跑 API 验证脚本，全 200 却判定为失败 | 本版 `/api/dataset` 同步结果返回 **HTTP 202** | 状态判断写 `in (200, 202)` |
| BI 里只有 product_id 人看不懂 | 视图层没拼维度 | `v_price_daily` 建视图时顺手 JOIN 商品名/店铺名 |
| 看板"当前价"里混着两个月前的旧商品 | `competitor_sku` 是 **upsert 累积表**，下架商品永不删（2026-10-25 实测 347 行里 228 行是旧批次） | 视图/告警一律按 `DATE(crawl_time)=最近采集日` 圈定，见 `v_sku_latest` 与 alert.py |
| 钉钉预警出现"幽灵降价"，今日价其实是旧快照 | `sku_ingest._parse_datetime` 曾用 `now()` 兜底：重放旧数据表时旧价被盖上"今天"戳 | 2026-10-25 已改为诚实回退当日 0 点；历史脏行需清理（见 §6 待修项） |
| `PUT /api/dashboard/:id` 报 500 `ClassCastException: String cannot be cast to Associative`（v0.64） | dashcards 条目字段不全（0.63 时代少字段还能过） | 每条必须给齐：`id`(负临时整数) `card_id` `col` `row` `size_x` `size_y` `series` `parameter_mappings` `visualization_settings` `dashboard_tab_id` |

### API 相关（只有打算脚本化建看板才需要）

| 现象 | 解法 |
|------|------|
| `POST /api/setup` → `errors.prefs: missing required key` | 必带 `"prefs":{"site_name":...,"site_locale":"zh"}`，站点名不放 `user` 里；`site_locale:"zh"` 即界面中文开关 |
| `POST /api/database` → `errors.details: Value 必须是 map` | 连接参数放 `details`，不是 `options` |
| `GET /api/database/metadata_graph`、`/autocomplete_filter` → 404 | v0.63 已移除，别用 |
| `POST /api/dashboard/:id/cards` → 404 | v0.63 无此端点 |
| `GET /api/card/:id/query` → 404 | 该端点是 **POST** |
| `GET /api/card/:id/render/png` → 404 | 服务端出图不可用；验证渲染只能开浏览器 |
| `PUT /api/dashboard/:id` 布局返回 200 但 0 张卡 | 用 `cards` 键会被**静默忽略**。要用 `dashcards` 键 |
| 同上，但报 `size_x missing` / `id should be an int` | `dashcards` 键 + **旧版字段名** `size_x`/`size_y` + 整数 `id`(=card_id)。别用 `width`/`height` 或字符串 uuid |
| `/api/card` 有时是数组、有时是 `{data:[...]}` | 兼容写：`r if isinstance(r,list) else r.get("data",[])` |

最后两条合起来说：**这版 Metabase 的看板布局接口是"新键名 + 旧字段名"的混搭**，文档里没写，只能靠错误信息反推。踩一次就记住，别再花时间试错。

---

## 6. 数据现状：为什么有 2 张表是空的

2026-09-25 实测：

| 指标 | 值 | 影响 |
|------|-----|------|
| 采集日 | 只有 **2 个**（2026-07-25、2026-08-05），中间断 11 天 | 折线图只有 2 个点 |
| 各日 SKU 数 | 31 / 6 | 第二天规模是第一天 1/5 |
| 两日重合 SKU | **6** | 环比算不出东西 |
| 可算环比的行 | 20 | ⑦降价榜、⑧历史新低各只有 **1 行** |
| 有价格历史的商品 | **55 / 63** | 8 个商品从没进过 `price_history` |
| `sku_price IS NULL` | 0 | 掩码价过滤正常 |

**这两张表只有 1 行是数据现状，不是 bug。** 连续跑满两周采集，它们自己会满。

在此之前，别加这些图（会做出空洞的东西）：周环比、月趋势、价格波动率/标准差带、大促前后对比（还要 [promo_dates.json](../../config/promo_dates.json) 里有真实档期）。

**两个比"加图"优先的数据待修项**：

1. **8 个商品有快照、无价格历史** —— `competitor_sku` 写了但 `price_history` 漏写，查 [sku_ingest.py](../4.竞品数据汇总/sku_ingest.py) 的追加逻辑；
2. **两日 SKU 集合只重合 6 个** —— 说明监控清单本身在漂移。做趋势前得先**固定一批 `product_id` 当稳定监控集**，否则环比永远算不出来。

```sql
-- 复现待修项 1：哪 8 个商品没有历史
SELECT p.product_id, p.product_name, p.shop_name
FROM competitor_product p
LEFT JOIN price_history h ON h.product_id = p.product_id
WHERE h.id IS NULL;
```

---

## 7. 和 ④日报 / ⑤告警 的分工（别做成三不像）

| 环节 | 归谁 | 为什么 |
|------|------|--------|
| 每日定时出固定报表（Excel、嵌主图） | ④ [report.py](../4.竞品数据汇总/report.py) | 固定格式、要发给别人、要留档 |
| 价格破线主动推钉钉 | ⑤ [alert.py](../5.竞品价格告警/alert.py) | **推送**是主动的，看板是被动的 |
| 想临时看"这家店某个型号近一周怎么走"、筛选、排序、下钻 | ⑥ 本模块 | 探索式，不该写进脚本 |

**Metabase 不替代前两个。** 判断标准很简单：需要"主动找上你"的 → 脚本；需要"你去翻、要问不同的问题"的 → BI。

两者口径靠 §3.3 的 `min_price_before` 对齐（同一套"历史最低/昨日价"定义），不会出现"钉钉说破线、看板说没破"。

---

## 8. 安全边界（现在是本地单机形态，上服务器/给人看之前必做）

1. **H2 配置库**：启动日志有官方警告，H2 不建议生产用。要长期跑或多实例，迁移到 MySQL/PG —— 见 [migrating-from-h2](https://metabase.com/docs/latest/operations-guide/migrating-from-h2.html)。
2. **给 BI 建只读账号**（BI 只需要 SELECT，不该拿 root）：
   ```sql
   CREATE USER 'mb_readonly'@'localhost' IDENTIFIED BY '<强密码>';
   GRANT SELECT ON price_monitor.* TO 'mb_readonly'@'localhost';
   ```
   然后在 Metabase 数据源里把 root 换成它。顺带解决 MySQL root 明文躺在 [config/database.json](../../config/database.json) 里的问题。
3. **默认只监听 127.0.0.1**：启动脚本里 `set "BIND=127.0.0.1"`。改成 `0.0.0.0` 就等于把竞品价格数据给整个局域网看 —— 想给同事看更该走内网反代 + HTTPS，而不是放开 3000。
4. **`MB_SESSION_SECRET_KEY`** 已自动生成在 `mb_secret.txt`（首次启动时），**这个文件不要提交、不要外传**。不设它的话日志会警告：任何能读到 `metabase.db` 的人可伪造会话冒充管理员。
5. **管理员密码不写进任何仓库文档**，包括本文。

---

## 附：当时的自动化实现（可选，仓库外）

`F:\Programs\metabase\` 下这 6 个脚本是我把搭建流程脚本化的记录，**正常用不上**（全部能在 UI 里手点完成，见 6-0）：

| 脚本 | 干什么 | 对应 |
|------|--------|------|
| `setup_metabase.py` | 建管理员 + 加数据源 + 等同步 | 6-0 步骤006/008 |
| `verify_db.py` | 触发同步 + 实跑 4 个视图看返回 | 6-0 步骤007 |
| `build_dashboard.py` | 建 10 个问题 + 建看板（幂等，先清同名） | 6-0 步骤009/010 |
| `layout_dashboard.py` | 排 24 列栅格 | 6-0 附录E |
| `refine_cards.py` | 单张卡返工（柱图改横向） | 6-0 附录A·A6 |
| `final_check.py` | 逐张卡跑一遍，确认渲染路径通 | 6-0 步骤011 |

> **这些脚本里硬编码了开发环境的密码（Metabase 管理员、以及从 `database.json` 读的 MySQL root），所以刻意放在仓库外、不进 git。** 要参考写法就从上面各文档节抄 payload，别把它们复制进仓库 —— 这个仓库是要拿去面试的。

**已验证到什么程度（诚实边界）**：10 张图各自的 SQL 都跑过、返回行数已核对（见 §6 表）、布局坐标已回读确认。但**没有一张图是我肉眼在浏览器里看过渲染效果的** —— 服务端出图接口 v0.63 不可用，浏览器自动化那条路被权限拦了。所以"图的样子好不好看、中文有没有糊、日期轴格式对不对"这三件事，就是 6-0 步骤011 必须人工开浏览器验收的原因。
