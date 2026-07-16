"""对抗测试：凭据 dataclass 的 repr / str 永不泄露 api_key / api_secret 明文。

背景：红线安全审计（A股永不实盘 + 凭据不泄露复核，2026-07-15）发现
KeystoreRecord（security/keystore.py）与 BinanceCredentials（execution/binance_client.py）
是裸 @dataclass、无 __repr__ 打码——Python 默认 dataclass repr 会把
``api_key='真key' api_secret='真secret'`` 明文渲染。当前无代码路径 repr 它们（潜伏非活跃、
非确认泄露），但生产 traceback 捕获 locals、debugger、未来某行日志都会泄露。本测试把
「没人 repr 它就安全」的隐式脆弱不变量转成「构造即安全」的显式门。

镜现有约定 MaterializedCredential.__repr__（llm/credential_pool.py:123-127，
``api_key=<redacted>`` + ``__str__ = __repr__``）。

种坏门（mutation）：移除任一 __repr__ → @dataclass 生成的默认 repr 含明文 →
本文件相应断言翻红。
"""

from app.execution.binance_client import BinanceCredentials
from app.execution.binance_ws import WSStreamerState
from app.security.keystore import KeystoreRecord

# 独特哨兵值：若出现在 repr / str / 容器 repr 里即证泄露
_SENTINEL_KEY = "AKIA_SENTINEL_KEY_9c1f_do_not_leak"
_SENTINEL_SECRET = "SECRET_SENTINEL_7b3e_do_not_leak"
_SENTINEL_LISTEN_KEY = "LISTENKEY_SENTINEL_2d5a_do_not_leak"


def test_keystore_record_repr_redacts_secrets():
    rec = KeystoreRecord(
        name="binance_mainnet",
        api_key=_SENTINEL_KEY,
        api_secret=_SENTINEL_SECRET,
        note="prod",
    )
    for rendered in (repr(rec), str(rec), f"{rec}"):
        assert _SENTINEL_KEY not in rendered, "api_key 明文泄露进 repr/str"
        assert _SENTINEL_SECRET not in rendered, "api_secret 明文泄露进 repr/str"
        assert "<redacted>" in rendered
    # 打码只在 repr——真数据仍可门后访问、序列化（to_dict 供后端加密存储）
    assert rec.api_key == _SENTINEL_KEY
    assert rec.api_secret == _SENTINEL_SECRET
    assert rec.to_dict()["api_secret"] == _SENTINEL_SECRET
    # 非密标识字段仍在（repr 仍可用于调试）
    assert "binance_mainnet" in repr(rec)


def test_keystore_record_redacted_inside_container_repr():
    # 现实泄露向量：日志常打容器（list/dict），容器 repr 递归调用元素 __repr__。
    rec = KeystoreRecord(name="x", api_key=_SENTINEL_KEY, api_secret=_SENTINEL_SECRET)
    assert _SENTINEL_KEY not in repr([rec])
    assert _SENTINEL_SECRET not in repr([rec])
    assert _SENTINEL_KEY not in repr({"cred": rec})
    assert _SENTINEL_SECRET not in repr({"cred": rec})


def test_binance_credentials_repr_redacts_secrets():
    cred = BinanceCredentials(
        api_key=_SENTINEL_KEY,
        api_secret=_SENTINEL_SECRET,
        network="mainnet",
    )
    for rendered in (repr(cred), str(cred), f"{cred}"):
        assert _SENTINEL_KEY not in rendered, "api_key 明文泄露进 repr/str"
        assert _SENTINEL_SECRET not in rendered, "api_secret 明文泄露进 repr/str"
        assert "<redacted>" in rendered
    assert cred.api_key == _SENTINEL_KEY
    assert cred.api_secret == _SENTINEL_SECRET
    assert "mainnet" in repr(cred)


def test_binance_credentials_redacted_inside_container_repr():
    cred = BinanceCredentials(api_key=_SENTINEL_KEY, api_secret=_SENTINEL_SECRET)
    assert _SENTINEL_KEY not in repr([cred])
    assert _SENTINEL_SECRET not in repr({"c": cred})


def test_binance_credentials_from_record_also_redacts():
    # from_record 从 KeystoreRecord 搬明文——搬出来的对象同样不许 repr 泄露
    rec = KeystoreRecord(
        name="binance_testnet",
        api_key=_SENTINEL_KEY,
        api_secret=_SENTINEL_SECRET,
    )
    cred = BinanceCredentials.from_record(rec, network="testnet")
    for rendered in (repr(cred), str(cred)):
        assert _SENTINEL_KEY not in rendered
        assert _SENTINEL_SECRET not in rendered
    assert cred.api_key == _SENTINEL_KEY  # 真数据仍搬到位


# ---- WSStreamerState.listen_key：Binance WS user-data bearer 凭据（跨厂商 skeptic 逮出的第三个泄露向量）----


def test_ws_streamer_state_repr_redacts_listen_key():
    st = WSStreamerState(listen_key=_SENTINEL_LISTEN_KEY, connected=True, reconnect_count=3)
    for rendered in (repr(st), str(st), f"{st}"):
        assert _SENTINEL_LISTEN_KEY not in rendered, "listen_key 明文泄露进 repr/str"
        assert "<redacted>" in rendered
        # 运维诊断字段应仍可见（打码只针对 listen_key）
        assert "connected=True" in rendered
        assert "reconnect_count=3" in rendered
    # 真值仍可门后访问（WS 用它拼 URL）
    assert st.listen_key == _SENTINEL_LISTEN_KEY


def test_ws_streamer_state_redacted_inside_container_repr():
    st = WSStreamerState(listen_key=_SENTINEL_LISTEN_KEY)
    assert _SENTINEL_LISTEN_KEY not in repr([st])
    assert _SENTINEL_LISTEN_KEY not in repr({"state": st})


def test_ws_streamer_state_empty_listen_key_not_redacted_marker():
    # 空 listen_key 渲染为 ''（非 <redacted>），保留「是否已取 key」的诊断信号且不泄露
    st = WSStreamerState()
    assert "<redacted>" not in repr(st)
    assert "listen_key=''" in repr(st)


# ═══════════════════════════════════════════════════════════════════════════
# 系统性凭据 repr 泄露封堵（红线审计 + 双厂商复审，2026-07-15）
# ---------------------------------------------------------------------------
# 探针化清单：裸 @dataclass / Pydantic 的 secret 字段经默认 repr/str/%s/traceback
# 明文渲染。修法：dataclass 用 field(repr=False)、Pydantic v2 用 Field(repr=False)——
# 只堵「意外暴露」(repr / str / f-string / 容器 repr / error-string)；功能序列化
# (model_dump / to_dict / asdict) 是显式访问边界，保留不动（签名 / 持久化 / 传输合法要用）。
# 每测种坏门：拿掉对应 field(repr=False) / Field(repr=False) / _redact_secret 即翻红。
# 函数内 import：某模块可选依赖漂移时，新测各自独立可收集，不牵连上面 8 个既有测。
# ═══════════════════════════════════════════════════════════════════════════

_S_TS_TOKEN = "TUSHARE_TOKEN_SENTINEL_a1b2_do_not_leak"
_S_GW_SECRET = "GWSECRET_SENTINEL_c3d4_do_not_leak"
_S_KNOWN_SECRET = "KNOWNSECRET_SENTINEL_e5f6_do_not_leak"
_S_HMAC_TOKEN = "HMACTOKEN_SENTINEL_1122_do_not_leak"
_S_LLM_CRED = "LLMCRED_SENTINEL_3344_do_not_leak"
_S_LLM_PREVIEW = "PREVIEWSECRET_SENTINEL_7788_do_not_leak"
_S_CAP_SIG = "CAPSIG_SENTINEL_99aa_do_not_leak"
_S_AUTH_STATIC = "AUTHSTATIC_SENTINEL_bbcc_do_not_leak"
_S_LK2 = "LISTENKEY2_SENTINEL_ddee_do_not_leak"


def test_token_client_repr_redacts_token():
    # HIGH：活跃 Tushare pull 每次拼请求都持 token；repr/str/%s/traceback 泄露即真泄露
    from app.tushare_quant1.tushare_provider import TokenClient

    tc = TokenClient(slot=1, token=_S_TS_TOKEN, token_mask="ab****yz", points=2000,
                     expires_at=None, ts_module=None, pro_client=None)
    for rendered in (repr(tc), str(tc), f"{tc}", repr([tc]), repr({"c": tc})):
        assert _S_TS_TOKEN not in rendered, "tushare token 明文泄露进 repr/str/容器"
    # 掩码仍在（诊断可用）+ 真值门后可访问（活跃 pull 要用）
    assert "ab****yz" in repr(tc)
    assert tc.token == _S_TS_TOKEN


def test_release_candidate_repr_redacts_gateway_and_known_secrets():
    from app.release_gate.release_gate import ReleaseCandidate

    rc = ReleaseCandidate(asset_ref="asset-x", gateway_secret=_S_GW_SECRET.encode(),
                          known_secrets=(_S_KNOWN_SECRET,))
    for rendered in (repr(rc), str(rc), repr([rc])):
        assert _S_GW_SECRET not in rendered, "gateway_secret 明文泄露进 repr"
        assert _S_KNOWN_SECRET not in rendered, "known_secrets 明文泄露进 repr"
    # 非密标识字段仍在 + 真值门后可访问（release gate 功能要用）
    assert "asset-x" in repr(rc)
    assert rc.gateway_secret == _S_GW_SECRET.encode()
    assert rc.known_secrets == (_S_KNOWN_SECRET,)


def test_node_execution_context_repr_redacts_token():
    from app.agent.orchestrator.governance import NodeExecutionContext

    ctx = NodeExecutionContext(node_id="n1", task_id="t1", role="factor",
                               permitted_tools=frozenset({"read_dataset"}), token=_S_HMAC_TOKEN)
    for rendered in (repr(ctx), str(ctx), repr([ctx])):
        assert _S_HMAC_TOKEN not in rendered, "HMAC 准入令牌明文泄露进 repr"
    # 诊断字段仍在 + 真值门后可访问（dispatcher verify 要用）
    assert "n1" in repr(ctx)
    assert ctx.token == _S_HMAC_TOKEN


def test_llm_provider_record_repr_redacts_plaintext_credential():
    from app.research_os.onboarding_gateway import LLMProviderRecord

    rec = LLMProviderRecord(
        provider_id="prov-1", provider_type="openai", auth_methods=("api_key",), base_url="https://x",
        model_profiles=(), capability_tags=(), context_window=128000, tool_calling_support=True,
        structured_output_support=True, cost_model_ref="cm", rate_limits="rl",
        data_retention_policy="dr", region_residency="us", allowed_roles=(), allowed_desks=(),
        health_status="ok", quota_status="ok", auth_refs=(), plaintext_credential=_S_LLM_CRED)
    for rendered in (repr(rec), str(rec), repr([rec])):
        assert _S_LLM_CRED not in rendered, "LLM provider 凭据明文泄露进 repr"
    assert "prov-1" in repr(rec)
    assert rec.plaintext_credential == _S_LLM_CRED


def test_llm_gateway_call_request_repr_redacts_credential_and_preview():
    from app.research_os.onboarding_gateway import LLMGatewayCallRequest

    req = LLMGatewayCallRequest(
        role_agent="factor", desk="alpha", task_type="score", provider_id="p", model_id="m",
        routing_policy_ref="rp", credential_pool_ref="cp", auth_ref="ar", via_gateway=True,
        plaintext_credential=_S_LLM_CRED, payload_preview={"prompt": _S_LLM_PREVIEW})
    for rendered in (repr(req), str(req), repr([req])):
        assert _S_LLM_CRED not in rendered, "plaintext_credential 明文泄露进 repr"
        assert _S_LLM_PREVIEW not in rendered, "payload_preview 内嵌 secret 泄露进 repr"
    assert req.plaintext_credential == _S_LLM_CRED
    assert req.payload_preview == {"prompt": _S_LLM_PREVIEW}


def test_capability_token_repr_redacts_sig_but_model_dump_keeps_it():
    from app.security.gate.broker import CapabilityToken

    cap = CapabilityToken(cap_id="cap-1", action="request_live_order", gate_ref="gate-1",
                          keystore_name="binance_mainnet",
                          expires_at_utc="2999-01-01T00:00:00+00:00", sig=_S_CAP_SIG)
    for rendered in (repr(cap), str(cap), repr([cap])):
        assert _S_CAP_SIG not in rendered, "capability HMAC sig 明文泄露进 repr"
    assert "cap-1" in repr(cap)
    # 功能边界：sig 必须仍在 model_dump——verify_capability 靠它核签。防「用 exclude 洗白 repr」的错误修法翻绿
    assert cap.model_dump()["sig"] == _S_CAP_SIG
    assert cap.sig == _S_CAP_SIG


def test_auth_spec_repr_redacts_static_value():
    from app.connectors.generic_rest import _AuthSpec

    spec = _AuthSpec(mode="header", header_name="X-API-KEY", static_value=_S_AUTH_STATIC)
    for rendered in (repr(spec), str(spec), repr([spec]), repr({"a": spec})):
        assert _S_AUTH_STATIC not in rendered, "connector static_value 明文泄露进 repr"
    # 功能边界：model_dump 仍带 static_value（connector 建请求 / 配置 round-trip 要用）
    assert spec.model_dump()["static_value"] == _S_AUTH_STATIC
    assert spec.static_value == _S_AUTH_STATIC


def test_generic_rest_config_repr_redacts_embedded_static_value():
    # GenericRESTConfig 内嵌 _AuthSpec —— 容器 repr 递归调子对象 repr，须一并不泄露（transitive 修复）
    from app.connectors.generic_rest import GenericRESTConfig, _AuthSpec

    spec = _AuthSpec(mode="header", header_name="X-API-KEY", static_value=_S_AUTH_STATIC)
    cfg = GenericRESTConfig(connector_name="c", label="l", base_url="https://x", auth=spec, endpoints={})
    for rendered in (repr(cfg), str(cfg), repr([cfg])):
        assert _S_AUTH_STATIC not in rendered, "内嵌 _AuthSpec.static_value 经 GenericRESTConfig repr 泄露"
    assert cfg.auth.static_value == _S_AUTH_STATIC


# ---- WSStreamerState.last_error：listen_key 内嵌请求 URL，异常文本经 last_error → snapshot() 外流 ----


class _FakeBinanceClientRaising:
    """product=spot 使 renew 走 public() 路径；两法都抛内嵌 listen_key 的异常（模拟 URL-in-exception 泄露）。"""

    product = "spot"
    network = "testnet"

    def __init__(self, listen_key: str) -> None:
        self._lk = listen_key

    def public(self, *_a, **_k):
        raise RuntimeError(f"HTTPError PUT https://x/api/v3/userDataStream?listenKey={self._lk} -> 500")

    def signed(self, *_a, **_k):
        raise RuntimeError(f"conn reset wss://x/ws/{self._lk} (openOrders)")


def test_ws_streamer_last_error_redacts_listen_key_on_renew():
    from app.execution.binance_ws import BinanceUserDataStream

    stream = BinanceUserDataStream(_FakeBinanceClientRaising(_S_LK2))
    stream._state.listen_key = _S_LK2
    assert stream.renew_listen_key() is False
    # last_error（+ 经 snapshot 外流）不得含 listen_key，且打码标记在
    assert _S_LK2 not in stream._state.last_error
    assert _S_LK2 not in stream.snapshot()["last_error"]
    assert "<lk-redacted>" in stream._state.last_error


def test_ws_streamer_last_error_redacts_listen_key_on_reconcile():
    from app.execution.binance_ws import BinanceUserDataStream

    stream = BinanceUserDataStream(_FakeBinanceClientRaising(_S_LK2))
    stream._state.listen_key = _S_LK2
    stream.reconcile_once()
    assert _S_LK2 not in (stream._state.last_error or "")
    assert _S_LK2 not in (stream.snapshot()["last_error"] or "")


def test_ws_streamer_on_error_redacts_listen_key_in_state_and_audit():
    from app.execution.binance_ws import BinanceUserDataStream

    stream = BinanceUserDataStream(_FakeBinanceClientRaising(_S_LK2))
    stream._state.listen_key = _S_LK2
    stream._on_error(None, RuntimeError(f"handshake failed wss://x/ws/{_S_LK2}"))
    # 两条外流路径都堵：state.last_error（→ snapshot）+ 审计条（→ export）
    assert _S_LK2 not in stream._state.last_error
    assert _S_LK2 not in stream.snapshot()["last_error"]
    assert _S_LK2 not in repr(stream._audit.export())


def test_redact_secret_helper_contract():
    from app.execution.binance_ws import _redact_secret

    # 非空 secret：抹掉每一处出现
    assert _redact_secret(f"url=/ws/{_S_LK2}", _S_LK2) == "url=/ws/<lk-redacted>"
    assert _S_LK2 not in _redact_secret(f"a {_S_LK2} b {_S_LK2} c", _S_LK2)
    # 空 secret：原样返回（不误伤、不把空串当作可匹配子串）
    assert _redact_secret("plain error text", "") == "plain error text"


# ---- P1（跨厂商 skeptic 二轮）：stale-rotated listen_key——异步回调携【旧】key,state 已轮换 ----

_S_LK_OLD = "LISTENKEY_OLD_SENTINEL_aa11_do_not_leak"
_S_LK_NEW = "LISTENKEY_NEW_SENTINEL_bb22_do_not_leak"


class _FakeBinanceClientReturningKeys:
    """create_listen_key（spot 走 public）依次返回不同 listenKey——模拟 key 轮换。"""

    product = "spot"
    network = "testnet"

    def __init__(self, keys) -> None:
        self._keys = list(keys)
        self._i = 0

    def public(self, *_a, **_k):
        key = self._keys[min(self._i, len(self._keys) - 1)]
        self._i += 1
        return {"listenKey": key}

    def signed(self, *_a, **_k):
        return self.public()


def test_ws_streamer_on_error_redacts_STALE_rotated_listen_key():
    # P1：老连接 _on_error 携【旧】key,而 state.listen_key 已轮换到【新】key。
    # 只打码当前 key 会漏旧 key（→ snapshot / audit export 外流）——必须按签发历史全打码。
    from app.execution.binance_ws import BinanceUserDataStream

    stream = BinanceUserDataStream(_FakeBinanceClientReturningKeys([_S_LK_OLD, _S_LK_NEW]))
    k1 = stream.create_listen_key()  # 旧 key → 进签发历史
    k2 = stream.create_listen_key()  # 新 key → state 轮换
    assert k1 == _S_LK_OLD and k2 == _S_LK_NEW
    assert stream._state.listen_key == _S_LK_NEW  # 确已轮换
    stream._on_error(None, RuntimeError(f"stale conn wss://x/ws/{_S_LK_OLD} closed"))
    assert _S_LK_OLD not in stream._state.last_error, "stale-rotated listen_key 泄露(P1)"
    assert _S_LK_OLD not in stream.snapshot()["last_error"]
    assert _S_LK_OLD not in repr(stream._audit.export())
    assert "<lk-redacted>" in stream._state.last_error


def test_ws_streamer_reconcile_loop_site_redacts_listen_key():
    # 种坏门覆盖 _reconcile_loop call-site（此前无直接测——拿掉该 self._redact 包裹即翻红）
    from unittest.mock import MagicMock

    from app.execution.binance_ws import BinanceUserDataStream

    stream = BinanceUserDataStream(_FakeBinanceClientRaising(_S_LK2))
    stream._state.listen_key = _S_LK2
    stream.reconcile_once = MagicMock(side_effect=RuntimeError(f"reconcile wss://x/ws/{_S_LK2}"))
    stream._stop_event.wait = MagicMock(side_effect=[False, True])  # 进循环一次 → 退出
    stream._reconcile_loop()
    assert _S_LK2 not in (stream._state.last_error or ""), "reconcile_loop call-site 未打码"
    assert "<lk-redacted>" in (stream._state.last_error or "")


def test_ws_streamer_ws_loop_site_redacts_listen_key(monkeypatch):
    # 种坏门覆盖 _ws_loop call-site：注入假 websocket 使 WebSocketApp 构造即抛含 key 的异常
    import sys
    import types
    from unittest.mock import MagicMock

    from app.execution.binance_ws import BinanceUserDataStream

    stream = BinanceUserDataStream(_FakeBinanceClientRaising(_S_LK2))
    stream._state.listen_key = _S_LK2  # truthy → _ws_loop 不调 create_listen_key

    fake_ws = types.ModuleType("websocket")

    def _boom(*_a, **_k):
        raise RuntimeError(f"ws connect fail wss://x/ws/{_S_LK2}")

    fake_ws.WebSocketApp = _boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "websocket", fake_ws)
    stream._stop_event.wait = MagicMock(return_value=True)  # 一次迭代后 break 退出
    stream._ws_loop()
    assert _S_LK2 not in (stream._state.last_error or ""), "ws_loop call-site 未打码"
    assert "<lk-redacted>" in (stream._state.last_error or "")
