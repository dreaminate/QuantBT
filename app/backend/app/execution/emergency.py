"""Account-scoped emergency handles for lease-only Binance futures venues.

The registry stores references and broker capabilities, never API key material.
Every private emergency operation obtains a short-lived KeyBroker lease and
revokes it in ``finally``.  No network call happens at registration time.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from ..lineage.ids import content_hash
from ..security.gate.broker import KeyBroker
from .base import ExecutionAuditLog, ExecutionReport, OrderExecutionObservation, Position
from .binance_client import BinanceAPIError
from .emergency_journal import (
    EmergencyActionError,
    EmergencyActionJournal,
    EmergencyCloseAction,
)
from .leased_binance import LeasedBinanceVenue


@dataclass(frozen=True)
class AccountPositionObservation:
    symbol: str
    quantity: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: float
    liquidation_price: float
    margin_mode: str


@dataclass(frozen=True)
class AccountExecutionObservation:
    account_ref: str
    observed_at_utc: str
    source_ref: str
    equity: float
    positions: tuple[AccountPositionObservation, ...]
    mark_price: float
    bid_price: float
    ask_price: float
    maker_fee_bps: float
    taker_fee_bps: float
    funding_rate_bps: float
    credential_check_ref: str
    ip_allowlist_ref: str
    withdrawal_disabled_ref: str
    hmac_replay_protection_ref: str
    health_check_ref: str
    rate_limit_ref: str
    account_identity_source: str
    position_mode: str
    can_trade: bool
    multi_assets_margin: bool
    permission_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class EmergencyVenueIdentity:
    owner_user_id: str
    account_ref: str
    keystore_name: str
    credential_binding_ref: str
    network: str
    product: str


@dataclass(frozen=True)
class EmergencyHaltContext:
    owner_user_id: str
    owner_epoch: int
    halt_ref: str
    account_ref: str
    account_epoch: int


class BrokeredEmergencyBinanceVenue:
    """Unique account handle that materializes credentials only per action."""

    def __init__(
        self,
        *,
        owner_user_id: str,
        account_ref: str,
        keystore_name: str,
        credential_binding_ref: str,
        broker: KeyBroker,
        network: str,
        product: str,
        max_leverage: int = 5,
        audit: ExecutionAuditLog | None = None,
        action_journal: EmergencyActionJournal | None = None,
        venue_factory: Callable[[], LeasedBinanceVenue] | None = None,
    ) -> None:
        owner_user_id = str(owner_user_id or "").strip()
        account_ref = str(account_ref or "").strip()
        keystore_name = str(keystore_name or "").strip()
        credential_binding_ref = str(credential_binding_ref or "").strip()
        if not owner_user_id:
            raise ValueError("emergency owner_user_id is required")
        if not account_ref:
            raise ValueError("emergency account_ref is required")
        if not keystore_name:
            raise ValueError("emergency keystore_name is required")
        if not credential_binding_ref:
            raise ValueError("emergency credential_binding_ref is required")
        if network not in {"testnet", "mainnet"}:
            raise ValueError("emergency Binance network must be testnet or mainnet")
        if product != "usdm_futures":
            raise ValueError("emergency close support currently requires usdm_futures")
        if network == "mainnet" and (
            action_journal is None or not action_journal.account_fence_bound
        ):
            raise ValueError(
                "mainnet emergency handle requires a fenced durable action journal"
            )
        self._identity = EmergencyVenueIdentity(
            owner_user_id=owner_user_id,
            account_ref=account_ref,
            keystore_name=keystore_name,
            credential_binding_ref=credential_binding_ref,
            network=network,
            product=product,
        )
        self._broker = broker
        self._action_journal = action_journal
        self._venue_factory = venue_factory or (
            lambda: LeasedBinanceVenue(
                product="usdm_futures",
                network=network,  # type: ignore[arg-type]
                max_leverage=max_leverage,
                audit=audit,
            )
        )

    @property
    def owner_user_id(self) -> str:
        return self._identity.owner_user_id

    @property
    def account_ref(self) -> str:
        return self._identity.account_ref

    @property
    def keystore_name(self) -> str:
        return self._identity.keystore_name

    @property
    def credential_binding_ref(self) -> str:
        return self._identity.credential_binding_ref

    @property
    def network(self) -> str:
        return self._identity.network

    @property
    def product(self) -> str:
        return self._identity.product

    @property
    def name(self) -> str:
        return f"leased_binance:{self.account_ref}:{self.network}:{self.product}"

    def _with_lease(
        self,
        operation: Callable[[LeasedBinanceVenue, Any], Any],
        *,
        action: str = "emergency_reduce_risk",
    ) -> Any:
        capability = self._broker.issue_capability(
            action=action,  # type: ignore[arg-type]
            gate_ref=f"emergency:{self.account_ref}",
            keystore_name=self.keystore_name,
            account_identity_ref=self.account_ref,
            owner_user_id=self.owner_user_id,
        )
        if (
            capability.credential_binding_ref is not None
            and capability.credential_binding_ref != self.credential_binding_ref
        ):
            raise PermissionError("emergency handle credential binding no longer matches broker registry")
        lease = self._broker.issue(capability)
        try:
            return operation(self._venue_factory(), lease)
        finally:
            self._broker.revoke(lease)

    def emergency_cancel_all(self) -> dict[str, Any]:
        return self._with_lease(lambda venue, lease: venue.emergency_cancel_all(lease=lease))

    def list_open_positions(self) -> list[Position]:
        return self._with_lease(lambda venue, lease: venue.list_open_positions(lease=lease))

    def list_open_order_refs(self) -> tuple[str, ...]:
        rows = self._with_lease(lambda venue, lease: venue.list_open_orders(lease=lease))
        if not isinstance(rows, list):
            raise TypeError("open-order discovery returned a non-list")
        refs: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("open-order discovery returned a malformed row")
            kind = str(row.get("_qb_order_kind") or "normal").strip().lower()
            if kind not in {"normal", "algo"}:
                raise ValueError("open-order discovery returned an unsupported order kind")
            order_ref = str(
                row.get("algoId")
                or row.get("clientAlgoId")
                or row.get("orderId")
                or row.get("clientOrderId")
                or ""
            ).strip()
            if not order_ref:
                raise ValueError("open-order discovery row lacks an order identity")
            refs.append(f"{kind}:{order_ref}")
        return tuple(sorted(set(refs)))

    def execution_reports_for_order(
        self,
        symbol: str,
        *,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> list[ExecutionReport]:
        return self._with_lease(
            lambda venue, lease: venue.execution_reports_for_order(
                symbol,
                order_id=order_id,
                client_order_id=client_order_id,
                lease=lease,
            )
        )

    def execution_bundle_for_order(
        self,
        symbol: str,
        *,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> tuple[OrderExecutionObservation, list[ExecutionReport]]:
        return self._with_lease(
            lambda venue, lease: venue.execution_bundle_for_order(
                symbol,
                order_id=order_id,
                client_order_id=client_order_id,
                lease=lease,
            )
        )

    @staticmethod
    def _validated_context(
        context: EmergencyHaltContext,
        *,
        owner_user_id: str,
        account_ref: str,
    ) -> EmergencyHaltContext:
        if not isinstance(context, EmergencyHaltContext):
            raise TypeError("emergency close requires a typed HALT context")
        if context.owner_user_id != owner_user_id or context.account_ref != account_ref:
            raise PermissionError("emergency HALT context belongs to a different account")
        if (
            type(context.owner_epoch) is not int
            or context.owner_epoch <= 0
            or type(context.account_epoch) is not int
            or context.account_epoch <= 0
            or not str(context.halt_ref or "").strip()
        ):
            raise ValueError("emergency HALT context is incomplete")
        return context

    @staticmethod
    def _validate_observation(
        action: EmergencyCloseAction,
        observation: OrderExecutionObservation,
    ) -> None:
        try:
            raw_quantity = Decimal(str(observation.raw.get("origQty")))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise EmergencyActionError(
                "exact venue observation lacks canonical requested quantity"
            ) from exc
        if (
            observation.client_order_id != action.client_order_id
            or observation.symbol != action.symbol
            or observation.side != action.side
            or raw_quantity != Decimal(action.quantity_text)
            or (
                bool(action.venue_order_id)
                and observation.order_id != action.venue_order_id
            )
        ):
            raise EmergencyActionError(
                "exact venue observation differs from the prepared emergency request"
            )

    def _apply_observation(
        self,
        venue: LeasedBinanceVenue,
        lease: Any,
        action: EmergencyCloseAction,
        observation: OrderExecutionObservation,
    ) -> EmergencyCloseAction:
        if self._action_journal is None:  # pragma: no cover - guarded by public callers.
            raise EmergencyActionError("emergency action journal is unavailable")
        self._validate_observation(action, observation)
        if observation.status == "filled":
            remaining = [
                position
                for position in venue.list_open_positions(lease=lease)
                if position.symbol.upper() == action.symbol
            ]
            if remaining:
                return self._action_journal.mark_filled_residual(
                    action.action_ref,
                    venue_order_id=observation.order_id,
                    observation_ref=observation.source_event_ref,
                    response_hash=observation.raw_event_hash,
                    cumulative_filled_qty=observation.cumulative_filled_qty,
                )
            return self._action_journal.mark_reconciled(
                action.action_ref,
                venue_order_id=observation.order_id,
                observation_ref=observation.source_event_ref,
                response_hash=observation.raw_event_hash,
                cumulative_filled_qty=observation.cumulative_filled_qty,
                terminal_status=observation.status,
                verified_flat=True,
            )
        if observation.status in {"new", "partially_filled"}:
            return self._action_journal.mark_pending(
                action.action_ref,
                venue_order_id=observation.order_id,
                observation_ref=observation.source_event_ref,
                response_hash=observation.raw_event_hash,
                cumulative_filled_qty=observation.cumulative_filled_qty,
                terminal_status=observation.status,
            )
        if observation.cumulative_filled_qty == 0:
            return self._action_journal.mark_failed(
                action.action_ref,
                venue_order_id=observation.order_id,
                observation_ref=observation.source_event_ref,
                response_hash=observation.raw_event_hash,
                cumulative_filled_qty=0,
                terminal_status=observation.status,
            )
        # The exact terminal observation closes this attempt while preserving
        # its economic effect.  A later fresh residual snapshot may prepare
        # attempt_no+1 with a different deterministic client ID.
        return self._action_journal.mark_partial_terminal(
            action.action_ref,
            venue_order_id=observation.order_id,
            observation_ref=observation.source_event_ref,
            response_hash=observation.raw_event_hash,
            cumulative_filled_qty=observation.cumulative_filled_qty,
            terminal_status=observation.status,
        )

    def _observe_action(
        self,
        venue: LeasedBinanceVenue,
        lease: Any,
        action: EmergencyCloseAction,
    ) -> EmergencyCloseAction:
        observation = venue.order_execution_observation(
            action.symbol,
            client_order_id=action.client_order_id,
            expected_emergency_close=True,
            lease=lease,
        )
        return self._apply_observation(venue, lease, action, observation)

    def _observe_action_or_fail_closed(
        self,
        action: EmergencyCloseAction,
    ) -> EmergencyCloseAction:
        try:
            return self._with_lease(
                lambda venue, lease: self._observe_action(venue, lease, action)
            )
        except BinanceAPIError as exc:
            if exc.code == -2013:
                raise EmergencyActionError(
                    "submitted emergency action is absent from exact venue lookup; automatic resubmit denied"
                ) from exc
            raise

    def resolve_unknown_submission_for_halt(
        self,
        action_ref: str,
        context: EmergencyHaltContext,
        *,
        operator_auth_audit_ref: str,
    ) -> dict[str, Any]:
        """Resolve exact ``-2013`` only as unknown + currently flat + no retry."""

        context = self._validated_context(
            context,
            owner_user_id=self.owner_user_id,
            account_ref=self.account_ref,
        )
        if self._action_journal is None:
            raise EmergencyActionError("emergency action journal is unavailable")
        action = self._action_journal.action(action_ref)
        if (
            action.owner_user_id != context.owner_user_id
            or action.account_ref != context.account_ref
            or action.account_epoch != context.account_epoch
        ):
            raise EmergencyActionError(
                "emergency action belongs to a different HALT account epoch"
            )
        if action.status == "manual_unknown_flat":
            resolution = self._action_journal.unknown_submission_resolution(
                action.action_ref,
                owner_user_id=context.owner_user_id,
            )
            return {
                "action": action.to_dict(),
                "resolution": resolution.to_dict(),
                "resolved_via": "persisted_manual_unknown_flat",
            }
        if action.status not in {"submitting", "acknowledged", "pending"}:
            raise EmergencyActionError(
                "emergency action is not a submitted unresolved action"
            )
        expected_head = action.last_event_ref

        def inspect(
            venue: LeasedBinanceVenue,
            lease: Any,
        ) -> tuple[str, Any, Any, Any]:
            try:
                observation = venue.order_execution_observation(
                    action.symbol,
                    client_order_id=action.client_order_id,
                    expected_emergency_close=True,
                    lease=lease,
                )
            except BinanceAPIError as exc:
                if exc.code != -2013:
                    raise
                lookup_at = datetime.now(UTC).isoformat(timespec="microseconds")
                flat = venue.verify_emergency_flat(
                    close_positions=False,
                    lease=lease,
                )
                flat_at = datetime.now(UTC).isoformat(timespec="microseconds")
                return "unknown", flat, lookup_at, flat_at
            observed = self._apply_observation(
                venue,
                lease,
                action,
                observation,
            )
            return "observed", observed, None, None

        outcome, evidence, lookup_at, flat_at = self._with_lease(inspect)
        if outcome == "observed":
            observed_action = evidence
            return {
                "action": observed_action.to_dict(),
                "resolution": None,
                "resolved_via": "exact_venue_observation",
            }
        terminal_action, resolution = self._action_journal.resolve_unknown_submission(
            action.action_ref,
            owner_user_id=context.owner_user_id,
            resolving_halt_ref=context.halt_ref,
            resolving_owner_epoch=context.owner_epoch,
            account_ref=context.account_ref,
            account_epoch=context.account_epoch,
            operator_user_id=context.owner_user_id,
            operator_auth_audit_ref=operator_auth_audit_ref,
            lookup_code=-2013,
            lookup_observed_at_utc=lookup_at,
            flat_verification=evidence,
            flat_observed_at_utc=flat_at,
            expected_action_event_ref=expected_head,
        )
        return {
            "action": terminal_action.to_dict(),
            "resolution": resolution.to_dict(),
            "resolved_via": "manual_unknown_flat",
        }

    def reconcile_emergency_actions_for_halt(
        self,
        context: EmergencyHaltContext,
    ) -> tuple[dict[str, Any], ...]:
        context = self._validated_context(
            context,
            owner_user_id=self.owner_user_id,
            account_ref=self.account_ref,
        )
        if self._action_journal is None:
            raise EmergencyActionError("emergency action journal is unavailable")
        actions = self._action_journal.actions_for_account_epoch(
            owner_user_id=context.owner_user_id,
            account_ref=context.account_ref,
            account_epoch=context.account_epoch,
        )
        resolved: list[dict[str, Any]] = []
        for action in actions:
            current = action
            if action.status == "prepared" and (
                action.halt_ref != context.halt_ref
                or action.owner_epoch != context.owner_epoch
            ):
                current = self._action_journal.mark_pre_submit_superseded(
                    action.action_ref
                )
            if action.status in {"submitting", "acknowledged", "pending"}:
                current = self._observe_action_or_fail_closed(action)
            if current.status in {"submitting", "acknowledged", "pending"}:
                raise EmergencyActionError(
                    f"emergency action {current.action_ref} remains {current.status}"
                )
            resolved.append(current.to_dict())
        return tuple(resolved)

    def close_open_position_for_halt(
        self,
        position: Position,
        context: EmergencyHaltContext,
    ) -> dict[str, Any]:
        context = self._validated_context(
            context,
            owner_user_id=self.owner_user_id,
            account_ref=self.account_ref,
        )
        if self._action_journal is None:
            raise EmergencyActionError("emergency action journal is unavailable")
        if position.quantity == 0:
            raise ValueError("emergency close requires a non-zero position")
        self.reconcile_emergency_actions_for_halt(context)
        action = self._action_journal.prepare(
            owner_user_id=context.owner_user_id,
            halt_ref=context.halt_ref,
            owner_epoch=context.owner_epoch,
            account_ref=context.account_ref,
            account_epoch=context.account_epoch,
            credential_binding_ref=self.credential_binding_ref,
            symbol=position.symbol,
            side="sell" if position.quantity > 0 else "buy",
            quantity=abs(float(position.quantity)),
        )
        if action.status == "reconciled":
            return action.to_dict()
        if action.status in {"submitting", "acknowledged", "pending"}:
            observed = self._observe_action_or_fail_closed(action)
            if observed.status != "reconciled":
                raise EmergencyActionError(
                    f"emergency action remains {observed.status}; new POST denied"
                )
            return observed.to_dict()
        if action.status in {"failed", "terminal_partial", "filled_residual"}:
            # prepare normally advances either terminal state to a fresh attempt.
            raise EmergencyActionError("terminal emergency action did not advance to a new attempt")
        if action.status == "manual_unknown_flat":
            raise EmergencyActionError(
                "unknown historical submission is permanently non-retryable; fresh POST denied"
            )

        def submit(venue: LeasedBinanceVenue, lease: Any) -> EmergencyCloseAction:
            claimed = self._action_journal.mark_submitting(action.action_ref)
            request_params = claimed.request_params()
            response = venue.close_prepared_emergency_request(
                request_params=request_params,
                request_hash=claimed.request_hash,
                lease=lease,
            )
            acknowledged = self._action_journal.mark_acknowledged(
                claimed.action_ref,
                venue_order_id=str(response.get("order_id") or ""),
                response_hash=str(response.get("response_hash") or ""),
                cumulative_filled_qty=response.get("filled_quantity"),
                terminal_status=str(response.get("status") or ""),
            )
            return self._observe_action(venue, lease, acknowledged)

        reconciled = self._with_lease(submit)
        if reconciled.status != "reconciled":
            raise EmergencyActionError(
                f"emergency action remains {reconciled.status} after venue response"
            )
        return reconciled.to_dict()

    def close_open_position(self, position: Position) -> dict[str, Any]:
        if self._action_journal is not None:
            raise PermissionError(
                "journaled mainnet emergency close requires an exact durable HALT context"
            )
        return self._with_lease(
            lambda venue, lease: venue.close_open_position(position, lease=lease)
        )

    def verify_emergency_flat(self, *, close_positions: bool = True) -> dict[str, Any]:
        return self._with_lease(
            lambda venue, lease: venue.verify_emergency_flat(
                close_positions=close_positions,
                lease=lease,
            )
        )

    def account_equity(self) -> float:
        total = float(self._with_lease(lambda venue, lease: venue.margin_equity(lease=lease)))
        if total <= 0:
            raise ValueError(f"account {self.account_ref} has no positive margin equity")
        return total

    def execution_observation(
        self,
        symbol: str,
        *,
        ip_allowlist_ref: str,
        hmac_replay_protection_ref: str,
        rate_limit_ref: str,
    ) -> AccountExecutionObservation:
        """Fetch a source-bound account/risk/safety snapshot without trading."""

        for field_name, value in (
            ("ip_allowlist_ref", ip_allowlist_ref),
            ("hmac_replay_protection_ref", hmac_replay_protection_ref),
            ("rate_limit_ref", rate_limit_ref),
        ):
            if not str(value or "").strip():
                raise ValueError(f"execution observation requires {field_name}")

        raw = self._with_lease(
            lambda venue, lease: venue.execution_account_snapshot(symbol, lease=lease),
            action="verify_account_identity",
        )
        if not isinstance(raw, dict):
            raise TypeError("execution account snapshot returned a non-object")
        venue_account_uid = str(raw.get("account_uid") or "").strip()
        if raw.get("account_identity_source") != "fapi_v2_balance.accountAlias":
            raise PermissionError("exchange account identity is not sourced from the documented accountAlias")
        if raw.get("position_mode") != "one_way":
            raise PermissionError("exchange account position mode is not one-way")
        if raw.get("can_trade") is not True:
            raise PermissionError("exchange account does not prove canTrade=true")
        if raw.get("multi_assets_margin") is not False:
            raise PermissionError("exchange account uses unsupported multi-assets margin mode")
        verified_account_ref = self._broker.account_identity_ref(
            venue="binance",
            network=self.network,
            product=self.product,
            venue_account_uid=venue_account_uid,
        )
        if self.account_ref.startswith("exchange_account_uid_") and self.account_ref != verified_account_ref:
            raise PermissionError("authenticated venue account identity changed")
        equity = float(raw.get("equity", 0) or 0)
        mark_price = float(raw.get("mark_price", 0) or 0)
        bid_price = float(raw.get("bid_price", 0) or 0)
        ask_price = float(raw.get("ask_price", 0) or 0)
        maker_fee_bps = float(raw.get("maker_commission_rate", 0) or 0) * 10_000
        taker_fee_bps = float(raw.get("taker_commission_rate", 0) or 0) * 10_000
        funding_rate_bps = float(raw.get("funding_rate", 0) or 0) * 10_000
        numerics = (equity, mark_price, bid_price, ask_price, maker_fee_bps, taker_fee_bps, funding_rate_bps)
        if not all(math.isfinite(value) for value in numerics):
            raise ValueError("execution account snapshot contains non-finite numeric state")
        if equity <= 0 or mark_price <= 0 or bid_price <= 0 or ask_price <= 0 or ask_price < bid_price:
            raise ValueError("execution account snapshot lacks positive equity/mark/book state")
        if maker_fee_bps < 0 or taker_fee_bps < 0:
            raise ValueError("execution account snapshot contains a negative commission rate")

        permission_state = raw.get("permission_state")
        if not isinstance(permission_state, dict):
            raise ValueError("execution account snapshot lacks API permission state")
        warnings = tuple(str(item) for item in raw.get("permission_warnings") or ())
        if warnings:
            raise PermissionError("exchange API permission state contains unresolved warnings")
        if raw.get("ip_restricted") is not True:
            raise PermissionError("exchange API key does not prove an active IP restriction")
        drain_enabled = sorted(
            str(key)
            for key, value in permission_state.items()
            if bool(value)
            and any(token in str(key).lower() for token in ("withdraw", "internaltransfer", "universaltransfer"))
        )
        if drain_enabled:
            raise PermissionError("exchange API key has fund-drain permissions enabled")
        trade_permissions = [
            bool(value)
            for key, value in permission_state.items()
            if any(token in str(key).lower() for token in ("futures", "trade"))
        ]
        if not trade_permissions or not any(trade_permissions):
            raise PermissionError("exchange API key lacks an explicit futures trading permission")

        positions: list[AccountPositionObservation] = []
        for item in raw.get("positions") or ():
            if not isinstance(item, dict):
                raise ValueError("execution account snapshot contains a malformed position")
            position = AccountPositionObservation(
                symbol=str(item.get("symbol") or "").upper(),
                quantity=float(item.get("quantity", 0) or 0),
                entry_price=float(item.get("entry_price", 0) or 0),
                mark_price=float(item.get("mark_price", 0) or 0),
                unrealized_pnl=float(item.get("unrealized_pnl", 0) or 0),
                leverage=float(item.get("leverage", 0) or 0),
                liquidation_price=float(item.get("liquidation_price", 0) or 0),
                margin_mode=str(item.get("margin_mode") or "").lower(),
            )
            if not position.symbol or position.quantity == 0:
                raise ValueError("execution account snapshot contains an invalid open position")
            if not all(
                math.isfinite(value)
                for value in (
                    position.quantity,
                    position.entry_price,
                    position.mark_price,
                    position.unrealized_pnl,
                    position.leverage,
                    position.liquidation_price,
                )
            ):
                raise ValueError("execution account snapshot contains non-finite position state")
            if position.mark_price <= 0 or position.leverage <= 0 or position.margin_mode not in {"isolated", "cross"}:
                raise ValueError("execution account snapshot contains incomplete position risk state")
            positions.append(position)

        observed_at = datetime.now(UTC).isoformat()
        source_payload = {
            "account_ref": verified_account_ref,
            "symbol": str(symbol or "").upper(),
            "observed_at_utc": observed_at,
            "equity": equity,
            "positions": [position.__dict__ for position in positions],
            "mark_price": mark_price,
            "bid_price": bid_price,
            "ask_price": ask_price,
            "maker_fee_bps": maker_fee_bps,
            "taker_fee_bps": taker_fee_bps,
            "funding_rate_bps": funding_rate_bps,
            "permission_state": permission_state,
            "account_identity_source": raw["account_identity_source"],
            "position_mode": raw["position_mode"],
            "can_trade": raw["can_trade"],
            "multi_assets_margin": raw["multi_assets_margin"],
            "ip_allowlist_ref": ip_allowlist_ref,
            "hmac_replay_protection_ref": hmac_replay_protection_ref,
            "rate_limit_ref": rate_limit_ref,
        }
        snapshot_hash = content_hash(source_payload)
        return AccountExecutionObservation(
            account_ref=verified_account_ref,
            observed_at_utc=observed_at,
            source_ref="account_execution_snapshot_" + snapshot_hash,
            equity=equity,
            positions=tuple(positions),
            mark_price=mark_price,
            bid_price=bid_price,
            ask_price=ask_price,
            maker_fee_bps=maker_fee_bps,
            taker_fee_bps=taker_fee_bps,
            funding_rate_bps=funding_rate_bps,
            credential_check_ref="credential_check_" + snapshot_hash,
            ip_allowlist_ref=ip_allowlist_ref,
            withdrawal_disabled_ref="withdrawal_disabled_" + content_hash(permission_state),
            hmac_replay_protection_ref=hmac_replay_protection_ref,
            health_check_ref="account_health_" + snapshot_hash,
            rate_limit_ref=rate_limit_ref,
            account_identity_source="fapi_v2_balance.accountAlias",
            position_mode="one_way",
            can_trade=True,
            multi_assets_margin=False,
            permission_warnings=warnings,
        )


class ActiveEmergencyVenueRegistry:
    """Thread-safe active-account registry consumed dynamically by KillSwitch."""

    def __init__(self) -> None:
        self._handles: dict[str, BrokeredEmergencyBinanceVenue] = {}
        self._lock = threading.RLock()

    def register(self, handle: BrokeredEmergencyBinanceVenue) -> None:
        with self._lock:
            existing = self._handles.get(handle.account_ref)
            if existing is not None and (
                existing.name != handle.name or existing.owner_user_id != handle.owner_user_id
                or existing.keystore_name != handle.keystore_name
                or existing.credential_binding_ref != handle.credential_binding_ref
            ):
                raise ValueError(f"emergency account_ref collision: {handle.account_ref}")
            if any(existing.name == handle.name and existing.account_ref != handle.account_ref for existing in self._handles.values()):
                raise ValueError(f"emergency venue name collision: {handle.name}")
            self._handles[handle.account_ref] = handle

    def unregister(self, account_ref: str) -> bool:
        with self._lock:
            return self._handles.pop(str(account_ref), None) is not None

    def unregister_for_user(self, owner_user_id: str, account_ref: str) -> bool:
        owner = str(owner_user_id or "")
        with self._lock:
            handle = self._handles.get(str(account_ref))
            if handle is None or handle.owner_user_id != owner:
                return False
            self._handles.pop(str(account_ref), None)
            return True

    def venues(self) -> tuple[BrokeredEmergencyBinanceVenue, ...]:
        with self._lock:
            return tuple(self._handles.values())

    def venues_for_user(self, owner_user_id: str) -> tuple[BrokeredEmergencyBinanceVenue, ...]:
        owner = str(owner_user_id or "").strip()
        if not owner:
            return ()
        with self._lock:
            return tuple(
                handle
                for handle in self._handles.values()
                if handle.owner_user_id == owner
            )

    def account_refs(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._handles))

    def venue(self, account_ref: str) -> BrokeredEmergencyBinanceVenue:
        with self._lock:
            try:
                return self._handles[str(account_ref)]
            except KeyError as exc:
                raise KeyError(f"unknown active emergency account: {account_ref}") from exc

    def venue_for_user(self, owner_user_id: str, account_ref: str) -> BrokeredEmergencyBinanceVenue:
        handle = self.venue(account_ref)
        if handle.owner_user_id != str(owner_user_id or ""):
            raise KeyError(f"unknown active emergency account for owner: {account_ref}")
        return handle

    def equity_observation(self) -> tuple[float, str, str]:
        handles = self.venues()
        if not handles:
            raise ValueError("no active emergency accounts")
        values = [(handle.account_ref, handle.account_equity()) for handle in handles]
        total = sum(value for _, value in values)
        source_ref = "active_emergency_equity:" + content_hash(
            {"accounts": [account_ref for account_ref, _ in values]}
        )
        return total, source_ref, datetime.now(UTC).isoformat()


__all__ = [
    "AccountExecutionObservation",
    "AccountPositionObservation",
    "ActiveEmergencyVenueRegistry",
    "BrokeredEmergencyBinanceVenue",
    "EmergencyHaltContext",
    "EmergencyVenueIdentity",
]
