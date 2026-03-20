# Notice Version Viewer（第一期公告详情页版本联动）

本增强面向 `/admin/notices/{id}`，用于在单个公告详情页中按版本查看结构化字段、原文摘要和对应附件。

## 1. 页面能力

- 在 `/admin/notices/{id}` 增加“版本查看器”
- 支持通过查询参数选择版本：
  - `version_id`
  - `version_no`
- 未显式传参时，默认选择：
  - `tender_notice.current_version_id` 对应版本
  - 若不存在则回退到版本列表第一条

## 2. 版本联动展示

选中版本后，页面展示：

- `title`
- `notice_type`
- `issuer`
- `region`
- `published_at`
- `deadline_at`
- `content_hash`
- `raw_document` 摘要（`id/document_type/fetched_at/storage_uri`）

## 3. 附件联动规则

- 附件表仅展示 `notice_version_id == selected_version.id` 的附件
- 同时在表头提示当前过滤版本与“已展示/总附件”数量
- 若无匹配附件，显示空状态

## 4. 使用示例

```bash
# 默认查看当前版本
http://127.0.0.1:8000/admin/notices/101

# 按 version_no 查看
http://127.0.0.1:8000/admin/notices/101?version_no=1

# 按 version_id 查看
http://127.0.0.1:8000/admin/notices/101?version_id=204
```

## 5. 实现落点

- 路由与联动逻辑：`app/api/endpoints/admin_notices.py`
- 页面模板：`app/templates/admin/notices_detail.html`
- 页面测试：`tests/test_notice_admin_pages.py`
