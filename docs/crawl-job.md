# Crawl Job（第一期任务管理）

本文档说明第一期 `crawl_job` 的最小可用工作流：创建任务、运行抓取、回传统计、结束状态。

## 1. 任务类型（job_type）

- `manual`：手动触发（CLI/运维执行）
- `scheduled`：计划任务触发（后续调度器可复用）
- `backfill`：历史数据回补

## 2. 任务状态（status）

- `pending`：已创建，待执行
- `running`：执行中
- `succeeded`：执行完成且无错误
- `failed`：执行失败（如 spider 进程非 0 退出）
- `partial`：执行完成但存在错误事件（`error_count > 0`）

## 3. 状态流转

第一期最小流转：

1. `pending -> running`
2. `running -> succeeded`
3. `running -> partial`
4. `running -> failed`
5. 允许 `pending -> failed`（例如启动前校验失败）

`succeeded / failed / partial` 为终态，不再继续流转。

## 4. 统计字段定义

`crawl_job` 在执行期间累计以下计数：

- `pages_fetched`：抓取页面计数（按 `RawDocumentItem` 写入次数）
- `documents_saved`：原始文档归档/写库计数（按 `raw_document` upsert 次数）
- `notices_upserted`：公告快照 upsert 次数（按 `tender_notice` 写入次数）
- `deduplicated_count`：去重命中次数（URL/内容/公告归并/版本去重/附件 URL 去重）
- `error_count`：错误事件次数（按 `crawl_error` 写入次数）

## 5. 代码落点

- 服务层：`app/services/crawl_job_service.py`
  - 创建任务：`create_job(...)`
  - 开始任务：`start_job(...)`
  - 累计统计：`record_stats(...)` / `record_stats_in_session(...)`
  - 结束任务：`finish_job(...)`
- writer 回传统计：`crawler/tender_crawler/writers/sqlalchemy_writer.py`
- 手动触发 CLI：`scripts/run_crawl_job.py`

## 6. 最小执行流程（CLI）

```bash
python scripts/run_crawl_job.py \
  --spider anhui_ggzy_zfcg \
  --job-type manual \
  --writer-backend sqlalchemy \
  --spider-arg max_pages=1
```

该命令会自动：

1. 创建 `crawl_job`（`pending`）
2. 切换为 `running`
3. 启动 spider，并注入 `-a crawl_job_id=<id>`
4. writer 在写入过程中回传统计
5. 结束时自动写入 `succeeded / partial / failed`

## 7. 校验建议

执行完成后可查询：

```sql
SELECT
  id, job_type, status, started_at, finished_at,
  pages_fetched, documents_saved, notices_upserted, deduplicated_count, error_count
FROM crawl_job
ORDER BY id DESC
LIMIT 10;
```

接口查询说明见：`docs/crawl-job-api.md`。
