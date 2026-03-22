# Notice Workbench（Phase-3 第1步）

## 1. 目标

将 `/admin/notices` 固化为业务日常使用的“招标信息汇总工作台”，重点解决：
- 默认去重展示
- 业务筛选
- 排序与导出一致性
- 重复项/版本可追溯

范围外（本步不做）：
- AI 匹配
- 企业资质库
- 投标文件生成

## 2. 页面入口

- 工作台：`/admin/notices`
- 公告详情：`/admin/notices/{id}`

## 3. 默认去重规则

默认 `dedup=true`，列表按业务键聚合展示最新一条：
- 优先使用 `tender_notice.dedup_hash`
- 若 `dedup_hash` 为空，回退稳定键：
  - `source_site_id + external_id + project_code + title`

说明：
- 工作台默认展示“去重后的公告汇总”
- 可用 `dedup=false` 查看全部记录

## 4. 筛选项

工作台顶部筛选支持：
- `keyword`（标题/发布方/地区）
- `source_code`
- `notice_type`
- `region`
- `recent_hours`
- `date_from`
- `date_to`
- `dedup`

示例：
- 仅看最近24小时新增：`/admin/notices?recent_hours=24`
- 按来源筛选：`/admin/notices?source_code=anhui_ggzy_zfcg`

## 5. 排序项

支持参数：
- `sort_by`：`published_at | deadline_at | budget_amount | source_name`
- `sort_order`：`asc | desc`

默认：
- `sort_by=published_at`
- `sort_order=desc`

示例：
- `GET /admin/notices?sort_by=published_at&sort_order=desc`
- `GET /admin/notices?sort_by=budget_amount&sort_order=desc`

## 6. 导出继承规则

导出接口：
- `GET /notices/export.csv`
- `GET /notices/export.json`
- `GET /notices/export.xlsx`

规则：
- 自动继承当前筛选、去重、排序条件
- 页面“重置”后导出会回到默认条件

## 7. 重复项/版本查看

列表每行提供“查看版本/重复项”入口，跳转公告详情页。

详情页展示：
- “该公告共 N 条版本/重复记录”
- 每条记录的：
  - 发布时间
  - 来源编码/来源名称
  - `detail_url`（若存在）

## 8. 实现落点

- 页面路由：`app/api/endpoints/admin_notices.py`
- API 路由：`app/api/endpoints/notices.py`
- 查询服务：`app/services/notice_query_service.py`
- 查询仓储：`app/repositories/notice_repository.py`
- 模板：
  - `app/templates/admin/notices_list.html`
  - `app/templates/admin/notices_detail.html`

## 9. 测试覆盖

- API：`tests/test_notice_api.py`
  - `dedup=true` 聚合结果
  - `sort_by/sort_order` 排序
- 页面：`tests/test_notice_admin_pages.py`
  - 默认去重展示
  - `keyword/source_code/recent_hours` 筛选
  - 排序与重复项入口
