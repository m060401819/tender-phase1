# 源站重复抑制与业务去重策略（Phase-3 第2步）

本文档定义三类看起来“像重复”但语义不同的场景，并给出系统处理边界。

## 1. 源站重复（source-side duplicate）

定义：
- 来源网站列表页自身重复展示同一条公告（同标题/同详情链接/同发布日期等）
- 这是输入噪声，不应污染库与工作台

处理层级：
- 运行内（spider）：先做 `source_list_item_fingerprint` 去重，重复列表项不再进入详情抓取
- 入库侧（writer）：用 `source_duplicate_key + content_hash` 抑制历史重复输入

关键点：
- 同 `source_duplicate_key` 且 `content_hash` 一致：判定为源站重复，计入 `source_duplicates_suppressed`
- 不新增重复 `raw_document / tender_notice / notice_version`

## 2. 业务公告去重（workbench dedup）

定义：
- 面向 `/admin/notices` 的展示聚合去重
- 以 `dedup_key`（及稳定回退策略）聚合同一业务公告

处理层级：
- 查询/展示层（`/notices` 与 `/admin/notices`）

关键点：
- 这是“展示聚合”，不能替代源站输入去噪
- 源站重复抑制必须先发生在采集/入库链路

## 3. 真实版本更新（version update）

定义：
- 同一公告（可同 `source_duplicate_key`），但详情正文内容变化（`content_hash` 变化）

处理层级：
- 版本层（`notice_version`）

关键点：
- 不是源站重复，不应被抑制
- 应继续创建新 `notice_version`，并维护 `is_current / version_no`

## 4. Key 计算规则

### 4.1 `source_list_item_fingerprint`（运行内列表去重）

输入字段（归一化后）：
- `source_code`
- `normalized_title`
- `normalized_detail_url`
- `published_at`（按天归一）
- `notice_type`
- `region`

输出：
- `sha256(joined_seed)`

### 4.2 `dedup_key`（入库侧主去重键）

输入字段（归一化后）：
- `normalized_title`
- `published_at`（按天归一）
- `normalized_purchaser_or_publisher`
- `normalized_budget_bucket`
- `normalized_detail_locator`（优先 `guid/detail_id`，否则 `detail_url`）

输出：
- `sha256(joined_seed)`

兼容说明：
- `source_duplicate_key` 仍保留并与 `dedup_key` 同步写入，便于旧链路兼容

## 5. 标准化规则

统一在 `DeduplicationService`：
- 标题/文本：去首尾空格、连续空白压缩、`NFKC` 全半角归一
- URL：标准化 + 移除明显无关 query（如 `utm_* / spm / from / timestamp`）
- 日期：解析为 UTC 后按天归一为 `YYYY-MM-DD`
- 空值：统一使用稳定占位，保证 hash 结果稳定

## 6. 任务统计字段（crawl_job）

本步新增并在 `/crawl-jobs` 与 `/admin/crawl-jobs` 展示：
- `list_items_seen`
- `list_items_unique`
- `list_items_source_duplicates_skipped`
- `detail_pages_fetched`
- `records_inserted`
- `records_updated`
- `source_duplicates_suppressed`
