# Notice Export（第一期公告导出）

第一期与 Phase-2 第4步补齐公告导出能力，便于业务侧做离线校验与筛选分析。

## 1. 接口列表

- `GET /notices/export.csv`
- `GET /notices/export.json`
- `GET /notices/export.xlsx`

## 2. 筛选与排序

导出接口复用 `GET /notices` 的筛选参数：
- `keyword`
- `source_code`
- `notice_type`
- `region`
- `recent_hours`

排序固定为：
- `published_at` 倒序
- `id` 倒序
- `published_at` 为空的记录排在最后

## 3. 导出字段

最小导出字段：
- `id`
- `source_code`
- `title`
- `notice_type`
- `issuer`
- `region`
- `published_at`
- `deadline_at`
- `budget_amount`
- `current_version_id`

## 4. 返回类型

- `GET /notices/export.csv` 返回 `text/csv`
- `GET /notices/export.json` 返回 `application/json`
- `GET /notices/export.xlsx` 返回 `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`

## 5. 管理页入口

页面：`/admin/notices`

列表页新增：
- 导出 CSV
- 导出 JSON
- 导出 Excel

入口会保留当前筛选条件并透传到导出接口。

## 6. 示例

```bash
curl "http://127.0.0.1:8000/notices/export.csv?keyword=低压&source_code=anhui_ggzy_zfcg&notice_type=announcement&region=合肥"
```

```bash
curl "http://127.0.0.1:8000/notices/export.json?keyword=低压&source_code=anhui_ggzy_zfcg&notice_type=announcement&region=合肥"
```

```bash
curl -L "http://127.0.0.1:8000/notices/export.xlsx?keyword=低压&source_code=anhui_ggzy_zfcg&notice_type=announcement&region=合肥&recent_hours=24" -o notices.xlsx
```

## 7. 实现落点

- 路由：`app/api/endpoints/notices.py`
- 服务：`app/services/notice_query_service.py`
- 仓储：`app/repositories/notice_repository.py`
- 管理页：
  - `app/api/endpoints/admin_notices.py`
  - `app/templates/admin/notices_list.html`
- 测试：
  - `tests/test_notice_api.py`
  - `tests/test_notice_admin_pages.py`

工作台说明见：`docs/notice-workbench.md`
