"""脊柱第 0 层 · honest-N 一本账 ledger 的【对抗式】测试。

验收标准（RULES §2 / 复核 00 §任务2）：不是「测函数跑通」，而是「种一个已知的坏，门
必须抓住，否则门是纸做的」。每条都种一个会让 honest-N 失真 / memoize 失效 / 账本被悄改的
坏，断言被抓。对应 spine 设计 03/05 §5 中属【一本账】职责的探针，外加对抗复核 wf_ada4a4e4
确认的 11 个发现各配一条回归（cross-theme 洗白 / UPSERT 改主题 / 并发重算 / 占位回填 /
软删陈旧 / 截断 / payload 读路径 / 坏 payload 行 / 集合背离 / 列覆盖 / update_fields）。
N_eff 聚类 / DSR-PBO gate 属 T-015，不在本测。
"""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import Mock

import pytest

from app.lineage import config_hash as id_config_hash
from app.lineage.ledger import (
    HONEST_N_DISCLOSURE,
    LEDGER_HWM_FILENAME,
    LEDGER_JSONL_FILENAME,
    Ledger,
    LedgerEntry,
)

GOAL = "theme_momentum"


def _entry(ledger_factor="rank(close)", goal=GOAL, **over):
    """构造一条 confirmatory backtest 条目（经 ids.config_hash 单一算法）。"""

    base = dict(
        factor=ledger_factor, params={"win": 5}, universe="csi300",
        dataset_version="ds_a", freq="1d", label="ret1",
        strategy_goal_ref=goal, kind="backtest", stage="confirmatory",
    )
    base.update(over)
    return LedgerEntry.create(**base)


# ── T-LED-1 memoize 命中：不重跑 + 不重复计 N（R8 同一本账，03-T8 / 05-T10）──────
def test_memoize_hit_no_recompute_no_double_count(tmp_path):
    led = Ledger(tmp_path)
    compute1 = Mock(return_value="result-ref-1")
    entry1, hit1 = led.memoize(_entry(), compute1)
    assert hit1 is False and compute1.call_count == 1 and entry1.result_ref == "result-ref-1"
    assert led.honest_n(GOAL) == 1

    compute2 = Mock(side_effect=RuntimeError("memoize 失效：缓存命中却重跑了 compute（门坏）"))
    entry2, hit2 = led.memoize(_entry(), compute2)
    assert hit2 is True, "同 config_hash 第二次应命中缓存"
    assert compute2.call_count == 0, "命中却重跑 compute → R8 同一本账被破坏（门坏）"
    assert entry2.result_ref == "result-ref-1"
    assert led.honest_n(GOAL) == 1, "memoize 命中却把 N +1 → honest-N 虚高（门坏）"


# ── T-LED-2 honest-N 不可改小：无 set_n / delete，谎报无门（03-T7，命门·硬）──────
def test_honest_n_no_set_n_no_delete_api(tmp_path):
    led = Ledger(tmp_path)
    for i in range(5):
        led.record_or_hit(_entry(params={"win": i}))
    assert led.honest_n(GOAL) == 5
    for forbidden in ("set_n", "set_honest_n", "delete", "remove", "reset", "decrement_n"):
        assert not hasattr(led, forbidden), f"账本暴露了 {forbidden} → honest-N 可被改小（门坏）"
    assert led.honest_n(GOAL) == 5


# ── T-LED-3 tombstone 不减 N + 文件行数只增（05-T12，防作弊·硬）──────────────────
def test_tombstone_does_not_reduce_n_appendonly(tmp_path):
    led = Ledger(tmp_path)
    hashes = [led.record_or_hit(_entry(params={"win": i}))[0].config_hash for i in range(3)]
    assert led.honest_n(GOAL) == 3
    jsonl = tmp_path / LEDGER_JSONL_FILENAME
    lines_before = len(jsonl.read_text().splitlines())

    led.tombstone(hashes[0], GOAL, reason="回测亏损，弃用")

    assert led.honest_n(GOAL) == 3, "tombstone 把 N 减小 → 可藏失败试验（门坏）"
    assert len(jsonl.read_text().splitlines()) > lines_before, "tombstone 应 append（行数只增）"
    assert led.get(hashes[0], GOAL).tombstone is True


# ── T-LED-4 config_hash 单一身份源：ledger 不自造第二套算法（00 §1.2-A 防回潮）────
def test_config_hash_is_single_source_no_second_algo(tmp_path):
    led = Ledger(tmp_path)
    e = _entry()
    expected = id_config_hash(
        factor="rank(close)", params={"win": 5}, universe="csi300",
        dataset_version="ds_a", freq="1d", label="ret1",
    )
    assert e.config_hash == expected, "ledger 的 config_hash 与 ids.config_hash 不符 → 双产方回潮（门坏）"
    assert e.entry_id == e.config_hash and e.config_hash.startswith("cfg_v1_")
    with pytest.raises(ValueError, match="entry_id"):
        LedgerEntry(
            entry_id="cfg_v1_fakefakefake0", config_hash=e.config_hash,
            strategy_goal_ref="g", dataset_version="ds_a", kind="backtest", stage="confirmatory",
        )


# ── T-LED-5 换装饰字段不刷 N（03-T9）；换 dataset_version 是新 trial（防刷 N）──────
def test_decorative_no_inflate_dataset_change_new_trial(tmp_path):
    led = Ledger(tmp_path)
    led.record_or_hit(_entry())
    for k in range(3):
        led.record_or_hit(_entry(params={"win": 5, "name": f"动量v{k}", "tags": ["x"], "note": "试"}))
    assert led.honest_n(GOAL) == 1, "换装饰字段刷出多条 → honest-N 被绕过（门坏）"
    led.record_or_hit(_entry(dataset_version="ds_b"))
    assert led.honest_n(GOAL) == 2, "换 dataset_version 没计新 trial → 可换数据集刷 N（门坏）"


# ── T-LED-6 等价写法各计 N（a*2 vs a+a）；语法同义折叠（a*2 vs (a*2)）─────────────
def test_equivalent_rewrites_distinct_syntactic_synonym_merges(tmp_path):
    led = Ledger(tmp_path)
    led.record_or_hit(_entry(ledger_factor="a*2"))
    led.record_or_hit(_entry(ledger_factor="a+a"))
    assert led.honest_n(GOAL) == 2, "a*2 与 a+a 被误折叠 → honest-N 低估（语义去重越权，门坏）"
    _, hit = led.record_or_hit(_entry(ledger_factor="(a*2)"))
    assert hit is True, "a*2 与 (a*2) 语法同义未折叠 → 冗余括号刷高 N（门坏）"
    assert led.honest_n(GOAL) == 2


# ── T-LED-7 跨 session/实例不重置：honest_n 按 goal 持久累计（05-T14）────────────
def test_honest_n_persists_across_instances(tmp_path):
    led_a = Ledger(tmp_path)
    led_a.record_or_hit(_entry(params={"win": 1}))
    led_a.record_or_hit(_entry(params={"win": 2}))
    assert led_a.honest_n(GOAL) == 2
    led_a.close()
    led_b = Ledger(tmp_path)
    assert led_b.honest_n(GOAL) == 2, "换 session 后 honest-N 归零 → 可换会话洗 N（门坏）"
    led_b.record_or_hit(_entry(params={"win": 3}))
    assert led_b.honest_n(GOAL) == 3


# ── T-LED-8 崩溃容错：JSONL 末尾坏行不炸全库（03-T11 / 05-T13）────────────────────
def test_crash_tolerant_bad_tail_line(tmp_path):
    led = Ledger(tmp_path)
    led.record_or_hit(_entry(params={"win": 1}))
    led.record_or_hit(_entry(params={"win": 2}))
    led.close()
    with (tmp_path / LEDGER_JSONL_FILENAME).open("a", encoding="utf-8") as fh:
        fh.write('{"seq": 2, "prev_hash": "deadbeef", "row_hash": "tr')   # 半行
    led2 = Ledger(tmp_path)
    assert led2.honest_n(GOAL) == 2, "一个坏尾行让账本不可用 → 崩溃即丢账（门坏）"
    led2.record_or_hit(_entry(params={"win": 3}))
    assert led2.honest_n(GOAL) == 3


# ── T-LED-9 防篡改：改中间历史行 → 哈希链断裂被检出（03-T3）──────────────────────
def test_tamper_evident_hash_chain_middle_edit(tmp_path):
    led = Ledger(tmp_path)
    for i in range(4):
        led.record_or_hit(_entry(params={"win": i}))
    assert led.verify_integrity().ok is True

    jsonl = tmp_path / LEDGER_JSONL_FILENAME
    lines = jsonl.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["payload"]["stage"] = "exploratory"   # 改内容、row_hash 不变 → 链必断
    lines[1] = json.dumps(rec, ensure_ascii=False)
    jsonl.write_text("\n".join(lines) + "\n")

    report = Ledger(tmp_path).verify_integrity()
    assert report.tampered is True and report.chain_intact is False, "改历史行未检出 → 篡改无痕（门坏）"
    text = report.message + " ".join(report.issues)
    assert any(w in text for w in ("哈希链不连续", "篡改", "防自欺"))
    assert not any(w in text for w in ("可信", "安全", "保证内容真实", "保证正确"))


# ── T-LED-10 SQLite↔JSONL 一本账对账：直改 SQLite 列与镜像背离被检出（S4 活性）──
def test_sqlite_column_tamper_detected(tmp_path):
    led = Ledger(tmp_path)
    for i in range(3):
        led.record_or_hit(_entry(params={"win": i}))
    assert led.verify_integrity().ok
    # 种坏：绕账本直改 SQLite 列（把 goal 改掉，企图让它从主题消失）。
    led._conn.execute("UPDATE ledger SET strategy_goal_ref='ghost' WHERE rowid=1")
    led._conn.commit()
    rep = led.verify_integrity()
    assert rep.tampered is True and rep.store_consistent is False, "SQLite 列被直改未检出 → 一本账裂开（门坏）"


# ── T-LED-11 SQLite 丢失 → 从 JSONL 全量重建（持久真相在 JSONL）──────────────────
def test_sqlite_rebuilt_from_jsonl_on_loss(tmp_path):
    led = Ledger(tmp_path)
    for i in range(4):
        led.record_or_hit(_entry(params={"win": i}))
    target = led.list_entries(GOAL)[0].config_hash
    led.tombstone(target, GOAL, reason="弃用")
    assert led.honest_n(GOAL) == 4
    led.close()
    (tmp_path / "ledger.sqlite").unlink()
    led2 = Ledger(tmp_path)
    assert led2.honest_n(GOAL) == 4, "SQLite 丢失后未从 JSONL 重建 → 账丢失（门坏）"
    assert led2.get(target, GOAL).tombstone is True
    assert led2.verify_integrity().ok is True, "JSONL 完整、仅丢 SQLite 应判 ok（误报截断=门坏）"


# ── T-LED-12 honest_n 诚实免责措辞（R2/R5）：说「下界」，不说「可信/安全/精确」──────
def test_honest_n_disclosure_wording():
    assert "下界" in HONEST_N_DISCLOSURE
    for banned in ("可信", "安全", "保证", "精确计数", "真实试验数"):
        assert banned not in HONEST_N_DISCLOSURE, f"免责出现绝对化措辞「{banned}」（门坏）"


# ── T-LED-13 get 语义：命中返存量、未知返 None ───────────────────────────────────
def test_get_returns_cached_or_none(tmp_path):
    led = Ledger(tmp_path)
    e, _ = led.record_or_hit(_entry(result_ref="ref-x"))
    got = led.get(e.config_hash, GOAL)
    assert got is not None and got.result_ref == "ref-x"
    assert led.get("cfg_v1_doesnotexist0", GOAL) is None


# ── T-LED-14 record_or_hit 幂等：重复入账不 append 第二条（03-T10）────────────────
def test_record_or_hit_idempotent_no_duplicate_row(tmp_path):
    led = Ledger(tmp_path)
    led.record_or_hit(_entry())
    jsonl = tmp_path / LEDGER_JSONL_FILENAME
    n1 = len(jsonl.read_text().splitlines())
    _, hit = led.record_or_hit(_entry())
    assert hit is True
    assert len(jsonl.read_text().splitlines()) == n1, "幂等入账却 append 第二条 → 重复记账（门坏）"
    assert led.honest_n(GOAL) == 1


# ── T-LED-15 跨主题同 config 不互相吞没（复核 #1，命门·硬）────────────────────────
def test_cross_theme_same_config_each_counts(tmp_path):
    led = Ledger(tmp_path)
    ea, ha = led.record_or_hit(_entry(goal="theme_A"))
    eb, hb = led.record_or_hit(_entry(goal="theme_B"))   # 同一 config 输入、不同主题
    assert ea.config_hash == eb.config_hash, "前提：同 config 输入跨主题应同 config_hash"
    assert hb is False, "主题 B 的试验撞主题 A 行被静默吞 → honest-N 洗白（门坏）"
    assert led.honest_n("theme_A") == 1
    assert led.honest_n("theme_B") == 1, "主题 B 的 honest_n 被吞成 0 → 可借他主题洗白（门坏）"
    assert led.get(eb.config_hash, "theme_B") is not None


# ── T-LED-16 UPSERT 不改主题/内容、不减 N（复核 #2，命门·硬）─────────────────────
def test_upsert_cannot_relocate_theme_or_mutate_content(tmp_path):
    led = Ledger(tmp_path)
    e, _ = led.record_or_hit(_entry(goal="theme_A"))
    led.record_or_hit(_entry(goal="theme_B"))            # 同 config 落到 B（新行，不动 A）
    assert led.honest_n("theme_A") == 1, "落主题 B 把主题 A 的行迁走 → A 的 N 掉（门坏）"
    # 软删 / 回填只动可变字段，内容/创建字段不可变。
    led.update_fields(e.config_hash, "theme_A", result_ref="r2")
    row = led._conn.execute(
        "SELECT kind, stage, strategy_goal_ref FROM ledger WHERE config_hash=? AND strategy_goal_ref='theme_A'",
        (e.config_hash,),
    ).fetchone()
    assert row == ("backtest", "confirmatory", "theme_A"), "回填竟改了内容/主题列 → 可借更新改写历史（门坏）"
    assert led.honest_n("theme_A") == 1 and led.verify_integrity().ok


# ── T-LED-17 并发 memoize 对同键 compute 至多一次（复核 #3）──────────────────────
def test_concurrent_memoize_computes_once(tmp_path):
    led = Ledger(tmp_path)
    calls = []
    clock = threading.Lock()

    def compute():
        with clock:
            calls.append(1)
        time.sleep(0.05)   # 真回测有真实墙钟耗时
        return "ref-c"

    barrier = threading.Barrier(4)

    def worker():
        barrier.wait()
        led.memoize(_entry(), compute)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(calls) == 1, f"并发同键 memoize 把 compute 跑了 {sum(calls)} 次 → R8 不重跑被并发击穿（门坏）"
    assert led.honest_n(GOAL) == 1
    # 无锁实现下 4 线程会各自走「回填」分支 → 1 条 record + 3 条 update；故断言 0 条 update
    # 才能真正区分坏实现（光断言 record==1 会被 UPSERT 折叠假绿，复核 second-look 指出）。
    ops = [r["op"] for r in led._chain.read_records()]
    assert ops.count("record") == 1 and ops.count("update") == 0, "并发产生多余审计行 → 锁失效（门坏）"


# ── T-LED-18 record_or_hit 占位后 memoize 回填 result_ref（复核 #4）──────────────
def test_memoize_backfills_result_ref_after_record_or_hit(tmp_path):
    led = Ledger(tmp_path)
    led.record_or_hit(_entry())                 # 占位：result_ref=None
    assert led.get(_entry().config_hash, GOAL).result_ref is None
    compute = Mock(return_value="ref-backfill")
    entry, hit = led.memoize(_entry(), compute)
    assert compute.call_count == 1, "占位条目（result_ref 空）memoize 竟跳过 compute → 计算永丢（门坏）"
    assert entry.result_ref == "ref-backfill"
    assert led.honest_n(GOAL) == 1, "回填不应重复计 N"


# ── T-LED-19 软删条目不被 memoize 当陈旧命中返回（复核 #5）────────────────────────
def test_memoize_does_not_serve_tombstoned_stale_result(tmp_path):
    led = Ledger(tmp_path)
    led.memoize(_entry(), Mock(return_value="old-buggy"))
    h = _entry().config_hash
    led.tombstone(h, GOAL, reason="结果有 bug，弃用", superseded_by="cfg_v1_newer0")
    compute = Mock(return_value="fresh-correct")
    entry, hit = led.memoize(_entry(), compute)
    assert compute.call_count == 1, "软删条目被当陈旧命中返回旧坏结果 → 不重算（门坏）"
    assert entry.result_ref == "fresh-correct" and entry.tombstone is False
    assert led.honest_n(GOAL) == 1, "复活同 config 不应重复计 N"


# ── T-LED-20 篡改 SQLite 读路径列被检出（复核 #7/#9：读路径 == 被核验路径）────────
def test_read_path_column_tamper_detected(tmp_path):
    led = Ledger(tmp_path)
    e, _ = led.record_or_hit(_entry(result_ref="good"))
    led._conn.execute("UPDATE ledger SET result_ref='EVIL' WHERE rowid=1")
    led._conn.commit()
    # get 读的就是被改的列（坏结果会被消费），但对账必须把它揪出来。
    assert led.get(e.config_hash, GOAL).result_ref == "EVIL"
    assert led.verify_integrity().tampered is True, "改 SQLite 读路径列未检出 → 可投毒缓存指针（门坏）"


# ── T-LED-21 末尾截断经高水位见证被检出（复核 #6）────────────────────────────────
def test_truncation_detected_via_hwm(tmp_path):
    led = Ledger(tmp_path)
    for i in range(5):
        led.record_or_hit(_entry(params={"win": i}))
    assert led.honest_n(GOAL) == 5
    led.close()
    # 种坏：删 JSONL 末尾 2 行 + 删 SQLite（且其 wal/shm），但保留独立 hwm 见证。
    jsonl = tmp_path / LEDGER_JSONL_FILENAME
    lines = jsonl.read_text().splitlines()
    jsonl.write_text("\n".join(lines[:3]) + "\n")
    for f in ("ledger.sqlite", "ledger.sqlite-wal", "ledger.sqlite-shm"):
        p = tmp_path / f
        if p.exists():
            p.unlink()
    assert (tmp_path / LEDGER_HWM_FILENAME).exists(), "前提：独立 hwm 见证文件应存在"

    rep = Ledger(tmp_path).verify_integrity()
    assert rep.not_truncated is False and rep.tampered is True, "JSONL 末尾被截 + 丢库竟未被高水位见证检出（门坏）"


# ── T-LED-22 坏 payload 行不炸 init/verify（复核 #8）──────────────────────────────
def test_malformed_payload_row_does_not_brick_ledger(tmp_path):
    led = Ledger(tmp_path)
    led.record_or_hit(_entry())
    led._chain.append("record", {"foo": "bar"})   # 链有效但 payload 缺 config_hash
    led.close()
    led2 = Ledger(tmp_path)                         # 不得因单条坏 payload 行无法构造
    assert led2.honest_n(GOAL) == 1, "坏 payload 行污染了计数（门坏）"
    rep = led2.verify_integrity()
    assert rep.tampered is True, "坏 payload 行未被 verify 标出 → 静默吞坏行（门坏）"


# ── T-LED-23 SQLite 行删除（集合背离）被检出（复核 #10）──────────────────────────
def test_sqlite_row_deletion_set_divergence_detected(tmp_path):
    led = Ledger(tmp_path)
    for i in range(3):
        led.record_or_hit(_entry(params={"win": i}))
    led._conn.execute("DELETE FROM ledger WHERE rowid=1")
    led._conn.commit()
    assert led.honest_n(GOAL) == 2   # SQLite 计数当场掉
    rep = led.verify_integrity()
    assert rep.store_consistent is False and rep.tampered is True, "删 SQLite 行造成集合背离未检出（门坏）"


# ── T-LED-24 tombstone 写入 SQLite 列 + 软删后对账仍 ok（复核 #11）────────────────
def test_tombstone_column_written_and_reconciles(tmp_path):
    led = Ledger(tmp_path)
    e, _ = led.record_or_hit(_entry())
    led.tombstone(e.config_hash, GOAL, reason="弃用")
    col = led._conn.execute(
        "SELECT tombstone FROM ledger WHERE config_hash=? AND strategy_goal_ref=?", (e.config_hash, GOAL)
    ).fetchone()[0]
    assert col == 1, "tombstone 列没写进 SQLite → 列与 payload 可悄然不一致（门坏）"
    assert led.verify_integrity().ok is True, "软删后列与审计应一致（不一致=门坏）"


# ── T-LED-25 update_fields 回填可生效、不减 N、append 审计行（复核 low-note）───────
def test_update_fields_backfill(tmp_path):
    led = Ledger(tmp_path)
    e, _ = led.record_or_hit(_entry())
    jsonl = tmp_path / LEDGER_JSONL_FILENAME
    n1 = len(jsonl.read_text().splitlines())
    led.update_fields(e.config_hash, GOAL, returns_corr_cluster_id="cl_1")
    assert led.get(e.config_hash, GOAL).returns_corr_cluster_id == "cl_1", "update_fields 无效（门坏）"
    assert led.honest_n(GOAL) == 1
    assert len(jsonl.read_text().splitlines()) == n1 + 1, "update_fields 应 append 恰一条审计行"
    assert led.verify_integrity().ok is True
