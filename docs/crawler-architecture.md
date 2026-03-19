# Crawler Architecture（Phase-1）

本文档说明第一期采集工程的目录职责与数据流，目标是支持多来源长期维护。

## 1. 目录职责

`crawler/tender_crawler/` 下核心模块：

- `spiders/`
  - 每个数据源一个独立 spider（如 `example_source_spider.py`、`anhui_ggzy_zfcg_spider.py`）
  - 只负责 crawling 编排（请求、分页、错误回调）
  - 不直接包含业务解析规则或数据库写入逻辑

- `parsers/`
  - 将页面内容转换为结构化公告字段
  - `BaseNoticeParser` 作为解析基类
  - 各来源 parser 继承基类扩展（如 `ExampleSourceParser`、`AnhuiGgzyZfcgParser`）

- `connectors/`
  - 动态页面连接器抽象
  - 提供 `PlaywrightConnector` 与 `PlaywrightFallbackConnector` 预留能力
  - 默认不启用复杂反爬，仅保留接口

- `writers/`
  - 写入层抽象，隔离持久化实现
  - 当前提供 `jsonl/noop/sqlalchemy` 后端
  - `sqlalchemy` 可直接写入 PostgreSQL phase-1 核心表

- `services/`
  - 写入层可复用领域逻辑
  - 当前包含 `DeduplicationService`：URL 标准化、哈希计算、公告归并键、公告类型规范化
  - `AttachmentArchiver`：附件下载与本地归档接口（可插拔）

- `items.py`
  - 统一定义采集层数据契约（raw_document / tender_notice / notice_version / tender_attachment / crawl_error）

- `pipelines.py`
  - `RawArchivePipeline`：原始页面归档（可挂接 `raw_document.storage_uri`）
  - `AttachmentArchivePipeline`：附件归档预处理（回填 `storage_uri/file_hash/mime_type/file_size_bytes`）
  - `WriterDispatchPipeline`：按 item_type 分发到 writers（可挂接公告与错误表）

- `settings.py`
  - 管理 pipeline 顺序、归档路径、writer backend、Playwright 开关等

## 2. 数据流（阶段分离）

1. Crawling（Spider）
- Spider 抓取页面，产出 `RawDocumentItem`
- Spider 调用 Parser 产出结构化项：`TenderNoticeItem` / `NoticeVersionItem` / `TenderAttachmentItem`
- 异常产出 `CrawlErrorItem`

2. Parsing（Parser）
- Parser 只做字段抽取与标准化，不做持久化
- 提供公告类型、发布时间、截止时间、地区、招标人、预算等基础字段入口

3. Writing（Pipeline + Writer）
- `RawArchivePipeline` 保存 HTML 与元数据文件
- `WriterDispatchPipeline` 根据 item_type 分流：
  - `raw_document` -> raw writer
  - `tender_notice` / `notice_version` / `tender_attachment` -> notice writer
  - `crawl_error` -> error writer
- `AttachmentArchivePipeline` 在附件写库前执行：
  - 预留下载接口，不改变 spider 对外运行方式
  - 支持 `noop/local` 两种归档后端
  - `local` 模式下载后回填 `storage_uri/file_hash/file_size_bytes/mime_type`
- `SqlAlchemyWriter` 在写入阶段统一执行：
  - URL 标准化 + `url_hash` 去重
  - 内容哈希去重
  - 公告归并（`external_id` > `detail_url` > `title`）
  - 版本去重与递增（相同内容不新增版本，内容变化新增版本）
  - 附件 URL 去重与 upsert，关联 `notice` / `notice_version` / `raw_document`

## 3. 与数据模型的挂接点

- `RawDocumentItem` 对应 `raw_document`
- `TenderNoticeItem` 对应 `tender_notice`
- `NoticeVersionItem` 对应 `notice_version`
- `TenderAttachmentItem` 对应 `tender_attachment`
- `CrawlErrorItem` 对应 `crawl_error`

当前已支持通过 `writers/sqlalchemy_writer.py` 进行 DB Upsert；新增来源时无需改写通用 pipeline。

去重与版本逻辑集中在：
- `tender_crawler/services/deduplication.py`
- `tender_crawler/writers/sqlalchemy_writer.py`

附件归档逻辑集中在：
- `tender_crawler/services/attachment_archive.py`
- `tender_crawler/pipelines.py::AttachmentArchivePipeline`

## 4. 扩展建议

新增来源时建议最小步骤：
1. 新建 `spiders/<source>_spider.py`（独立源）
2. 新建 `parsers/<source>_parser.py` 并继承 `BaseNoticeParser`
3. 复用现有 pipelines/writers
4. 增加该来源 parser/spider 的最小测试
