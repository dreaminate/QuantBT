<!-- 【开发os级别·模板】勿改本文件。开新机/新身份:复制到 log/{developer_id}/log.md,删本注释。
     log = 追加型滚动日志,最新在上。**条目格式是 build_log_index.py 的解析契约**:
     标题行必须是 `## YYYY-MM-DD-HHMM 一句话结论`(以日期开头,否则统一索引抓不到)。
     体量纪律:log.md 只留当月;跨月条目由 `os.py log` 自动滚动到 log/{id}/archive/YYYY-MM.md
     (索引脚本天然覆盖归档文件,历史不丢)。别把整个 session 压成一行——一条 = 标题行 + ≤5 行要点。 -->
# LOG · <developer_id> 滚动日志（追加型 · 最新在上 · 当月）

> 每 session 末落一条(推荐 `python dev/scripts/os.py log "<一句话>"`,格式/滚动自动合规)。
> 查历史:`python dev/scripts/build_log_index.py`(全员统一索引,含 archive/)→ 按 文件:行 读原文。

## YYYY-MM-DD-HHMM <一句话结论:干成/干砸了什么>
- 做了什么(1-3 行,落到文件/命令/测试)
- 卡在哪/踩了什么坑(没有就省略)
- 交接给下个 session 的第一个动作
