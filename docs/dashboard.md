# Dashboard（第一期统计总览）

第一期基于现有 `source_site / crawl_job / tender_notice / raw_document / crawl_error` 提供最小可用统计总览，便于快速查看系统运行情况。

## 1. 接口与页面

- API：`GET /stats/overview`
- 页面：`GET /admin/dashboard`

## 2. `GET /stats/overview` 返回内容

核心计数：

- `source_count`
- `active_source_count`
- `crawl_job_count`
- `crawl_job_running_count`
- `notice_count`
- `raw_document_count`
- `crawl_error_count`

最近 7 天趋势（按天聚合）：

- `recent_7d_crawl_job_counts`
- `recent_7d_notice_counts`
- `recent_7d_crawl_error_counts`

每个趋势项结构：

- `date`（`YYYY-MM-DD`）
- `count`

页面复用的最近摘要：

- `recent_failed_or_partial_jobs`
- `recent_crawl_errors`

## 3. `/admin/dashboard` 页面能力

- 展示核心计数卡片
- 用简单表格展示最近 7 天趋势
- 展示最近失败或 `partial` 的 `crawl_job` 摘要
- 展示最近 `crawl_error` 摘要
- 提供跳转链接到：
  - `/admin/sources`
  - `/admin/crawl-jobs`
  - `/admin/notices`
  - `/admin/raw-documents`
  - `/admin/crawl-errors`

## 4. 使用示例

```bash
curl "http://127.0.0.1:8000/stats/overview"
```

```bash
http://127.0.0.1:8000/admin/dashboard
```

## 5. 实现落点

- API 路由：`app/api/endpoints/stats.py`
- Admin 路由：`app/api/endpoints/admin_dashboard.py`
- Schema：`app/api/schemas/stats.py`
- Repository：`app/repositories/stats_repository.py`
- Service：`app/services/stats_service.py`
- 模板：`app/templates/admin/dashboard.html`
- 测试：`tests/test_stats_api.py`、`tests/test_dashboard_admin_pages.py`
