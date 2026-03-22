# New Notice Indicator（Phase-2 第3步）

## 1. 目标

在不引入消息推送系统的前提下，为业务人员提供最小可用、可见的“新增公告提示”。

实现范围：
- 首页 `/admin/home` 增加醒目新增提示
- 来源运营页 `/admin/source-sites` 对有新增的来源高亮
- 公告页 `/admin/notices` 增加“最近新增（24小时）”快捷筛选
- 统一显示：今日新增、最近24小时新增
- 无新增时显示“暂无新增”

## 2. 统计口径

新增统计基于入库时间，按公告或版本任一新增即计入：
- `tender_notice.created_at`
- `notice_version.created_at`

最近 24 小时统计逻辑：
- 统计窗口：`now - 24h`
- 去重口径：按 `notice_id` 去重

今日统计逻辑：
- 统计窗口：当天 00:00:00（UTC）到当前时间
- 同样按 `notice_id` 去重

## 3. API 变化（兼容增强）

### 3.1 `GET /stats/overview`

新增字段：
- `today_new_notice_count`
- `recent_24h_new_notice_count`

### 3.2 `GET /notices`

新增可选筛选参数：
- `recent_hours`（最小可用场景使用 `24`）

筛选语义：
- 公告 `created_at` 在窗口内，或
- 公告任一 `notice_version.created_at` 在窗口内

### 3.3 导出接口

导出接口同步支持 `recent_hours`：
- `GET /notices/export.csv`
- `GET /notices/export.json`

用于从 `/admin/notices` 保留当前筛选条件导出。

## 4. 页面效果

### 4.1 首页 `/admin/home`

- 顶部提示区显示：
  - 今日新增 X 条
  - 最近24小时新增 X 条
- 无新增时显示“暂无新增”
- 提供快捷入口：`/admin/notices?recent_hours=24`

### 4.2 来源运营页 `/admin/source-sites`

- 页面顶部显示今日/24小时新增汇总
- `上次新增条数 > 0` 的来源行增加高亮（`row-hot`）
- 来源“上次新增条数”继续复用最近一次 `crawl_job.notices_upserted`
- 从未抓取来源显示 `新增 0 条`

### 4.3 公告页 `/admin/notices`

- 新增快捷入口：`最近新增（24小时）`
- 开启后进入 `recent_hours=24` 筛选模式并显示“最近24小时新增筛选中”
- 提供“查看全部”一键回到普通列表
- CSV/JSON 导出链接保留当前 `recent_hours` 条件

## 5. 已知限制

- 当前仅提供页面内提示，不包含站内消息中心/邮件/IM 推送
- 当前为单进程本地应用上下文，不包含分布式通知聚合能力
- `recent_hours` 当前主要用于最小 24 小时场景
