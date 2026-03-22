# 全国公共资源交易平台（政府采购）来源说明

来源代码：`ggzy_gov_cn_deal`

- Spider：`crawler/tender_crawler/spiders/ggzy_gov_cn_deal_spider.py`
- Parser：`crawler/tender_crawler/parsers/ggzy_gov_cn_deal_parser.py`
- 入口页：`https://www.ggzy.gov.cn/deal/dealList.html?HEADER_DEAL_TYPE=02`
- 列表接口：`POST /information/pubTradingInfo/getTradList`

## 来源特点

- 该站点是全国聚合平台，单条记录通常带有 `provinceText / transactionSourcesPlatformText / informationTypeText / url`。
- 列表接口可能在特定条件下返回验证码挑战（`code=829`）。
- 当前实现先抓“无验证码可直取数据”，不做验证码破解。

## 列表页结构与提取字段

每条列表记录最少提取并写入：

- `title`
- `published_at`（按日期标准化到 UTC 00:00:00）
- `province`
- `source_platform / issuer`
- `notice_type`
- `detail_url`

实现策略：

- 列表页先写 `raw_document`（`role=list`），记录 `page_item_count/new_unique_item_count/page_source_duplicates_skipped`。
- 每条唯一列表记录先写“草稿公告”（`tender_notice + notice_version`），保证即使详情不可抓也不会整批为 0。
- 能进入详情时继续抓取并写入详情级 `raw_document`（`role=detail`），并尝试补充正文与附件。

## 去重策略（源级）

本来源单独启用源级去重，优先级如下：

1. `detail_url` 归一化后去重（优先）。
2. 若 `detail_url` 缺失或不稳定，使用组合键：
   `source_code + province + source_platform + normalized_title + published_date`。

`normalized_title` 标准化规则：

- 全角/半角统一（NFKC）
- 连续空白折叠
- 去掉明显无意义尾缀（如常见“公告/公示/通知”尾巴）

去重统计进入任务指标：

- `list_items_source_duplicates_skipped`
- `dedup_skipped`（详情页展示口径：列表跳过 + 入库抑制）

## 当前限制

- 不包含验证码破解能力；当接口返回验证码挑战时，任务会记录明确失败原因。
- 部分详情页可能跳转到外部平台或受访问策略影响，当前保证“列表级数据可落库”，详情增强按可达性补充。
