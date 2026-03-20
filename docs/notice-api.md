# Notice API（第一期公告检索与详情）

第一期基于 `tender_notice / notice_version / tender_attachment / source_site` 提供最小可用公告查询接口。

## 1. 接口列表

- `GET /notices`
- `GET /notices/{id}`
- `GET /notices/export.csv`
- `GET /notices/export.json`

## 2. GET /notices

### Query 参数

- `keyword`：关键词搜索（匹配 `title / issuer / region`，模糊匹配）
- `source_code`：来源筛选（精确匹配）
- `notice_type`：公告类型筛选（`announcement/change/result`）
- `region`：地区筛选（精确匹配）
- `limit`：分页大小，默认 `20`，范围 `1-200`
- `offset`：分页偏移，默认 `0`

### 排序规则

- 固定按 `published_at` 倒序
- 同时间按 `id` 倒序
- `published_at` 为空的记录排在最后

### 返回摘要字段

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

## 3. GET /notices/{id}

返回单条公告详情，包含：

1. `tender_notice` 主要字段
2. `current_version` 主要字段（若存在）
3. `versions` 历史版本列表（按 `version_no` 倒序）
4. 附件摘要列表（过滤 `is_deleted=true`）
5. 来源基本信息

说明：附件项包含 `notice_version_id`，可与 `versions[].id` 对应，用于页面按版本筛选附件。

`versions` 每项至少包含：
- `id`
- `version_no`
- `is_current`
- `notice_type`
- `published_at`
- `deadline_at`
- `content_hash`
- `raw_document_id`

如存在关联原文，补充：
- `raw_document.id`
- `raw_document.document_type`
- `raw_document.fetched_at`
- `raw_document.storage_uri`

不存在时返回：

```json
{"detail":"notice not found"}
```

## 4. 示例

```bash
curl "http://127.0.0.1:8000/notices?keyword=低压&source_code=anhui_ggzy_zfcg&notice_type=announcement&limit=20&offset=0"
```

```bash
curl "http://127.0.0.1:8000/notices/1"
```

导出示例：

```bash
curl "http://127.0.0.1:8000/notices/export.csv?keyword=低压&source_code=anhui_ggzy_zfcg&notice_type=announcement&region=合肥"
```

```bash
curl "http://127.0.0.1:8000/notices/export.json?keyword=低压&source_code=anhui_ggzy_zfcg&notice_type=announcement&region=合肥"
```

## 5. 实现落点

- 路由：`app/api/endpoints/notices.py`
- schema：`app/api/schemas/notice.py`
- repository：`app/repositories/notice_repository.py`
- service：`app/services/notice_query_service.py`
- 测试：`tests/test_notice_api.py`

导出能力说明见：`docs/notice-export.md`
