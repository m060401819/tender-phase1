# Source Health（Phase-2 第5步）

## 1. 目标

在来源运营页面提供“可运营、可排障、可重试”的最小闭环能力：
- 快速判断来源健康状态
- 快速查看最近失败原因
- 快速跳转异常任务与错误详情
- 一键重试（复用既有手动抓取链路）

## 2. 健康度分级

健康状态分为：
- `normal`（正常）
- `warning`（警告）
- `critical`（异常）

Phase-2 第7步起，阈值改为可配置，不再硬编码。

### 2.1 最小规则（可配置）

关键阈值：
- `recent_error_warning_threshold`
- `recent_error_critical_threshold`
- `consecutive_failure_warning_threshold`
- `consecutive_failure_critical_threshold`
- `partial_warning_enabled`

默认值：
- `recent_error_warning_threshold = 3`
- `recent_error_critical_threshold = 6`
- `consecutive_failure_warning_threshold = 1`
- `consecutive_failure_critical_threshold = 1`
- `partial_warning_enabled = true`

判定顺序（简化）：
1. 达到任一 critical 阈值 -> `critical`
2. 达到任一 warning 阈值 -> `warning`
3. 最近任务 `partial` 且 `partial_warning_enabled=true` -> `warning`
4. 最近任务 `succeeded` -> `normal`
5. 其余 -> `warning`

## 3. 数据来源

健康度计算复用现有模型：
- `source_site`
- `crawl_job`
- `crawl_error`

最近失败原因摘要优先级：
1. 最近 `crawl_error.error_message`
2. 最近失败/部分成功 `crawl_job.message`
3. 最近一次 `crawl_job.message`

## 4. 页面增强

新增健康规则配置页：
- `/admin/settings/health-rules`
- 可修改阈值并立即生效

## 4.1 `/admin/source-sites`

新增/增强：
- 健康状态（正常/警告/异常）
- 最近抓取结果
- 最近失败原因摘要
- 快速入口：
  - 查看任务（异常视图）
  - 查看错误
  - 立即重试（复用现有手动抓取）
- 新增最小运营摘要（最近24小时口径）：
  - 今日抓取次数
  - 今日成功次数
  - 今日失败次数
  - 今日新增公告数
  - 最近一次重试结果
- 新增“导出运营日报”入口：
  - `GET /reports/source-ops.xlsx?recent_hours=24`

## 4.2 `/admin/sources/{code}`

新增“运行健康摘要”模块：
- 最近一次抓取状态
- 最近一次抓取时间
- 最近一次新增数
- 最近一次错误数
- 最近7天抓取次数
- 最近7天失败次数
- 最近7天错误次数
- 最近失败原因摘要
- 一键重试入口
- 新增运营摘要字段（最近24小时口径）：
  - `today_crawl_job_count`
  - `today_success_count`
  - `today_failed_count`
  - `today_partial_count`
  - `today_new_notice_count`
  - `last_error_message`
  - `last_retry_status`
  - `last_job_status`
  - `last_job_finished_at`
- 页面可按来源导出运营日报：
  - `/reports/source-ops.xlsx?recent_hours=24&source_code={code}`

## 4.3 `/admin/crawl-jobs`

新增业务化异常筛选：
- 仅看异常（`failed + partial`）
- 仅看今日失败
- 仅看 partial

## 4.4 `/admin/crawl-errors`

新增“最近失败原因”来源聚合视图（近7天）：
- 按来源展示错误数与最近错误摘要
- 可直接跳转错误详情页

## 5. 最小辅助 API

新增：
- `GET /sources/{code}/health`
- `GET /settings/health-rules`
- `PATCH /settings/health-rules`

返回核心字段：
- `health_status`
- `health_status_label`
- `latest_job_status`
- `latest_job_started_at`
- `latest_notices_upserted`
- `latest_error_count`
- `recent_7d_job_count`
- `recent_7d_failed_count`
- `recent_7d_error_count`
- `latest_failure_reason`

## 6. 一键重试

一键重试入口位于：
- `/admin/source-sites`
- `/admin/sources/{code}`

实现方式：
- 复用 `POST /admin/sources/{code}/crawl-jobs`
- 使用 `default_max_pages` 作为默认参数
- 提交后跳转到对应 `crawl_job` 详情页

## 7. 实现落点

- 健康服务：`app/services/source_health_service.py`
- 规则配置服务：`app/services/health_rule_service.py`
- 规则配置文档：`docs/health-rule-config.md`
- 运营摘要服务：`app/services/source_ops_service.py`
- 来源页面：
  - `app/api/endpoints/admin_sources.py`
  - `app/templates/admin/source_sites_list.html`
  - `app/templates/admin/source_detail.html`
- 异常筛选页面：
  - `app/api/endpoints/admin_crawl_jobs.py`
  - `app/templates/admin/crawl_jobs_list.html`
  - `app/api/endpoints/admin_crawl_errors.py`
  - `app/templates/admin/crawl_errors_list.html`
- 健康 API：`app/api/endpoints/sources.py`
