# Crawl Job API（第一期最小查询接口）

本接口用于查询 `crawl_job` 执行记录与统计结果，支持筛选、排序和分页。

## 1. 接口列表

- `GET /crawl-jobs`
- `GET /crawl-jobs/{id}`

## 2. GET /crawl-jobs

### Query 参数

- `source_code`：按来源编码筛选（可选）
- `status`：按任务状态筛选（可选）
  - `pending/running/succeeded/failed/partial`
- `job_type`：按任务类型筛选（可选）
  - `manual/scheduled/backfill`
- `order_by`：倒序字段（可选）
  - `started_at`（默认）或 `id`
- `limit`：分页大小，默认 `20`，范围 `1-200`
- `offset`：分页偏移，默认 `0`

### 响应结构（摘要）

- `items[]`：任务列表
  - `id`
  - `source_site_id`
  - `source_code`
  - `job_type`
  - `status`
  - `started_at`
  - `finished_at`
  - `pages_fetched`
  - `documents_saved`
  - `notices_upserted`
  - `deduplicated_count`
  - `error_count`
  - `message`
- `total`
- `limit`
- `offset`
- `order_by`

## 3. GET /crawl-jobs/{id}

### Path 参数

- `id`：`crawl_job.id`

### 响应结构（详情）

返回列表接口的主要字段，并补充：
- `recent_crawl_error_count`：最近 7 天关联 `crawl_error` 数量

若不存在返回 `404`：

```json
{"detail":"crawl_job not found"}
```

## 4. 示例

```bash
curl "http://127.0.0.1:8000/crawl-jobs?source_code=anhui_ggzy_zfcg&status=running&limit=20&offset=0"
```

```bash
curl "http://127.0.0.1:8000/crawl-jobs/1"
```
