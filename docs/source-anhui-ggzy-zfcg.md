# 安徽省公共资源交易监管网（政府采购）字段映射

来源：`https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1`a

Spider：`crawler/tender_crawler/spiders/anhui_ggzy_zfcg_spider.py`
Parser：`crawler/tender_crawler/parsers/anhui_ggzy_zfcg_parser.py`

## 1. 抓取链路与分页策略

1. 列表页：`GET /zfcg/list`
2. 详情页：`GET /zfcg/newDetail?guid=...`
3. 详情子接口（项目登记）：`POST /zfcg/newDetailSub` with `type=xmdj`
4. 详情子接口（公告正文）：`POST /zfcg/newDetailSub` with `type=bulletin`

说明：该来源的结构化正文与关键字段主要在 `type=bulletin` 返回内容中，项目补充字段在 `type=xmdj`。

分页抓取策略（Phase-3 第3步）：
- 列表页持续翻页，不再只抓固定小页数
- 优先按站点真实请求规律翻页：`POST /zfcg/list` + `currentPage`
- 下一页优先解析分页控件参数（如 `onclick="pagination(...)"`），避免仅依赖 UI 页码文本
- 每页记录分页日志：`current_page_no / page_url / page_item_count / new_unique_item_count`
- 运行内优先做列表去重，减少重复详情请求

停止条件：
- 列表页没有记录
- 当前页所有记录发布时间均早于 `backfill_year-01-01`
- 命中 `max_pages`（可选安全兜底）
- 连续 `stop_after_consecutive_no_new_pages` 页无有效新增（默认 `5`）
- 到达最后一页（无可用下一页控件）
- 页面异常时写入 `crawl_error` 后安全退出

可用 spider 参数：
- `backfill_year`（例如 `2026`，用于按年份回填）
- `max_pages`（可选安全兜底，不传表示仅依赖停止条件）
- `stop_after_consecutive_no_new_pages`（默认 `5`）
- `stop_after_consecutive_empty_pages`（兼容旧参数，等价于上述阈值）
- `dedup_within_run`（默认 `true`）
- `time`（可选，默认手动抓取为 `1`，回填模式自动切换为全量列表）

## 2. 字段映射（第一期）

- 项目名称：
  - 优先 `bulletin #title::text`
  - 其次 `xmdj` 表格中的 `采购项目名称`
  - 兜底列表项标题
- 来源网站：固定 `安徽省公共资源交易监管网`
- 列表页 URL：当前抓取列表页 `response.url`
- 详情页 URL：`/zfcg/newDetail?guid=...`
- 公告类型：由标题关键词推断
  - 含 `更正/变更/澄清/延期` -> `change`
  - 含 `中标/成交/结果/中选` -> `result`
  - 默认 `announcement`
- 发布时间：`#tsSpan::text`
- 截止时间：从正文中匹配 `提交响应文件截止时间/截止时间`
- 招标人/采购人：
  - 优先 `xmdj` 的 `采购人名称`
  - 其次正文 `采购人(信息) 名称`
- 地区：
  - 优先 `xmdj` 的 `采购项目地点`
  - 其次列表标题中 `【...】`
- 预算金额：
  - 优先正文 `预算金额`
  - 其次 `xmdj` 的 `预算金额`
  - 自动处理 `万元` 到元的换算
- 正文：`#content` 文本清洗后拼接

## 3. 入库挂接

- 原始页面归档：`raw_document`
  - 列表页、详情页、`xmdj`、`bulletin` 都会形成 `RawDocumentItem`
- 结构化公告：
  - `tender_notice`（当前公告快照）
  - `notice_version`（版本快照，`content_hash` 去重）
- 附件元数据：
  - 解析正文中的附件链接（文件后缀或“附件/下载”语义）
  - 相对链接统一转绝对链接，并做 URL 标准化
  - 记录 `file_name/file_url/url_hash/file_hash/mime_type/file_size_bytes/storage_uri/attachment_type`
  - 写入 `tender_attachment`
  - 自动关联 `tender_notice`、`notice_version`，若存在同 URL 的 `raw_document` 也会建立 `raw_document_id`
- 错误事件：
  - 抓取/解析错误写入 `crawl_error`

## 4. 去重策略（含源站重复抑制）

- URL 去重：`raw_document.url_hash = sha256(normalized_url)`
- 内容去重：`raw_document.content_hash` 与 `notice_version.content_hash`
- 公告去重：`tender_notice.dedup_hash = sha256(source_code + external_id + title + detail_url)`
- 附件去重：`tender_attachment.url_hash = sha256(normalized_file_url)`，同源同 URL upsert

源站重复抑制（Phase-3 收口版）：
- 运行内列表去重键：`source_list_item_fingerprint`
- 入库侧业务去重键：`dedup_key`
  - `sha256(normalized_title + published_date(day) + normalized_purchaser_or_publisher + normalized_budget_bucket + normalized_region)`
  - 当 `issuer/budget/region` 信号不足时，自动回退加入 `detail_locator` 避免误并
- 兼容字段：`source_duplicate_key`（用于详情定位级判重与旧链路兼容）
- 详情定位键：`source_duplicate_key`（优先 `external_id/detail_url`）
- 同 `dedup_key` 或同 `source_duplicate_key` 且 `content_hash` 一致时：
  - 判定为源站重复输入
  - 计入 `crawl_job.source_duplicates_suppressed`
  - 不新增重复 `tender_notice / notice_version`

版本更新边界：
- 同 `dedup_key` 但正文 `content_hash` 变化：
  - 视为真实版本更新
  - 继续创建新的 `notice_version`

## 5. 附件归档接口（第一期）

- `AttachmentArchivePipeline` 提供可插拔归档后端：
  - `noop`：默认，仅保留元数据写入
  - `local`：下载附件并归档到本地目录，回填 `storage_uri/file_hash/file_size_bytes/mime_type`
- 当前不做复杂文件内容解析，只做文件级元数据管理与归档预留。
