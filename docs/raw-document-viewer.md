# Raw Document Viewer（第一期原始文档最小查看）

本功能用于把公告详情页中的 `raw_document` 摘要变成可访问、可查看、可定位的原始文档入口。

## 1. 接口与页面

- API：`GET /raw-documents/{id}`
- 页面：`GET /admin/raw-documents/{id}`
- 本地文件下载：`GET /admin/raw-documents/{id}/download`

## 2. GET /raw-documents/{id} 返回内容

固定返回 `raw_document` 主要字段：

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

如存在关联关系，补充最小摘要：

- `notice_version`：`id/notice_id/version_no/is_current/title/notice_type`
- `tender_notice`：`id/source_code/title/notice_type/published_at/current_version_id`

不存在返回：

```json
{"detail":"raw_document not found"}
```

## 3. `/admin/raw-documents/{id}` 页面能力

- 展示 `raw_document` 主要字段
- 展示关联 `notice_version` / `tender_notice` 摘要
- 若 `storage_uri` 指向可访问的本地文件（`file://` 且文件存在），显示“下载原始文件”入口
- 提供关联公告跳转入口：`/admin/notices/{notice_id}`
- 提供原始 JSON 调试区

## 4. 公告详情页联动

`/admin/notices/{id}` 的版本区域新增 `raw_document` 跳转链接：

- 版本查看器中的当前 `raw_document` 摘要可直接跳转
- 历史版本表中的每条 `raw_document` 摘要可直接跳转

## 5. 实现落点

- API 路由：`app/api/endpoints/raw_documents.py`
- Admin 路由：`app/api/endpoints/admin_raw_documents.py`
- Schema：`app/api/schemas/raw_document.py`
- Repository：`app/repositories/raw_document_repository.py`
- Service：`app/services/raw_document_query_service.py`
- 页面模板：`app/templates/admin/raw_documents_detail.html`
- 测试：`tests/test_raw_document_api.py`、`tests/test_raw_document_admin_pages.py`
