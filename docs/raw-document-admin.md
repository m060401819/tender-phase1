# Raw Document Admin（第一期原始文档列表与筛选）

第一期在已支持 `raw_document` 详情查看的基础上，补充最小列表查询与管理页面，便于按来源、文档类型、任务维度浏览原始文档集合。

## 1. 接口与页面

- API 列表：`GET /raw-documents`
- API 详情：`GET /raw-documents/{id}`
- 管理列表页：`GET /admin/raw-documents`
- 管理详情页：`GET /admin/raw-documents/{id}`

## 2. `GET /raw-documents` 查询能力

支持筛选参数：

- `source_code`
- `document_type`
- `crawl_job_id`
- `content_hash`

分页与排序：

- `limit / offset`
- 固定按 `fetched_at` 倒序（同时间按 `id` 倒序）

列表返回摘要字段：

- `id`
- `source_code`
- `crawl_job_id`
- `url`
- `normalized_url`
- `document_type`
- `fetched_at`
- `storage_uri`
- `mime_type`
- `title`
- `content_hash`

## 3. `/admin/raw-documents` 页面能力

- 展示 `raw_document` 摘要列表
- 支持筛选：
  - `source_code`
  - `document_type`
  - `crawl_job_id`
- 支持 `limit / offset` 分页
- 每条记录可跳转 `/admin/raw-documents/{id}`
- 支持公告详情页跳转上下文：
  - 若来自 `/admin/notices/{id}`，可自动带 `source_code` 等筛选条件
  - 通过 `from_notice_id` 保留“返回公告详情”入口

## 4. 访问示例

```bash
curl "http://127.0.0.1:8000/raw-documents?source_code=anhui_ggzy_zfcg&document_type=html&crawl_job_id=900&limit=20&offset=0"
```

```bash
http://127.0.0.1:8000/admin/raw-documents
```

## 5. 实现落点

- API 路由：`app/api/endpoints/raw_documents.py`
- Admin 路由：`app/api/endpoints/admin_raw_documents.py`
- Schema：`app/api/schemas/raw_document.py`
- Repository：`app/repositories/raw_document_repository.py`
- Service：`app/services/raw_document_query_service.py`
- 管理列表模板：`app/templates/admin/raw_documents_list.html`
- 测试：`tests/test_raw_document_api.py`、`tests/test_raw_document_admin_pages.py`
