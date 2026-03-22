# Crawl Job Admin（第一期最小管理页面）

第一期提供不带认证的最小任务看板页面，用于查看 `crawl_job` 执行结果。  
Phase-2 第6步在此基础上增加“异常任务单次重试”最小闭环。

## 1. 页面地址

- 列表页：`/admin/crawl-jobs`
- 详情页：`/admin/crawl-jobs/{id}`
- 重试动作：`POST /admin/crawl-jobs/{job_id}/retry`
- API 重试入口：`POST /crawl-jobs/{job_id}/retry`

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
- 新增重试相关展示：
  - 是否已重试
  - 重试后的新任务链接
  - 重试结果状态（`succeeded/failed/partial`）
- 支持筛选：`source_code / status / job_type`
- 支持分页：`limit / offset`
- 支持排序：`order_by=started_at|id`（倒序）
- `failed/partial` 且未重试的任务显示“重试”按钮

## 3. 详情页能力

- 展示 `crawl_job` 全部主要字段
- 展示 `recent_crawl_error_count`
- 展示重试关系字段：
  - `retry_of_job_id`
  - `retried_by_job_id`
  - `retried_by_status`
- 展示“上次失败 vs 本次重试”的最小对比摘要
- 提供原始 JSON 区域，便于调试接口数据

## 4. 实现说明

- 使用 FastAPI + Jinja2 服务端渲染
- 页面查询逻辑复用现有 `crawl-jobs` API 处理函数
- 重试复用现有 `crawl_job` 创建与 spider 触发链，不引入额外异步系统
- 不引入前端框架，不引入认证系统

## 5. 重试规则（最小版）

- 仅允许 `failed` 或 `partial` 任务触发重试
- 每个异常任务只允许单次人工重试
- 重试任务会创建新的 `crawl_job`：
  - `job_type = manual_retry`
  - `retry_of_job_id = 原任务 id`
- 若不满足条件返回：
  - `404`：任务不存在
  - `400`：状态不允许或已重试

## 6. 本地访问

启动服务后访问：

```bash
http://127.0.0.1:8000/admin/crawl-jobs
```
