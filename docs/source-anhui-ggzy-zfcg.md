# 安徽省公共资源交易监管网（政府采购）字段映射

来源：`https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1`

Spider：`crawler/tender_crawler/spiders/anhui_ggzy_zfcg_spider.py`
Parser：`crawler/tender_crawler/parsers/anhui_ggzy_zfcg_parser.py`

## 1. 抓取链路

1. 列表页：`GET /zfcg/list`
2. 详情页：`GET /zfcg/newDetail?guid=...`
3. 详情子接口（项目登记）：`POST /zfcg/newDetailSub` with `type=xmdj`
4. 详情子接口（公告正文）：`POST /zfcg/newDetailSub` with `type=bulletin`

说明：该来源的结构化正文与关键字段主要在 `type=bulletin` 返回内容中，项目补充字段在 `type=xmdj`。

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

## 4. 去重策略

- URL 去重：`raw_document.url_hash = sha256(normalized_url)`
- 内容去重：`raw_document.content_hash` 与 `notice_version.content_hash`
- 公告去重：`tender_notice.dedup_hash = sha256(source_code + external_id + title + detail_url)`
- 附件去重：`tender_attachment.url_hash = sha256(normalized_file_url)`，同源同 URL upsert

## 5. 附件归档接口（第一期）

- `AttachmentArchivePipeline` 提供可插拔归档后端：
  - `noop`：默认，仅保留元数据写入
  - `local`：下载附件并归档到本地目录，回填 `storage_uri/file_hash/file_size_bytes/mime_type`
- 当前不做复杂文件内容解析，只做文件级元数据管理与归档预留。
