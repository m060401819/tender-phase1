# Phase-1 Runbook（本地演示与交付操作手册）

本文档用于把当前 Phase-1 项目以“可交付、可演示、可接手”的方式跑通。

## 1. 本地启动步骤

### 1.1 前置条件

- Python `3.12`
- Docker / Docker Compose
- 可用端口：`8000`（FastAPI）、`5432`（PostgreSQL）

### 1.2 安装依赖

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

### 1.3 启动数据库

```bash
docker compose up -d postgres
```

### 1.4 配置环境变量

```bash
cp .env.example .env
```

### 1.5 执行数据库迁移

```bash
alembic upgrade head
alembic current
```

### 1.6 启动 API 服务

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 1.7 健康检查

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

## 3. 运行真实样板源抓取步骤

样板源：`anhui_ggzy_zfcg`（安徽省公共资源交易监管网-政府采购）

### 3.1 最小抓取（不入库）

```bash
cd crawler
scrapy crawl anhui_ggzy_zfcg -a max_pages=1
```

结果：
- 原始页面归档：`data/raw/`
- 结构化输出：`data/staging/*.jsonl`

### 3.2 入库抓取（推荐演示）

```bash
cd crawler
CRAWLER_WRITER_BACKEND=sqlalchemy \
CRAWLER_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/tender_phase1 \
scrapy crawl anhui_ggzy_zfcg -a max_pages=1
```

### 3.3 通过来源接口触发抓取（可选）

```bash
curl -X POST "http://127.0.0.1:8000/sources/anhui_ggzy_zfcg/crawl-jobs" \
  -H "Content-Type: application/json" \
  -d '{"max_pages": 1, "triggered_by": "runbook"}'
```

## 4. 访问路径（演示入口）

### 4.1 API 路径

- 健康检查：`GET /healthz`
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

- 总览：`/admin/dashboard`
- 来源：`/admin/sources`
- 抓取任务：`/admin/crawl-jobs`
- 公告：`/admin/notices`
- 原始文档：`/admin/raw-documents`
- 错误事件：`/admin/crawl-errors`

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

现象：接口报错 `relation "..." does not exist`。

修复：
```bash
alembic upgrade head
alembic current
```

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

## 7. 演示建议顺序（5-10 分钟）

1. `/healthz` 验证服务可用
2. 运行一次样板源抓取（入库）
3. 打开 `/admin/crawl-jobs` 看任务记录
4. 打开 `/admin/notices` 看公告，并演示导出 CSV / JSON
5. 打开 `/admin/raw-documents`、`/admin/crawl-errors` 查看原文与错误事件
6. 打开 `/admin/dashboard` 演示总览
