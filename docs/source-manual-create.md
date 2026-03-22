# Source Manual Create（来源手动新增）

## 1. 背景

Phase-3 第1步支持在后台手动新增来源网站，不再依赖 seed 初始化。

## 2. 页面入口

- 来源列表：`/admin/source-sites`
- 新增页面：`/admin/sources/new`

在来源列表页点击“新增来源网站”进入表单。

页面会区分两种模式：

- A. 仅登记来源：保存来源信息，不代表可抓取。
- B. 已接入可抓来源：`source_code` 命中已接入清单（如 `anhui_ggzy_zfcg`、`ggzy_gov_cn_deal`）时可直接创建抓取任务。

若来源未接入 spider/parser，页面会明确提示：

- `仅保存来源信息，尚未接入抓取逻辑`

## 3. 表单字段

必填：
- `source_code`（唯一）
- `source_name`
- `official_url`
- `list_url`

可配置：
- `is_active`
- `schedule_enabled`
- `schedule_days`（仅允许 `1/2/3/7`）
- `crawl_interval_minutes`（正整数）
- `default_max_pages`（可选，空值时使用系统默认）
- `remark`（可选）

## 4. 校验规则

- `source_code`：必填，且唯一
- `source_name`：必填
- `official_url`：必填，需符合基本 URL 格式
- `list_url`：必填，需符合基本 URL 格式
- `schedule_days`：必须在 `1/2/3/7`
- `crawl_interval_minutes`：必须为正整数
- `default_max_pages`：如填写则必须为正整数

提交成功后：
- 重定向至 `/admin/source-sites`
- 页面提示“新增成功”
- 新来源立即在来源列表可见

## 5. API（可复用）

新增来源接口：
- `POST /sources`

请求示例：

```json
{
  "source_code": "manual_new_source",
  "source_name": "Manual New Source",
  "official_url": "https://manual-new-source.example.com/",
  "list_url": "https://manual-new-source.example.com/list",
  "remark": "phase3 manual create",
  "is_active": true,
  "schedule_enabled": true,
  "schedule_days": 3,
  "crawl_interval_minutes": 180,
  "default_max_pages": 6
}
```

常见响应：
- `201`：创建成功
- `409`：`source_code` 冲突（已存在）
- `422`：请求体字段校验失败

## 6. 实现落点

- 页面路由：`app/api/endpoints/admin_sources.py`
- API 路由：`app/api/endpoints/sources.py`
- 服务层：`app/services/source_site_service.py`
- 仓储层：`app/repositories/source_site_repository.py`
- 模板：
  - `app/templates/admin/source_sites_list.html`
  - `app/templates/admin/source_new.html`
