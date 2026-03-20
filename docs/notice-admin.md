# Notice Admin（第一期最小公告管理页面）

第一期提供最小公告管理页面，便于直接查看已入库公告与版本/附件信息。

## 1. 页面地址

- 列表页：`/admin/notices`
- 详情页：`/admin/notices/{id}`

## 2. 列表页能力

- 展示字段：
  - `id`
  - `source_code`
  - `title`
  - `notice_type`
  - `issuer`
  - `region`
  - `published_at`
  - `deadline_at`
  - `budget_amount`
- 支持筛选：`keyword / source_code / notice_type / region`
- 支持分页：`limit / offset`
- 支持导出：CSV / JSON（保留当前筛选条件）
- 每条记录可跳转详情页

## 3. 详情页能力

- 展示 `tender_notice` 主要字段
- 展示 `current_version` 主要字段
- 展示 `versions` 历史版本区域（含 `raw_document` 摘要）
- `raw_document` 摘要支持跳转到原始文档详情页（`/admin/raw-documents/{id}`）
- 增加“版本查看器”：
  - 支持 `version_id` / `version_no` 选择指定版本
  - 展示指定版本字段（`title/notice_type/issuer/region/published_at/deadline_at/content_hash`）
  - 展示指定版本关联的 `raw_document` 摘要
- 展示“版本附件列表”：
  - 仅显示选中版本的附件
  - 明确显示附件所属 `version_no`
- 展示来源基本信息
- 提供原始 JSON 调试区域

## 4. 实现说明

- 使用 FastAPI + Jinja2 服务端渲染
- 页面查询逻辑复用现有 `GET /notices` 与 `GET /notices/{id}` 处理函数
- 不引入认证系统，不引入前端框架

## 5. 访问示例

启动服务后访问：

```bash
http://127.0.0.1:8000/admin/notices
```
