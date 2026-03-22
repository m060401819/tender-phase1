# Phase-1 Runbook（本地演示与交付操作手册）

本文档用于把当前 Phase-1 项目以“可交付、可演示、可接手”的方式跑通。

## 1. 本地启动步骤

### 1.1 前置条件

- Python `3.12`
- Docker / Docker Compose
- 可用端口：`8000`（FastAPI）、`5432`（PostgreSQL）

### 1.2 一键启动（唯一推荐方式）

```bash
./scripts/dev_up.sh
```

脚本会自动完成：
1. 启动 `postgres` + `app`
2. 等待 Postgres 可连接
3. 执行 `alembic upgrade head`
4. 执行 `python scripts/seed_sources.py --demo`
5. 启动 `uvicorn app.main:app --host 0.0.0.0 --port 8000`
6. 等待 `/healthz` 就绪

### 1.3 健康检查

```bash
curl "http://127.0.0.1:8000/healthz"
```

预期返回：

```json
{"status":"ok","service":"tender-phase1"}
```

## 2. 数据库迁移步骤

### 2.1 首次初始化

```bash
alembic upgrade head
```

### 2.2 查看当前版本

```bash
alembic current
```

### 2.3 回滚一步（需要时）

```bash
alembic downgrade -1
```

### 2.4 Phase-3 收口迁移（必须）

分页抓全 + 自动去重 + 来源扩展依赖以下 revision：
- `20260320_0006`（`add source dedup keys and crawl quality stats`）
- `20260320_0007`（`phase3 product closure fields`）
- 文件：
  - `alembic/versions/20260320_0006_add_source_dedup_and_crawl_stats.py`
  - `alembic/versions/20260320_0007_phase3_product_closure.py`

执行方式：

```bash
alembic upgrade head
alembic current
```

`alembic current` 需包含 `20260320_0007`，否则管理页可能因为缺列而 500。

## 3. 运行真实样板源抓取步骤

样板源：`anhui_ggzy_zfcg`（安徽省公共资源交易监管网-政府采购）

### 3.1 最小抓取（不入库）

```bash
cd crawler
scrapy crawl anhui_ggzy_zfcg -a max_pages=3
```

结果：
- 原始页面归档：`data/raw/`
- 结构化输出：`data/staging/*.jsonl`

### 3.2 入库抓取（推荐演示）

```bash
cd crawler
CRAWLER_WRITER_BACKEND=sqlalchemy \
CRAWLER_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/tender_phase1 \
scrapy crawl anhui_ggzy_zfcg -a max_pages=3
```

### 3.3 通过来源接口触发抓取（可选）

```bash
curl -X POST "http://127.0.0.1:8000/sources/anhui_ggzy_zfcg/crawl-jobs" \
  -H "Content-Type: application/json" \
  -d '{"max_pages": 50, "triggered_by": "runbook"}'
```

### 3.4 检查采集完整性与重复抑制（Phase-3 第2步）

建议先跑 `max_pages=2` 或 `max_pages=3`：

```bash
python scripts/run_crawl_job.py \
  --spider anhui_ggzy_zfcg \
  --source-code anhui_ggzy_zfcg \
  --job-type manual \
  --writer-backend sqlalchemy \
  --spider-arg max_pages=3 \
  --spider-arg stop_after_consecutive_empty_pages=2 \
  --spider-arg dedup_within_run=true
```

然后在任务详情（`/admin/crawl-jobs/{id}`）重点查看：
- `list_items_seen`：列表页看到的条目总数
- `list_items_unique`：运行内唯一列表项数
- `list_items_source_duplicates_skipped`：列表重复跳过数
- `detail_pages_fetched`：实际进入详情抓取数
- `source_duplicates_suppressed`：历史重复输入抑制数

预期：
- `list_items_unique <= list_items_seen`
- 若源站存在重复，`list_items_source_duplicates_skipped` 或 `source_duplicates_suppressed` > 0
- `/admin/notices` 不应被同源重复列表项污染

### 3.5 全国平台抓取验证（ggzy_gov_cn_deal）

先执行一次 manual：

```bash
python scripts/run_crawl_job.py \
  --spider ggzy_gov_cn_deal \
  --source-code ggzy_gov_cn_deal \
  --job-type manual \
  --writer-backend sqlalchemy \
  --spider-arg max_pages=5
```

再执行同样命令一次，验证源级去重统计提升（`dedup_skipped` 应增长）。

任务详情重点关注：

- `pages_scraped`
- `list_seen`
- `list_unique`
- `raw_documents_written`
- `notices_written`
- `dedup_skipped`
- `failure_reason`

## 4. 访问路径（演示入口）

### 4.1 API 路径

- 健康检查：`GET /healthz`
- OpenAPI：`GET /docs`
- 来源：
  - `GET /sources`
  - `GET /sources/{code}`
  - `PATCH /sources/{code}`
  - `POST /sources/{code}/crawl-jobs`
- 抓取任务：
  - `GET /crawl-jobs`
  - `GET /crawl-jobs/{id}`
- 公告：
  - `GET /notices`
  - `GET /notices/{id}`
  - `GET /notices/export.csv`
  - `GET /notices/export.json`
- 原始文档：
  - `GET /raw-documents`
  - `GET /raw-documents/{id}`
- 错误事件：
  - `GET /crawl-errors`
  - `GET /crawl-errors/{id}`
- 统计总览：
  - `GET /stats/overview`

### 4.2 管理页面路径

- 总览：`/admin/home`、`/admin/dashboard`
- 来源运营：`/admin/source-sites`
- 来源：`/admin/sources`
- 抓取任务：`/admin/crawl-jobs`
- 公告：`/admin/notices`
- 原始文档：`/admin/raw-documents`
- 错误事件：`/admin/crawl-errors`

### 4.3 从后台手动抓取

1. 打开 `/admin/source-sites`
2. 点击某个来源行里的“手动抓取”
3. 系统会创建一个新的 `manual` 抓取任务（`triggered_by=admin_ui`）
4. 自动跳转到 `/admin/crawl-jobs/{job_id}` 查看执行状态（如无详情路由则回退到 `/admin/crawl-jobs?source_code={code}`）

## 5. 公告导出 CSV / JSON

### 5.1 导出 CSV

```bash
curl "http://127.0.0.1:8000/notices/export.csv?keyword=低压&source_code=anhui_ggzy_zfcg&notice_type=announcement&region=合肥"
```

### 5.2 导出 JSON

```bash
curl "http://127.0.0.1:8000/notices/export.json?keyword=低压&source_code=anhui_ggzy_zfcg&notice_type=announcement&region=合肥"
```

说明：导出复用 `/notices` 的筛选参数，排序固定为 `published_at` 倒序。

## 6. 常见问题排查

### 6.1 数据库未启动

现象：连接失败、`Connection refused`。

排查：
```bash
docker compose ps
```

修复：
```bash
docker compose up -d postgres
```

### 6.2 迁移未执行

现象：
- 接口报错 `relation "..." does not exist`
- 或 `/admin/home` 500，traceback 含 `column crawl_job.list_items_seen does not exist`

快速定位（必须看 traceback，不要猜）：

```bash
curl -i "http://127.0.0.1:8000/admin/home"
# 同时观察 uvicorn 终端输出 traceback
```

常见栈位置：
- `app/api/endpoints/admin_dashboard.py`
- `app/services/stats_service.py`
- `app/repositories/stats_repository.py`

修复：
```bash
alembic upgrade head
alembic current
```

说明：
- Dashboard 已做降级容错。即使统计查询异常，也会返回 200 并展示默认值/告警提示。
- 但根因仍应通过迁移对齐修复（尤其是 Phase-3 第2步字段）。

### 6.3 端口占用

现象：`Address already in use`。

排查：
```bash
lsof -i :8000
lsof -i :5432
```

处理：
- 关闭占用进程，或
- 改用其他端口启动（例如 `uvicorn ... --port 8001`）

### 6.4 Spider 无输出或无入库

常见原因与处理：
- 未在 `crawler/` 目录执行：先 `cd crawler`
- 未设置 DB writer：确认 `CRAWLER_WRITER_BACKEND=sqlalchemy`
- 未配置数据库 URL：确认 `CRAWLER_DATABASE_URL` 可连接
- `max_pages` 太小或过滤条件导致命中少：增大 `max_pages` 重试

### 6.5 API 有数据但管理页为空

检查是否加了筛选条件：
- 清空 `/admin/notices` 或 `/admin/crawl-jobs` 页面上的筛选项后重试

### 6.6 来源页为空或 source_count=0

常见原因：尚未初始化来源。

修复：
```bash
python scripts/seed_sources.py --demo
```

验证：
```bash
curl "http://127.0.0.1:8000/sources"
```

## 7. 演示建议顺序（5-10 分钟）

1. 执行来源初始化：`python scripts/seed_sources.py --demo`
2. `/healthz` 验证服务可用
3. 打开 `/admin/home`、`/admin/source-sites` 确认来源已可见
4. 运行一次样板源抓取（入库）
5. 打开 `/admin/crawl-jobs` 看任务记录
   - 在任务详情确认 `list_items_seen / list_items_unique / source duplicate` 统计
6. 打开 `/admin/notices` 看公告，并演示导出 CSV / JSON
7. 打开 `/admin/raw-documents`、`/admin/crawl-errors` 查看原文与错误事件
8. 打开 `/admin/dashboard` 演示总览
