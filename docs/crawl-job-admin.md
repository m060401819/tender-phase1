# Crawl Job Admin（第一期最小管理页面）

第一期提供不带认证的最小任务看板页面，用于查看 `crawl_job` 执行结果。

## 1. 页面地址

- 列表页：`/admin/crawl-jobs`
- 详情页：`/admin/crawl-jobs/{id}`

## 2. 列表页能力

- 展示字段：
  - `id`
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
- 支持筛选：`source_code / status / job_type`
- 支持分页：`limit / offset`
- 支持排序：`order_by=started_at|id`（倒序）

## 3. 详情页能力

- 展示 `crawl_job` 全部主要字段
- 展示 `recent_crawl_error_count`
- 提供原始 JSON 区域，便于调试接口数据

## 4. 实现说明

- 使用 FastAPI + Jinja2 服务端渲染
- 页面查询逻辑复用现有 `crawl-jobs` API 处理函数
- 不引入前端框架，不引入认证系统

## 5. 本地访问

启动服务后访问：

```bash
http://127.0.0.1:8000/admin/crawl-jobs
```
