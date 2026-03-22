# Phase-1 数据模型设计（信息采集与聚合）

本文档说明第一期核心数据表（不包含 AI 匹配、企业资质库、投标文件生成）。

## 1. 设计目标
- 支持多数据源采集和任务追踪
- 原始归档与结构化公告解耦
- 支持同一公告多版本演进
- 支持附件元数据统一管理
- 支持 URL 去重与内容哈希去重
- 支持公告/变更/结果三类公告

## 2. 核心表

### 2.1 `source_site`
数据源主表。

关键字段：
- `id` 主键
- `code` 站点唯一编码（唯一）
- `name` 站点名称
- `base_url` 站点入口
- `official_url` 官网链接
- `list_url` 列表页链接
- `is_active` 是否启用
- `supports_js_render` 是否需要 JS 渲染
- `crawl_interval_minutes` 默认抓取间隔

---

### 2.2 `crawl_job`
抓取任务执行记录。

关键字段：
- `source_site_id` -> `source_site.id`
- `job_type`：`scheduled/manual/backfill`
- `status`：`pending/running/succeeded/failed/partial`
- `started_at` / `finished_at`
- `pages_fetched` / `documents_saved` / `notices_upserted` / `deduplicated_count` / `error_count`

用途：记录每轮采集作业状态、统计和错误规模。

---

### 2.3 `raw_document`
原始文档归档元数据（HTML/PDF/JSON）。

关键字段：
- `source_site_id` -> `source_site.id`
- `crawl_job_id` -> `crawl_job.id`
- `url` / `normalized_url`
- `url_hash`（URL 去重）
- `content_hash`（内容去重）
- `document_type`：`html/pdf/json/other`
- `storage_uri` 原文存储位置
- `fetched_at` 抓取时间

关键约束：
- `UNIQUE(source_site_id, url_hash)`：同源 URL 去重
- `INDEX(content_hash)`：内容哈希去重检索

---

### 2.4 `tender_notice`
结构化公告主实体（聚合后的“当前状态”）。

关键字段：
- `source_site_id` -> `source_site.id`
- `external_id` 源站公告 ID
- `project_code` 项目编号
- `dedup_hash` 聚合去重键
- `dedup_key` Phase-3 主去重键
- `title`
- `notice_type`：`announcement/change/result`
- `issuer` 招标人
- `region` 地区
- `published_at` / `deadline_at`
- `budget_amount` / `budget_currency`
- `current_version_id` -> `notice_version.id`

关键约束：
- `UNIQUE(source_site_id, external_id)`
- `UNIQUE(source_site_id, dedup_hash)`

---

### 2.5 `notice_version`
公告版本快照表（同一公告的历史版本）。

关键字段：
- `notice_id` -> `tender_notice.id`
- `raw_document_id` -> `raw_document.id`
- `version_no` 版本号
- `is_current` 是否当前版本
- `content_hash` 版本内容哈希
- `dedup_key` 版本归属去重键
- `title` / `notice_type` / `issuer` / `region`
- `published_at` / `deadline_at`
- `budget_amount` / `budget_currency`
- `structured_data` 结构化 JSON 快照
- `change_summary` 变更摘要

关键约束：
- `UNIQUE(notice_id, version_no)`
- `UNIQUE(notice_id, content_hash)`

---

### 2.6 `tender_attachment`
公告附件元数据表。

关键字段：
- `source_site_id` -> `source_site.id`
- `notice_id` -> `tender_notice.id`
- `notice_version_id` -> `notice_version.id`
- `raw_document_id` -> `raw_document.id`
- `file_name` / `file_url`
- `url_hash`（附件 URL 去重）
- `file_hash`（文件内容去重）
- `storage_uri` / `mime_type` / `file_size_bytes`
- `attachment_type`：`notice_file/bid_file/other`

关键约束：
- `UNIQUE(source_site_id, url_hash)`
- `INDEX(file_hash)`

---

### 2.7 `crawl_error`
抓取/解析/入库错误日志。

关键字段：
- `source_site_id` -> `source_site.id`
- `crawl_job_id` -> `crawl_job.id`
- `raw_document_id` -> `raw_document.id`
- `stage`：`fetch/parse/persist`
- `error_type` / `error_message` / `traceback`
- `url`
- `retryable`
- `occurred_at`

用途：用于任务观测、重试策略和失败排查。

## 3. 关系总览
- `source_site 1 -> N crawl_job`
- `source_site 1 -> N raw_document`
- `source_site 1 -> N tender_notice`
- `source_site 1 -> N tender_attachment`
- `source_site 1 -> N crawl_error`
- `crawl_job 1 -> N raw_document`
- `crawl_job 1 -> N crawl_error`
- `tender_notice 1 -> N notice_version`
- `tender_notice 1 -> N tender_attachment`
- `tender_notice.current_version_id -> notice_version.id`
- `notice_version N -> 1 raw_document`
- `tender_attachment N -> 1 notice_version`（可空）
- `crawl_error N -> 1 raw_document`（可空）

## 4. 建模边界
第一期只实现采集聚合所需核心结构：
- 不含 AI 语义分析字段
- 不含企业资质匹配字段
- 不含投标文件生成字段

## 5. 去重与版本策略（写入层固化）

去重与版本逻辑由写入层统一执行（`writers/sqlalchemy_writer.py` + `services/deduplication.py`），不依赖具体 spider 的临时实现细节。

### 5.1 URL 去重
- 对 `raw_document.url` 做标准化（host 小写、query 排序、去 fragment）得到 `normalized_url`
- 计算 `url_hash = sha256(normalized_url)`
- 按 `UNIQUE(source_site_id, url_hash)` 做 upsert
- 命中同 URL 时更新最新元数据，并标记 `is_duplicate_url=true`

### 5.2 内容去重
- `raw_document.content_hash` 优先使用上游传入值；缺失时由写入层对正文计算
- 同源存在相同 `content_hash` 且 URL 不同时，标记 `is_duplicate_content=true`
- `notice_version` 维度按 `UNIQUE(notice_id, content_hash)` 保证同公告同内容只保留一个版本快照

### 5.3 公告归并（`tender_notice.dedup_key`）
写入层按以下规则生成稳定主去重键：

`dedup_key = sha256(normalized_title + published_date(day) + normalized_purchaser_or_publisher + normalized_budget_bucket + normalized_detail_locator)`

说明：
- `normalized_detail_locator` 优先使用 `guid/detail_id`，否则回退到标准化 `detail_url`
- `source_duplicate_key` 与 `dedup_key` 同步写入，用于兼容旧链路
- `dedup_hash` 继续保留为兼容字段

### 5.4 版本跟踪
- 同一公告重复抓取且 `content_hash` 不变：不新增 `notice_version`
- 同一公告 `content_hash` 变化：新增版本，`version_no` 递增
- `tender_notice` 保存当前快照字段（标题、类型、发布时间、预算等）
- `notice_version` 保存历史快照（含 `structured_data`）
- 新版本标记 `is_current=true`，旧版本统一置为 `false`
- `tender_notice.current_version_id` 指向当前版本

### 5.5 公告类型规范化
- 写入层统一规范到枚举：`announcement` / `change` / `result`
- 非法值自动回退为 `announcement`
