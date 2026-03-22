# Source Schedule（Phase-2 第2步：抓取周期与轻量调度）

## 1. 目标

在不改动既有手动抓取链路的前提下，为来源网站增加最小自动调度能力：
- 可配置启用/停用自动抓取
- 可配置固定周期（1/2/3/7 天）
- 自动触发时复用现有 `crawl_job` + spider 执行链
- 可查看下次抓取时间、上次计划抓取时间、最近调度结果

## 2. 模型字段

`source_site` 新增字段：
- `schedule_enabled: bool`
- `schedule_days: int`（仅允许 `1/2/3/7`）
- `last_scheduled_run_at: datetime | null`
- `next_scheduled_run_at: datetime | null`
- `last_schedule_status: str | null`（`succeeded/failed/partial/skipped`）

迁移文件：
- `alembic/versions/20260320_0003_add_source_schedule_fields.py`

## 3. API

### 3.1 GET /sources/{code}/schedule

返回：
- `source_code`
- `schedule_enabled`
- `schedule_days`
- `next_scheduled_run_at`
- `last_scheduled_run_at`
- `last_schedule_status`

### 3.2 PATCH /sources/{code}/schedule

请求体支持：

```json
{
  "schedule_enabled": true,
  "schedule_days": 2
}
```

规则：
- `schedule_days` 仅允许 `1/2/3/7`
- 不存在来源返回 `404`

保存后行为：
1. 更新来源调度配置
2. Web 进程先刷新数据库中的 `next_scheduled_run_at`
3. 若当前进程启用了嵌入式调度器，则立即同步内存 job（启用则注册/更新，停用则移除）
4. 独立 scheduler 进程会按刷新周期从数据库收敛配置变更

## 4. 页面

### 4.1 /admin/source-sites

新增列：
- 自动抓取
- 抓取周期
- 下次抓取时间
- 最近调度结果

并保留：
- 上次抓取时间
- 上次新增条数
- 手动抓取按钮

### 4.2 /admin/sources/{code}

新增“自动抓取配置”表单：
- 开关：是否启用自动抓取
- 周期：1/2/3/7 天
- 保存按钮

保存后：
- 页面提示“配置已更新”
- 详情页展示调度摘要（启用状态、周期、下次抓取、上次结果）

## 5. 调度行为（独立 scheduler 进程）

- Web 进程默认不在 FastAPI `lifespan` 中启动调度器；只有显式设置 `SOURCE_SCHEDULER_EMBEDDED_ENABLED=true` 时才会启用嵌入式模式
- 生产/多实例部署应启动独立调度进程：`python -m app.run_source_scheduler`
- 独立 scheduler 启动时会按数据库配置恢复任务，并注册一个周期性“数据库刷新 job”
- 数据库刷新 job 会：
  - 从 `source_site` 重新收敛启用状态、抓取周期、`next_scheduled_run_at`
  - 为新增/变更来源注册或更新调度任务
  - 清理数据库中已删除来源对应的陈旧 APScheduler job
- 自动调度触发时：
  - 创建 `job_type=scheduled` 的 `crawl_job`
  - 复用既有 spider 执行链
  - 更新 `last_scheduled_run_at`
  - 更新 `last_schedule_status`
  - 刷新 `next_scheduled_run_at`
- 若同来源已有 `pending/running` 任务，则本次计划抓取不会重复创建任务，并记录 `last_schedule_status=skipped`
- 当 `is_active=false` 或 `schedule_enabled=false` 时，不调度

实现入口：
- `app/main.py`（仅在显式开启时运行嵌入式调度器）
- `app/run_source_scheduler.py`（独立 scheduler 进程入口）
- `app/services/source_schedule_service.py`（调度注册/恢复/周期刷新/同步）

## 6. 已知限制

当前为**单独 scheduler 进程 + APScheduler 内存态 job**：
- 不含 Celery/Redis/RabbitMQ
- Web 多实例已不再重复启动调度器
- 若误部署多个 `scheduler` 副本，仍会重复恢复调度任务；此时需要额外的调度主节点、数据库 leader election 或分布式锁方案

## 7. 测试覆盖

- `tests/test_source_api.py`：调度配置 GET/PATCH、非法值、404
- `tests/test_source_admin_pages.py`：来源详情页调度表单展示与提交
- `tests/test_app_lifespan.py`：Web 默认不启动调度器、显式开启嵌入式模式时可正常启停
- `tests/test_source_schedule_service.py`：创建/更新/停用/启动恢复调度任务、数据库刷新收敛、删除来源清理陈旧 job、重复刷新不推迟 `next_run_time`
