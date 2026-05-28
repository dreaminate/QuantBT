"""v1.0.3 · Stripe 订阅接入 (Community / Learn / Live Pro 三档).

Plan id 映射 (Stripe 后台创建后回填到 secrets.yaml):
  community  → free, 无 Stripe price
  learn      → ¥49/月 / ¥499/年
  live_pro   → ¥149/月 / ¥1499/年
"""

from __future__ import annotations

from .stripe_service import (
    BillingError,
    BillingService,
    PLAN_IDS,
    Plan,
    SubscriptionRecord,
    init_billing_db,
)

__all__ = [
    "BillingError",
    "BillingService",
    "PLAN_IDS",
    "Plan",
    "SubscriptionRecord",
    "init_billing_db",
]
