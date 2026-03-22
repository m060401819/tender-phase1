# Source Admin（第一期来源管理与任务触发）

第一期新增最小来源管理能力，让系统可以查看 `source_site` 并手动触发一次抓取任务。

## 1. API 列表

- `GET /sources`
- `GET /sources/{code}`
- `PATCH /sources/{code}`
- `POST /sources/{code}/crawl-jobs`

## 2. GET /sources

返回来源列表，至少包含字段：
- `code`
- `name`
- `base_url`
- `official_url`
- `list_url`
- `is_active`
- `supports_js_render`
- `crawl_interval_minutes`

说明：按 `code` 升序返回。

## 3. GET /sources/{code}

返回单个来源详情（当前与列表字段一致，另含 `description` 与 `default_max_pages`）。

不存在时返回：

```json
{"detail":"source not found"}
```

## 4. PATCH /sources/{code}

用于更新来源最小运行配置，支持字段：
- `name`
- `official_url`
- `list_url`
- `description`
- `is_active`
- `supports_js_render`
- `crawl_interval_minutes`
- `default_max_pages`

请求体允许提交任意子集；成功返回更新后的来源对象；不存在返回 404。

## 5. POST /sources/{code}/crawl-jobs

请求体（最小）：

```json
{
  "max_pages": 1,
  "triggered_by": "api"
}
```

行为：
1. 校验来源是否存在
2. 创建 `manual` 类型 `crawl_job`
3. 将任务置为 `running`
4. 同步执行 spider（最小实现，不引入 Celery）
5. 按执行结果回写状态：
   - 进程返回码 `0`：`succeeded`（若累计错误则由 `crawl_job` 规则推导为 `partial`）
   - 非 `0`：`failed`

响应摘要：
- `source_code`
- `job`（`crawl_job` 核心字段）
- `return_code`
- `command`

## 6. 管理页面

- 列表页：`/admin/sources`
- 详情页：`/admin/sources/{code}`

详情页提供“编辑来源配置”表单，提交到：
- `POST /admin/sources/{code}/config`

保存后重定向回来源详情页并展示最新值。

详情页提供“触发一次抓取”表单（`max_pages`），提交后重定向到：
- `/admin/crawl-jobs/{id}`

## 7. 实现落点

- API 路由：`app/api/endpoints/sources.py`
- 管理页路由：`app/api/endpoints/admin_sources.py`
- 查询服务：`app/services/source_site_service.py`
- 触发服务：`app/services/source_crawl_trigger_service.py`
- 查询仓储：`app/repositories/source_site_repository.py`
- 模板：
  - `app/templates/admin/sources_list.html`
  - `app/templates/admin/source_detail.html`

## 8. 已覆盖测试

- `tests/test_source_api.py`
  - 来源列表/详情
  - 手动触发任务（成功/失败路径）
- `tests/test_source_admin_pages.py`
  - 来源页面展示
  - 配置更新与回显
  - 表单触发抓取与跳转

更多配置说明见：`docs/source-config.md`
