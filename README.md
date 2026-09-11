# schema-lint

批量提取并校验任意页面的 Schema.org / JSON-LD 结构化数据，按 Google rich results 的要求
报出缺失字段，并给出 0–100 的评分。

**为什么有人会为它付钱**：Google 官方的 Rich Results Test 一次只能查一个 URL。
任何要批量看站的人（SEO、电商运营、做 AI 搜索可见度/GEO 的人）都得靠工具。
而这个品类里挤满的是 LinkedIn 爬虫和 Google Maps 爬虫，校验器这一格基本是空的。

---

## 输出字段（每条结果）

| 字段 | 说明 |
|---|---|
| `url` / `finalUrl` | 原始 URL 与重定向后的最终 URL |
| `httpStatus` | 状态码 |
| `jsonLdBlockCount` | 页面上 JSON-LD 块的数量 |
| `types` | 检测到的所有 schema.org 类型（含 `@graph` 里的嵌套节点） |
| `issues[]` | 问题列表，每条含 `severity` / `type` / `field` / `message` / `recommendation` |
| `errorCount` / `warningCount` | 错误数（阻断 rich result）/ 警告数（影响展现） |
| `score` / `grade` | 0–100 分与 A–F 评级 |

评分：`100 - error×15 - warning×5`，下限 0。页面完全没有 JSON-LD 直接判 0 分 F。

**severity 的含义**
- `error` —— 缺 Google 要求的必填字段，rich result 根本出不来。
  例：`Product` 缺 `image`；`offers.price` 写成 `"$29.99"`（必须是裸数字）；`offers` 缺 `priceCurrency`
- `warning` —— 不阻断但明显影响展现或数据质量。
  例：缺 `aggregateRating`、日期不是 ISO 8601、图片用的是相对路径

实际会抓到的高频错误（也是这个工具的卖点）：
`Product` 的 `offers` 里 `price` 带货币符号、`priceCurrency` 缺失、日期写成 `2026/09/11`、
`image` 用了相对路径、整页压根没有 JSON-LD。

---

## 本地跑通（不需要 Apify 账号）

核心校验逻辑是纯标准库，可以直接单测：

```bash
cd src
python3 -c "
from validator import lint_html
print(lint_html(open('some_page.html').read()))"
```

端到端跑真实网页（只需 httpx，不需要 apify SDK）：

```bash
pip install httpx
python src/smoke.py https://example.com https://your-site.com
```

---

## 部署到 Apify

```bash
pip install apify-cli
apify login
apify push
```

首次 push 后去 Console 的 Publication 页做三件事：

1. **完成 KYC**（身份证 + 地址证明 + 税务文件 + UBO）。
   ⚠️ 余额因 KYC 未完成被搁置连续满 12 个月会被平台没收，注册完就先做掉
2. **配置 pay-per-event**：primary event 选 `apify-default-dataset-item`
   （每条结果计费，零代码）。参考价 Bronze $0.02 / 条，Silver 低 10%，Gold 低 20%。
   免费档定价不要激进——那是获客漏斗，不是收入来源
   ⚠️ rental 定价模式 2026-09-30 终止，新 actor 一律直接上 pay-per-event
3. **填 README 和示例输出**，Store 页面的质量分影响排序

---

## 已知边界（诚实说明）

- 只校验 JSON-LD。不处理 microdata 和 RDFa（v2 再说，JSON-LD 占了绝大多数）
- 不做 JS 渲染。纯服务端 HTML 抓取，SPA 站点会漏（要渲染就得上 Playwright，成本翻十倍，
  对这个价位不划算）
- 规则是内置的静态表，不是 Google 的实时规则。Google 改规则时我会更新 `validator.py` 里的
  `REQUIRED` / `RECOMMENDED`

---

## 还能怎么用它

除了收租，这个仓库最重要的用途是**当 Fiverr gig 的 GitHub 作品集**。
新卖家没评价就没排名，而一个跑得通、有测试、有文档的仓库，是唯一不靠人脉能拿出来的 proof。
