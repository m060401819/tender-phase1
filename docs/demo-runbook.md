# Demo Runbook（Phase-2 第8步：真实来源初始化与演示闭环）

本手册用于让新同事按文档完成一次“可见来源 + 可触发抓取 + 可验证结果”的本地演示。

## 1. 一键演示流程（推荐）

1. 启动 PostgreSQL：

```bash
docker compose up -d postgres
```

2. 执行数据库迁移：

```bash
alembic upgrade head
```

3. 初始化真实样板来源（幂等）：

```bash
APP_ENV=dev python scripts/seed_sources.py --demo
```

该步骤仅用于演示/开发环境，生产环境不要执行 demo seed。

4. 启动 FastAPI：

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

5. 打开以下页面确认来源已可见：
- `/healthz`
- `/docs`
- `/admin/home`
- `/admin/source-sites`
- `/admin/crawl-jobs`
- `/admin/notices`

6. 触发一次样板抓取（二选一）：

方式 A（命令行）：

```bash
python scripts/run_crawl_job.py \
  --spider anhui_ggzy_zfcg \
  --source-code anhui_ggzy_zfcg \
  --job-type manual \
  --writer-backend sqlalchemy \
  --spider-arg max_pages=1
```

方式 B（后台入口）：
- 打开 `/admin/source-sites`
- 找到 `anhui_ggzy_zfcg`
- 点击“立即重试”（手动触发抓取）

## 2. 演示成功判定

抓取后可在页面观察：
- `/admin/source-sites`：来源、健康度、最近新增、导出入口
- `/admin/crawl-jobs`：出现新任务记录（至少有一条）
- `/admin/notices`：若站点返回公告，出现业务表格记录
- `/admin/raw-documents`：若成功归档，出现原始文档记录
- `/admin/crawl-errors`：若站点异常或解析失败，可见错误记录
- `/reports/source-ops.xlsx`：可导出来源运营日报

最小闭环要求：
- 即使外部站点临时波动导致 0 公告，也应至少看到 `crawl_job` 任务记录。

## 3. 外部站点波动时的观察路径

若真实站点短时异常（超时、反爬、无返回）：
- 先看 `/admin/crawl-jobs` 任务状态与 message
- 再看 `/admin/crawl-errors` 具体错误
- 在 `/admin/source-sites` 查看来源健康度是否降级
- 必要时在 `/admin/crawl-jobs` 使用单次重试闭环

## 4. 幂等说明

`APP_ENV=dev python scripts/seed_sources.py --demo` 可重复执行：
- 已存在 `anhui_ggzy_zfcg` 时执行更新
- 不会插入重复 `source_code`
