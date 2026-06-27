"""v1.0.3 · Stripe 订阅服务 (scaffold)。

设计:
- 不真做 Stripe API 调用（user 拿到 API key 后我接入真 stripe-python SDK）
- 当前 scaffold:
  · sqlite 表 billing_subscriptions
  · plan 枚举 + 价格信息（与 /pricing 页一致）
  · 用户 plan 切换 record_subscription（模拟支付完成）
  · webhook handler 框架（解析 stripe event payload + 更新 db）
- v1.0.3 接入 Stripe 时:
  · 装 stripe-python
  · 实现 create_checkout_session（user 点"购买"→重定向 stripe.com）
  · 实现 webhook signature 校验
  · 接入 customer.subscription.created/updated/deleted 三个事件
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


class BillingError(Exception):
    pass


Plan = Literal["community", "learn", "live_pro"]

PLAN_IDS: list[Plan] = ["community", "learn", "live_pro"]


# 与 /pricing 页（PricingPage.tsx）一致；Stripe Price ID 在 user 拿到 Stripe 账号后填进 secrets.yaml
PLAN_INFO: dict[Plan, dict[str, Any]] = {
    "community": {
        "name": "Community",
        "price_cny_monthly": 0,
        "price_cny_annual": 0,
        "stripe_price_id_monthly": None,
        "stripe_price_id_annual": None,
        "features": {
            "live_mainnet": False,
            "live_testnet": False,
            "agent_daily_quota": 3,
            "max_runs_per_day": 5,
            "glossary_depth": "l1_l2",
        },
    },
    "learn": {
        "name": "Learn",
        "price_cny_monthly": 49,
        "price_cny_annual": 499,
        "stripe_price_id_monthly": None,  # user 在 Stripe 后台建后填
        "stripe_price_id_annual": None,
        "features": {
            "live_mainnet": False,
            "live_testnet": True,
            "agent_daily_quota": 20,
            "max_runs_per_day": -1,  # 无限
            "glossary_depth": "l1_l2_l3_l4",
        },
    },
    "live_pro": {
        "name": "Live Pro",
        "price_cny_monthly": 149,
        "price_cny_annual": 1499,
        "stripe_price_id_monthly": None,
        "stripe_price_id_annual": None,
        "features": {
            "live_mainnet": True,
            "live_testnet": True,
            "agent_daily_quota": 100,
            "max_runs_per_day": -1,
            "glossary_depth": "l1_l2_l3_l4",
            "copy_trade_beta": True,
        },
    },
}


@dataclass
class SubscriptionRecord:
    user_id: str
    plan: Plan
    billing_cycle: Literal["monthly", "annual"]  # 或 'none' for community
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    status: Literal["active", "past_due", "canceled", "trialing"]
    started_at_utc: str
    current_period_end_utc: str | None
    cancel_at_period_end: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS billing_subscriptions (
        user_id TEXT PRIMARY KEY,
        plan TEXT NOT NULL,
        billing_cycle TEXT NOT NULL DEFAULT 'monthly',
        stripe_customer_id TEXT,
        stripe_subscription_id TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        started_at_utc TEXT NOT NULL,
        current_period_end_utc TEXT,
        cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
        metadata TEXT NOT NULL DEFAULT '{}',
        updated_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS billing_webhook_events (
        event_id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        payload TEXT NOT NULL,
        processed_at_utc TEXT NOT NULL,
        processing_result TEXT NOT NULL
    )
    """,
]


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def init_billing_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as c:
        for stmt in _SCHEMA:
            c.execute(stmt)
        c.commit()


class BillingService:
    def __init__(self, db_path: Path) -> None:
        self._db = db_path
        init_billing_db(db_path)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db)
        c.row_factory = sqlite3.Row
        return c

    def get_subscription(self, user_id: str) -> SubscriptionRecord:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM billing_subscriptions WHERE user_id=?",
                (user_id,),
            ).fetchone()
        if not row:
            # 默认 Community 免费档
            return SubscriptionRecord(
                user_id=user_id, plan="community", billing_cycle="monthly",
                stripe_customer_id=None, stripe_subscription_id=None,
                status="active", started_at_utc=_utc_now(),
                current_period_end_utc=None, cancel_at_period_end=False,
            )
        return SubscriptionRecord(
            user_id=row["user_id"], plan=row["plan"],  # type: ignore
            billing_cycle=row["billing_cycle"],
            stripe_customer_id=row["stripe_customer_id"],
            stripe_subscription_id=row["stripe_subscription_id"],
            status=row["status"],
            started_at_utc=row["started_at_utc"],
            current_period_end_utc=row["current_period_end_utc"],
            cancel_at_period_end=bool(row["cancel_at_period_end"]),
            metadata=json.loads(row["metadata"] or "{}"),
        )

    def upsert_subscription(self, rec: SubscriptionRecord) -> None:
        if rec.plan not in PLAN_IDS:
            raise BillingError(f"plan 必须 ∈ {PLAN_IDS}")
        now = _utc_now()
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO billing_subscriptions "
                "(user_id, plan, billing_cycle, stripe_customer_id, stripe_subscription_id, "
                "status, started_at_utc, current_period_end_utc, cancel_at_period_end, metadata, updated_at_utc) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rec.user_id, rec.plan, rec.billing_cycle,
                    rec.stripe_customer_id, rec.stripe_subscription_id,
                    rec.status, rec.started_at_utc, rec.current_period_end_utc,
                    int(rec.cancel_at_period_end), json.dumps(rec.metadata, ensure_ascii=False),
                    now,
                ),
            )
            c.commit()

    def user_can_access_feature(self, user_id: str, feature: str) -> bool:
        """检查 user 当前 plan 是否解锁该 feature (live_mainnet / agent_daily_quota 等)。"""
        sub = self.get_subscription(user_id)
        plan_features = PLAN_INFO[sub.plan]["features"]
        v = plan_features.get(feature)
        if isinstance(v, bool):
            return v
        return v is not None

    def get_agent_daily_quota(self, user_id: str) -> int:
        sub = self.get_subscription(user_id)
        return PLAN_INFO[sub.plan]["features"].get("agent_daily_quota", 0)

    def get_max_runs_per_day(self, user_id: str) -> int:
        sub = self.get_subscription(user_id)
        return PLAN_INFO[sub.plan]["features"].get("max_runs_per_day", 0)

    def record_webhook_event(
        self, event_id: str, event_type: str, payload: dict[str, Any], processing_result: str = "ok",
    ) -> None:
        """Stripe webhook 接收 → 落库 + 幂等去重。"""
        with self._conn() as c:
            # 幂等：同 event_id 不重复处理
            existing = c.execute(
                "SELECT 1 FROM billing_webhook_events WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if existing:
                return
            c.execute(
                "INSERT INTO billing_webhook_events (event_id, event_type, payload, processed_at_utc, processing_result) "
                "VALUES (?,?,?,?,?)",
                (event_id, event_type, json.dumps(payload, ensure_ascii=False), _utc_now(), processing_result),
            )
            c.commit()

    def process_stripe_event(self, event: dict[str, Any]) -> str:
        """处理 Stripe webhook event。

        支持的 event types:
        - customer.subscription.created → 新建 subscription record
        - customer.subscription.updated → 更新（plan upgrade/downgrade）
        - customer.subscription.deleted → 标记 canceled
        - invoice.payment_failed → 标记 past_due
        """
        event_id = event.get("id", "")
        event_type = event.get("type", "")
        data_object = (event.get("data") or {}).get("object") or {}
        user_id = (data_object.get("metadata") or {}).get("user_id") or ""

        if event_type in ("customer.subscription.created", "customer.subscription.updated"):
            # 从 Stripe price id 反查 plan
            price_id = ""
            try:
                items = data_object.get("items", {}).get("data", [])
                if items:
                    price_id = items[0].get("price", {}).get("id", "")
            except Exception:
                pass
            plan = self._resolve_plan_from_price_id(price_id)
            cycle: Literal["monthly", "annual"] = self._resolve_cycle_from_price_id(price_id)
            self.upsert_subscription(SubscriptionRecord(
                user_id=user_id, plan=plan, billing_cycle=cycle,
                stripe_customer_id=data_object.get("customer"),
                stripe_subscription_id=data_object.get("id"),
                status=data_object.get("status", "active"),
                started_at_utc=_utc_now(),
                current_period_end_utc=time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(data_object.get("current_period_end", 0)),
                ) if data_object.get("current_period_end") else None,
                cancel_at_period_end=bool(data_object.get("cancel_at_period_end")),
            ))
            result = f"upserted {plan}"
        elif event_type == "customer.subscription.deleted":
            sub = self.get_subscription(user_id)
            sub.status = "canceled"
            sub.plan = "community"  # 降级回 community
            self.upsert_subscription(sub)
            result = "canceled"
        elif event_type == "invoice.payment_failed":
            sub = self.get_subscription(user_id)
            sub.status = "past_due"
            self.upsert_subscription(sub)
            result = "past_due"
        else:
            result = "ignored"

        self.record_webhook_event(event_id, event_type, event, result)
        return result

    def _resolve_plan_from_price_id(self, price_id: str) -> Plan:
        """反查 plan: user 在 Stripe 后台建 price 后，把 price_id 填到 PLAN_INFO."""
        if not price_id:
            return "community"
        for plan_name, info in PLAN_INFO.items():
            if price_id in (info.get("stripe_price_id_monthly"), info.get("stripe_price_id_annual")):
                return plan_name  # type: ignore
        return "community"  # fallback

    def _resolve_cycle_from_price_id(self, price_id: str) -> Literal["monthly", "annual"]:
        for info in PLAN_INFO.values():
            if price_id == info.get("stripe_price_id_annual"):
                return "annual"
        return "monthly"


__all__ = [
    "BillingError",
    "BillingService",
    "PLAN_IDS",
    "PLAN_INFO",
    "Plan",
    "SubscriptionRecord",
    "init_billing_db",
]
