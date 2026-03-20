# Source Config（第一期来源配置增强）

第一期在来源管理能力中补齐最小可配置运行参数，仍聚焦信息采集与聚合，不涉及 AI 匹配、资质库匹配或投标文件生成。

## 1. 目标范围

`source_site` 在现有“查看 + 手动触发抓取”基础上，新增可编辑字段：
- `is_active`
- `crawl_interval_minutes`
- `supports_js_render`
- `default_max_pages`

## 2. API

### 2.1 PATCH /sources/{code}

请求体支持任意子集更新：

```json
{
  "is_active": true,
  "crawl_interval_minutes": 30,
  "supports_js_render": false,
  "default_max_pages": 5
}
```

规则：
- 仅允许上述四个字段
- `crawl_interval_minutes` 与 `default_max_pages` 必须 `>= 1`
- 来源不存在返回：

```json
{"detail":"source not found"}
```

返回：更新后的来源对象。

### 2.2 兼容性

以下接口保持不变并兼容：
- `GET /sources`
- `GET /sources/{code}`
- `POST /sources/{code}/crawl-jobs`

## 3. 管理页面

页面：`/admin/sources/{code}`

新增“编辑来源配置”表单：
- `is_active`（true/false）
- `supports_js_render`（true/false）
- `crawl_interval_minutes`
- `default_max_pages`

提交地址：`POST /admin/sources/{code}/config`

行为：
1. 更新来源配置
2. `303` 重定向回 `/admin/sources/{code}`
3. 详情页显示最新配置值

## 4. 实现落点

- 模型：`app/models/source_site.py`
- 迁移：`alembic/versions/20260320_0002_add_default_max_pages_to_source_site.py`
- API：`app/api/endpoints/sources.py`
- 管理页路由：`app/api/endpoints/admin_sources.py`
- 模板：`app/templates/admin/source_detail.html`

## 5. 测试

- `tests/test_source_api.py`
  - `PATCH /sources/{code}` 成功与 404
- `tests/test_source_admin_pages.py`
  - 配置表单渲染
  - 配置提交、重定向与数据库落库校验
