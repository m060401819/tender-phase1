# Crawl Error Admin（第一期抓取错误查询与管理页面）

第一期在已支持 `crawl_error` 入库记录的基础上，提供最小查询 API 和管理页面，便于排查抓取、解析、写入过程中的失败原因。

## 1. 接口与页面

- API 列表：`GET /crawl-errors`
- API 详情：`GET /crawl-errors/{id}`
- 管理列表：`GET /admin/crawl-errors`
- 管理详情：`GET /admin/crawl-errors/{id}`

## 2. `GET /crawl-errors` 列表能力

筛选参数：

- `source_code`
- `stage`（`fetch/parse/persist`）
- `crawl_job_id`
- `error_type`

分页与排序：

- 分页：`limit / offset`
- 排序：按 `created_at` 倒序（同时间按 `id` 倒序）

返回摘要字段：

- `id`
- `source_code`
- `crawl_job_id`
- `stage`
- `error_type`
- `message`
- `url`
- `created_at`

## 3. `GET /crawl-errors/{id}` 详情能力

返回主要字段：

- `id`
- `source_code`
- `crawl_job_id`
- `stage`
- `error_type`
- `message`
- `detail`
- `url`
- `traceback`
- `created_at`

如存在关联关系，返回最小摘要：

- `raw_document`：`id/document_type/fetched_at/storage_uri`
- `notice`：`id/source_code/title/notice_type/current_version_id`
- `notice_version`：`id/notice_id/version_no/is_current/title/notice_type`

不存在返回：

```json
{"detail":"crawl_error not found"}
```

## 4. `/admin/crawl-errors` 页面能力

- 展示错误摘要列表
- 支持 `source_code / stage / crawl_job_id / error_type` 筛选
- 支持 `limit / offset` 分页
- 每条记录可跳转 `/admin/crawl-errors/{id}`
- `crawl_job_id` 可跳转到 `/admin/crawl-jobs/{id}`

## 5. `/admin/crawl-errors/{id}` 页面能力

- 展示完整错误信息（含 `message/detail/traceback`）
- 展示关联 `raw_document` / `notice` / `notice_version` 摘要
- 关联实体提供跳转链接（`/admin/raw-documents/{id}`、`/admin/notices/{id}`）

## 6. 实现落点

- API 路由：`app/api/endpoints/crawl_errors.py`
- 管理页路由：`app/api/endpoints/admin_crawl_errors.py`
- Schema：`app/api/schemas/crawl_error.py`
- Repository：`app/repositories/crawl_error_repository.py`
- Service：`app/services/crawl_error_query_service.py`
- 模板：`app/templates/admin/crawl_errors_list.html`、`app/templates/admin/crawl_errors_detail.html`
- 测试：`tests/test_crawl_error_api.py`、`tests/test_crawl_error_admin_pages.py`
