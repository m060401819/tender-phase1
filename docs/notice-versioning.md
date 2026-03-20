# Notice Versioning（第一期公告版本追踪与原文关联）

第一期在公告详情查询中增强版本追踪能力，用于审计同一公告的历史变化。

## 1. 能力范围

- `GET /notices/{id}` 返回 `versions` 历史版本列表
- 每个版本可关联 `raw_document` 摘要（如存在）
- `/admin/notices/{id}` 增加“历史版本”区域
- 附件列表显示所属版本（`version_no`）

## 2. API 结构

`/notices/{id}` 在原有字段基础上新增：

- `versions[]`
  - `id`
  - `version_no`
  - `is_current`
  - `notice_type`
  - `published_at`
  - `deadline_at`
  - `content_hash`
  - `raw_document_id`
  - `raw_document`（可空）
    - `id`
    - `document_type`
    - `fetched_at`
    - `storage_uri`

说明：
- 当前版本仍由 `current_version` 返回
- `versions` 用于历史追踪，当前版本也会包含在 `versions` 中

## 3. 页面展示

`/admin/notices/{id}` 增强内容：

1. 历史版本表格：`version_no / is_current / published_at / content_hash`
2. 原文摘要：`raw_document` 的 `id/type/fetched_at/storage_uri`
3. 附件归属：在附件表中显示 `notice_version_id` 与 `version_no`

## 4. 实现落点

- Repository：`app/repositories/notice_repository.py`
  - 聚合 `versions`
  - 聚合 `raw_document` 摘要
  - 解析 `current_version`
- API：`app/api/endpoints/notices.py`
- Admin：`app/api/endpoints/admin_notices.py`
- 模板：`app/templates/admin/notices_detail.html`

## 5. 验证建议

- API：`GET /notices/{id}` 检查 `versions` 与 `raw_document` 字段
- 页面：`/admin/notices/{id}` 检查历史版本区和附件所属版本

更多“版本选择联动查看”的页面说明见：`docs/notice-version-viewer.md`。
