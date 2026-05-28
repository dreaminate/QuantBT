"""v1.0.3 · Stripe billing scaffold 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.billing import BillingError, BillingService, PLAN_IDS, SubscriptionRecord


@pytest.fixture
def svc(tmp_path: Path) -> BillingService:
    return BillingService(tmp_path / "billing.db")


def test_default_subscription_is_community(svc):
    sub = svc.get_subscription("u1")
    assert sub.plan == "community"
    assert sub.status == "active"
    assert sub.stripe_subscription_id is None


def test_plan_ids_three(svc):
    assert PLAN_IDS == ["community", "learn", "live_pro"]


def test_upsert_learn_plan(svc):
    sub = SubscriptionRecord(
        user_id="u1", plan="learn", billing_cycle="monthly",
        stripe_customer_id="cus_1", stripe_subscription_id="sub_1",
        status="active", started_at_utc="2026-05-29T00:00:00Z",
        current_period_end_utc="2026-06-29T00:00:00Z", cancel_at_period_end=False,
    )
    svc.upsert_subscription(sub)
    got = svc.get_subscription("u1")
    assert got.plan == "learn"
    assert got.stripe_subscription_id == "sub_1"


def test_upsert_invalid_plan_raises(svc):
    sub = SubscriptionRecord(
        user_id="u1", plan="enterprise",  # type: ignore[arg-type]
        billing_cycle="monthly",
        stripe_customer_id=None, stripe_subscription_id=None,
        status="active", started_at_utc="x",
        current_period_end_utc=None, cancel_at_period_end=False,
    )
    with pytest.raises(BillingError):
        svc.upsert_subscription(sub)


def test_user_can_access_feature(svc):
    # community 默认不能 live_mainnet
    assert svc.user_can_access_feature("u1", "live_mainnet") is False

    # 升 live_pro
    sub = SubscriptionRecord(
        user_id="u1", plan="live_pro", billing_cycle="monthly",
        stripe_customer_id=None, stripe_subscription_id=None,
        status="active", started_at_utc="x",
        current_period_end_utc=None, cancel_at_period_end=False,
    )
    svc.upsert_subscription(sub)
    assert svc.user_can_access_feature("u1", "live_mainnet") is True
    assert svc.user_can_access_feature("u1", "copy_trade_beta") is True


def test_agent_daily_quota_by_plan(svc):
    # community 默认 3 次
    assert svc.get_agent_daily_quota("u1") == 3

    # learn 20 次
    sub = SubscriptionRecord(
        user_id="u1", plan="learn", billing_cycle="monthly",
        stripe_customer_id=None, stripe_subscription_id=None,
        status="active", started_at_utc="x",
        current_period_end_utc=None, cancel_at_period_end=False,
    )
    svc.upsert_subscription(sub)
    assert svc.get_agent_daily_quota("u1") == 20


def test_process_stripe_event_subscription_created(svc):
    event = {
        "id": "evt_123",
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_test",
                "customer": "cus_test",
                "status": "active",
                "metadata": {"user_id": "u1"},
                "items": {"data": [{"price": {"id": "price_unknown"}}]},
                "current_period_end": 1735689600,
                "cancel_at_period_end": False,
            }
        }
    }
    result = svc.process_stripe_event(event)
    assert "upserted" in result
    sub = svc.get_subscription("u1")
    assert sub.stripe_subscription_id == "sub_test"


def test_process_stripe_event_subscription_deleted_downgrades(svc):
    # 先升 learn
    svc.upsert_subscription(SubscriptionRecord(
        user_id="u1", plan="learn", billing_cycle="monthly",
        stripe_customer_id=None, stripe_subscription_id=None,
        status="active", started_at_utc="x",
        current_period_end_utc=None, cancel_at_period_end=False,
    ))
    event = {
        "id": "evt_delete",
        "type": "customer.subscription.deleted",
        "data": {"object": {"metadata": {"user_id": "u1"}}},
    }
    result = svc.process_stripe_event(event)
    assert result == "canceled"
    sub = svc.get_subscription("u1")
    assert sub.plan == "community"
    assert sub.status == "canceled"


def test_process_stripe_event_payment_failed(svc):
    svc.upsert_subscription(SubscriptionRecord(
        user_id="u1", plan="learn", billing_cycle="monthly",
        stripe_customer_id=None, stripe_subscription_id=None,
        status="active", started_at_utc="x",
        current_period_end_utc=None, cancel_at_period_end=False,
    ))
    event = {
        "id": "evt_fail",
        "type": "invoice.payment_failed",
        "data": {"object": {"metadata": {"user_id": "u1"}}},
    }
    result = svc.process_stripe_event(event)
    assert result == "past_due"
    sub = svc.get_subscription("u1")
    assert sub.status == "past_due"


def test_webhook_idempotency(svc):
    """同 event_id 两次发送只处理一次。"""
    event = {
        "id": "evt_idem",
        "type": "customer.subscription.created",
        "data": {"object": {"id": "sub", "status": "active",
                              "metadata": {"user_id": "u1"},
                              "items": {"data": []}}},
    }
    svc.process_stripe_event(event)
    svc.process_stripe_event(event)  # 第二次应该 skip

    # webhook_events 表里只一条
    with svc._conn() as c:
        rows = c.execute("SELECT COUNT(*) FROM billing_webhook_events WHERE event_id='evt_idem'").fetchone()
    assert rows[0] == 1


def test_unknown_event_type_ignored(svc):
    event = {
        "id": "evt_unknown",
        "type": "checkout.session.completed",  # 暂不处理
        "data": {"object": {}},
    }
    result = svc.process_stripe_event(event)
    assert result == "ignored"
