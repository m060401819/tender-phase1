# Retry And Ops Report（Phase-2 第6步）

## 1. 目标

在“发现异常”后提供最小闭环能力：
- 异常任务支持单次人工重试
- 在任务页/错误页可看到重试结果
- 在来源页可查看最小运营摘要
- 支持导出来源运营日报（Excel）

## 2. 新增与扩展接口

- `POST /crawl-jobs/{job_id}/retry`
- `GET /reports/source-ops.xlsx`

## 3. 异常任务重试规则

`POST /crawl-jobs/{job_id}/retry`：
- 仅允许 `failed` 或 `partial` 任务重试
- 原任务不存在返回 `404`
- 状态不符合或已重试返回 `400`
- 每个异常任务仅允许单次人工重试
- 重试后创建新任务：
  - `job_type = manual_retry`
  - `retry_of_job_id = 原任务 id`
- 返回新任务摘要、执行命令和返回码

## 4. 页面增强

## 4.1 `/admin/crawl-jobs`

- `failed/partial` 且未重试任务显示“重试”按钮
- 已重试任务显示“已重试”标签与新任务链接
- 详情页展示重试关系字段，并提供“上次失败 vs 本次重试”最小对比

## 4.2 `/admin/crawl-errors`

- 来源聚合摘要中展示“最近重试结果”
- 错误详情页展示该来源最近一次重试状态与任务链接（若存在）

## 4.3 `/admin/source-sites` 与 `/admin/sources/{code}`

- 来源列表增加运营摘要字段：
  - 今日抓取次数
  - 今日成功/失败次数
  - 今日新增公告数
  - 最近一次重试结果
- 来源列表页增加“导出运营日报”入口
- 来源详情页增加按来源导出入口

## 5. 来源运营日报导出

接口：`GET /reports/source-ops.xlsx`

参数：
- `recent_hours`：可选，默认 `24`，取值范围 `1-720`
- `source_code`：可选，仅导出指定来源

返回：
- `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- 文件名：`source-ops-report-YYYYMMDD.xlsx`

表头字段（第一行）：
- `source_code`
- `source_name`
- `official_url`
- `is_active`
- `schedule_enabled`
- `schedule_days`
- `today_crawl_job_count`
- `today_success_count`
- `today_failed_count`
- `today_partial_count`
- `today_new_notice_count`
- `last_job_status`
- `last_job_finished_at`
- `last_error_message`
- `last_retry_status`

## 6. 已知限制

- 当前只支持单次人工重试，不包含自动多轮重试策略
- 调度仍为单进程本地版，不是分布式调度
- 不包含 AI 匹配、企业资质库、投标文件生成
