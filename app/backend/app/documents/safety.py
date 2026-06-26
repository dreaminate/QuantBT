"""文档摄入安全门 —— 外来文档 = RCE-adjacent 攻击面（与外来 pickle 同级·GOAL §6 Source intake）。

威胁模型（外来 PDF/文档可同时是 RCE/SSRF/DoS 载体）：
  - 伪装扩展名：`.pdf` 实为可执行 / 脚本 / 别的容器 → 喂解析器即触发解析器漏洞 → RCE。
  - 外联 / SSRF：解析器去抓远程资源（外部实体、远程图片、嵌入 URL）→ 打内网 / 云元数据 / 外泄。
  - DoS：zip bomb / 解压炸弹 / 超大文件 / 超量页 → 撑爆内存 / CPU。

本模块只放【纯·无副作用·无网络】安全门函数（fail-closed：拿不准一律拒）。门的语义对齐
`training/artifact_trust.py` 的范式（外来字节默认不可信、命中才放行、绝不静默降级），但这是
【文档】侧的独立攻击面，扩展不替换、不碰 pickle 加载路。落盘 / 编排在 `intake.py`、沙箱在
`sandbox.py`。

诚实边界（裁决说「证据 / 边界」，不说「绝对安全」）：
  - magic 嗅探只读文件头部字节，能抓【伪装成文档的可执行 / 脚本 / 异类容器】；不声称能验
    PDF/OOXML 内部结构合法（那是沙箱解析层 + 真解析库的事）。
  - `assert_url_allowed` 是【纯解析】门：校验 scheme / IP 字面私网段 / allowlist 成员，
    【不做 DNS 解析】（no-network 红线，且摄入决策期不该偷偷联网）。allowlist 内的【域名】被
    DNS-rebinding 重绑到私网 IP 这层，须由【抓取层】resolve-and-pin 再核验解析后 IP —— 明确
    标注的领地外 follow-on，本门不声称覆盖。
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class DocumentIntakeError(Exception):
    """外来文档未过摄入安全门：伪装扩展名 / SSRF / 超限(zip bomb·DoS) / 解析沙箱内联网 等。

    与 `artifact_trust.ArtifactTrustError` 平行：外来内容默认不可信，过不了门即【显式 raise·绝不
    静默放行】。致命级（撞「解析器须联网才能解析」之类岔路）由调用方升级为停工报告。
    """


# ── ① MIME / magic 嗅探：抓伪装扩展名（验收 #1） ────────────────────────────────
# 文件头魔数 → 格式 token。按【最长前缀优先】匹配（长签名排前，防短签名误命中）。
# 只用 stdlib（零新依赖、零联网）；不依赖 libmagic / python-magic（避免「解析器须联网/装外部库」岔路）。
_MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    # —— 可执行 / 脚本：文档扩展名下出现【即拒】（这就是 .pdf 实为可执行的攻击）——
    (b"\x7fELF", "executable_elf"),            # Linux ELF
    (b"MZ", "executable_pe"),                  # Windows PE/DOS
    (b"\xca\xfe\xba\xbe", "executable_macho"),  # Mach-O fat / Java class（CAFEBABE）
    (b"\xcf\xfa\xed\xfe", "executable_macho"),  # Mach-O 64 LE
    (b"\xce\xfa\xed\xfe", "executable_macho"),  # Mach-O 32 LE
    (b"\xfe\xed\xfa\xcf", "executable_macho"),  # Mach-O 64 BE
    (b"\xfe\xed\xfa\xce", "executable_macho"),  # Mach-O 32 BE
    (b"#!", "script_shebang"),                 # #!/bin/sh 等脚本
    # —— 合法文档容器 ——
    (b"%PDF-", "pdf"),                          # PDF
    (b"PK\x03\x04", "zip_ooxml"),               # ZIP / docx / xlsx / pptx / epub
    (b"PK\x05\x06", "zip_ooxml"),               # 空 ZIP
    (b"PK\x07\x08", "zip_ooxml"),               # 跨卷 ZIP
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole_legacy"),  # 旧 OLE（.doc/.xls/.ppt）
    (b"{\\rtf", "rtf"),                          # RTF
    (b"<!DOCTYPE html", "html"),
    (b"<!doctype html", "html"),
    (b"<html", "html"),
    (b"<HTML", "html"),
)

# 可执行 / 脚本族：文档语境下绝不允许（无论扩展名声称什么）。
_EXECUTABLE_FORMATS = frozenset(
    {"executable_elf", "executable_pe", "executable_macho", "script_shebang"}
)

# 扩展名 → 允许的格式 token 集合。
#   binary-magic 扩展名（pdf/ooxml/...）：嗅探必须命中其中之一，否则【伪装】→ 拒。
#   text 扩展名（txt/md/csv/...）：允许 text/html/unknown，但仍拒可执行 / 脚本族。
EXTENSION_EXPECTED_FORMATS: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"pdf"}),
    ".docx": frozenset({"zip_ooxml"}),
    ".xlsx": frozenset({"zip_ooxml"}),
    ".pptx": frozenset({"zip_ooxml"}),
    ".epub": frozenset({"zip_ooxml"}),
    ".doc": frozenset({"ole_legacy"}),
    ".xls": frozenset({"ole_legacy"}),
    ".ppt": frozenset({"ole_legacy"}),
    ".rtf": frozenset({"rtf", "text"}),
    ".html": frozenset({"html", "text"}),
    ".htm": frozenset({"html", "text"}),
    ".txt": frozenset({"text", "html"}),
    ".md": frozenset({"text", "html"}),
    ".csv": frozenset({"text"}),
    ".json": frozenset({"text"}),
}

# text 家族扩展名：允许 text/html/unknown（无二进制魔数可比对），只硬拒可执行 / 脚本。
_TEXT_FAMILY_EXTENSIONS = frozenset({".rtf", ".html", ".htm", ".txt", ".md", ".csv", ".json"})

# 嗅探需要的头部字节数（足够容纳上面所有签名 + 一点余量）。
MAGIC_HEAD_BYTES = 64


def sniff_format(head: bytes) -> str:
    """读文件头部魔数，返回格式 token（命不中任何已知签名 → "unknown"）。纯函数·零副作用。"""
    for sig, token in _MAGIC_SIGNATURES:
        if head.startswith(sig):
            return token
    return "unknown"


def assert_mime_matches_extension(*, filename: str, head: bytes) -> str:
    """验收 #1：嗅探出的真实格式与声称扩展名不符（伪装文档）→ 拒。返回嗅探到的格式 token。

    硬规则（fail-closed）：
      1. 嗅探为可执行 / 脚本族 → 【无条件拒】（`.pdf` 实为 ELF/PE/Mach-O/shebang 即此分支）。
      2. binary-magic 扩展名（.pdf/.docx/...）：嗅探格式不在该扩展名期望集 → 拒（伪装成别的容器）。
      3. text 家族扩展名：允许 text/html/unknown，可执行 / 脚本已被规则 1 拦下。
      4. 未知扩展名：仍跑规则 1（可执行 → 拒），其余放行交沙箱解析层（本门不臆断未知类型）。
    """
    fmt = sniff_format(head)
    ext = Path(filename).suffix.lower()

    # 规则 1：可执行 / 脚本族在文档语境下绝不允许（无论扩展名）。
    if fmt in _EXECUTABLE_FORMATS:
        raise DocumentIntakeError(
            f"摄入安全门#1（伪装扩展名）：{filename} 声称是文档，但文件头魔数 = {fmt}"
            "（可执行 / 脚本）→ 拒。外来文档绝不可是可执行体（RCE 攻击面）。"
        )

    expected = EXTENSION_EXPECTED_FORMATS.get(ext)
    if expected is None:
        # 未知扩展名：规则 1 已挡可执行，其余不臆断（交沙箱解析层 + 限额门兜底）。
        return fmt

    if ext in _TEXT_FAMILY_EXTENSIONS:
        # text 家族：text/html/unknown 都放行（无二进制魔数可比对）。
        if fmt in expected or fmt == "unknown":
            return fmt
        raise DocumentIntakeError(
            f"摄入安全门#1（伪装扩展名）：{filename}（text 类）实际魔数 = {fmt}，"
            f"与期望 {sorted(expected)} 不符 → 拒。"
        )

    # binary-magic 扩展名：必须命中期望魔数集，否则伪装（含 head 太短无法确认 → fail-closed 拒）。
    if fmt not in expected:
        raise DocumentIntakeError(
            f"摄入安全门#1（伪装扩展名）：{filename} 扩展名期望 {sorted(expected)}，"
            f"但文件头魔数 = {fmt} → 拒（伪装文档 / 头部损坏，外来内容不可信）。"
        )
    return fmt


# ── ② URL allowlist / SSRF 门（验收 #2 上半：URL 不在 allowlist / 私网即拒） ──────
# 本地 / 内网指代名（非 IP 字面，DNS 会指向 loopback / 内网）：直接列入硬拒名单。
_LOCAL_HOST_NAMES = frozenset({"localhost", "ip6-localhost", "ip6-loopback"})
_LOCAL_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")
_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


def assert_url_allowed(url: str, *, allowlist: frozenset[str] | set[str] | tuple[str, ...]) -> None:
    """验收 #2：只放行 http(s) + host 命中 allowlist + 非私网字面 IP；其余一律拒（防 SSRF / 外联）。

    fail-closed 逐层（任一不过即 raise）：
      1. scheme ∈ {http, https}（拒 file:// gopher:// data:// ftp:// 等 SSRF 常用 scheme）。
      2. host 非空。
      3. host 是 IP 字面且非全局可路由（loopback/私网/link-local/CGNAT/保留/未指定）→ 拒
         （挡 169.254.169.254 云元数据、127.0.0.1、10.x、::1 等经典 SSRF 目标）。
      4. host 是本地指代名（localhost / *.internal / *.local ...）→ 拒。
      5. host（或其父域）须在 allowlist —— 默认拒，白名单制（非黑名单）。

    诚实边界：不做 DNS（no-network 红线）。allowlist 内域名被 DNS-rebinding 重绑私网这层须由
    抓取层 resolve-and-pin 兜底（领地外 follow-on）。本门拦的是【URL 自身可判】的 SSRF 面。
    """
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in _ALLOWED_URL_SCHEMES:
        raise DocumentIntakeError(
            f"摄入安全门#2（SSRF）：URL scheme={scheme!r} 不在 {sorted(_ALLOWED_URL_SCHEMES)} → 拒"
            f"（{url!r}；file/gopher/data/ftp 等是 SSRF 常用外联面）。"
        )

    host = (parts.hostname or "").lower()
    if not host:
        raise DocumentIntakeError(f"摄入安全门#2（SSRF）：URL 无 host → 拒（{url!r}）。")

    # IP 字面 → 必须全局可路由，否则私网 / 元数据端点 SSRF。
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None and not addr.is_global:
        raise DocumentIntakeError(
            f"摄入安全门#2（SSRF）：host={host} 是非全局 IP（私网 / loopback / link-local / 保留）→ 拒"
            "（防打内网 / 云元数据 169.254.169.254）。"
        )

    # 本地 / 内网指代名（DNS 会指回本机或内网）。
    if host in _LOCAL_HOST_NAMES or host.endswith(_LOCAL_HOST_SUFFIXES):
        raise DocumentIntakeError(
            f"摄入安全门#2（SSRF）：host={host} 是本地 / 内网指代名 → 拒。"
        )

    allow = {h.lower() for h in allowlist}
    if not _host_in_allowlist(host, allow):
        raise DocumentIntakeError(
            f"摄入安全门#2（allowlist）：host={host} 不在 allowlist {sorted(allow)} → 拒"
            "（白名单制·默认拒，防任意外联 / SSRF）。"
        )


def _host_in_allowlist(host: str, allow: set[str]) -> bool:
    """host 精确命中 allowlist 条目，或为其子域（host endswith '.'+entry）。"""
    if host in allow:
        return True
    return any(host.endswith("." + entry) for entry in allow)


# ── ③ no-network 解析门（验收 #2 下半：解析器尝试联网 → 拒） ─────────────────────
import socket as _socket  # noqa: E402 —— 放在常量后，避免被误当顶层依赖排序


def _blocked_network(*_a: object, **_k: object) -> None:
    raise DocumentIntakeError(
        "摄入安全门（no-network parser 红线）：解析沙箱内禁止任何网络访问。"
        "外来文档解析器绝不允许外联（防 SSRF / 远程外部实体 / 数据外泄）。"
        "若某解析路径【必须】联网才能解析 → 这是红线岔路，停工报告中心，绝不放行。"
    )


@contextmanager
def no_network() -> Iterator[None]:
    """进程级 fail-closed 网络封锁上下文：块内任何 socket 出口 → raise DocumentIntakeError。

    封堵高层 HTTP 库共同漏斗 + 裸 socket：
      - `socket.getaddrinfo`（域名解析，urllib/requests/httpx 联网前必经）；
      - `socket.create_connection`（stdlib http.client 出口）；
      - `socket.socket.connect` / `connect_ex`（裸 socket，含 IP 字面直连）。
    try/finally 还原，绝不泄漏全局态。

    诚实边界（不说「绝对隔离」）：这是【同进程 best-effort】门，挡住 socket 层出口，覆盖
    urllib / requests / httpx / aiohttp / 裸 socket 等现实路径。绕过面（ctypes 直发 syscall、
    fork 子进程后自己建 socket）需【OS 级沙箱】（seccomp / network namespace / 无网容器）根除
    —— 明确标注的 follow-on。本门兑现的是「in-process 解析器无法 socket 外联」。
    """
    saved = (
        _socket.getaddrinfo,
        _socket.create_connection,
        _socket.socket.connect,
        _socket.socket.connect_ex,
    )
    _socket.getaddrinfo = _blocked_network  # type: ignore[assignment]
    _socket.create_connection = _blocked_network  # type: ignore[assignment]
    _socket.socket.connect = _blocked_network  # type: ignore[assignment,method-assign]
    _socket.socket.connect_ex = _blocked_network  # type: ignore[assignment,method-assign]
    try:
        yield
    finally:
        (
            _socket.getaddrinfo,
            _socket.create_connection,
            _socket.socket.connect,
            _socket.socket.connect_ex,
        ) = saved  # type: ignore[assignment,method-assign]


# ── ④ size / page / compression 限额门（验收 #3：zip bomb / DoS） ────────────────
@dataclass(frozen=True)
class IntakeLimits:
    """摄入限额（DoS / zip bomb 防线）。默认值偏保守，调用方可按场景放宽 / 收紧。"""

    max_bytes: int = 64 * 1024 * 1024          # 单文档原始字节上限（64 MiB）
    max_pages: int = 5_000                      # 解析后页数上限（页炸弹）
    max_archive_entries: int = 10_000           # 容器（OOXML/zip）内条目数上限
    max_uncompressed_bytes: int = 1024 * 1024 * 1024  # 容器解压后总字节上限（1 GiB）
    max_compression_ratio: float = 200.0        # 解压后 / 压缩前 比上限（zip bomb 核心指标）

    def __post_init__(self) -> None:
        for name in (
            "max_bytes", "max_pages", "max_archive_entries", "max_uncompressed_bytes",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"IntakeLimits.{name} 必须 > 0")
        if self.max_compression_ratio <= 1.0:
            raise ValueError("IntakeLimits.max_compression_ratio 必须 > 1.0")


def check_size(n_bytes: int, limits: IntakeLimits) -> None:
    """原始字节超 max_bytes → 拒（超大文件 DoS）。"""
    if n_bytes > limits.max_bytes:
        raise DocumentIntakeError(
            f"摄入安全门#3（DoS·size）：原始 {n_bytes} 字节 > 上限 {limits.max_bytes} → 拒。"
        )


def check_pages(n_pages: int, limits: IntakeLimits) -> None:
    """解析后页数超 max_pages → 拒（页炸弹 DoS）。"""
    if n_pages > limits.max_pages:
        raise DocumentIntakeError(
            f"摄入安全门#3（DoS·pages）：页数 {n_pages} > 上限 {limits.max_pages} → 拒。"
        )


def inspect_archive_safety(data: bytes, limits: IntakeLimits) -> None:
    """OOXML / zip 容器：只读【中央目录】（绝不解压）估算解压后体量 / 条目数 / 压缩比 → 抓 zip bomb。

    用 stdlib `zipfile` 读 infolist（不触发解压，故对炸弹安全）；据 file_size（解压后声明值）求和：
      - 条目数 > max_archive_entries → 拒；
      - 解压后总字节 > max_uncompressed_bytes → 拒；
      - 解压后 / 压缩前 比 > max_compression_ratio → 拒（zip bomb 核心特征）。
    非 zip 容器（魔数不是 PK）直接返回（该路径由 size 门 + 解析沙箱兜底）。
    损坏 / 异常 zip → 拒（fail-closed：外来容器解析不开即不可信）。
    """
    import io
    import zipfile

    if not data.startswith(b"PK"):
        return  # 非 zip 容器：本门不适用（size 门 + sandbox 兜底）。

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile as e:
        raise DocumentIntakeError(
            "摄入安全门#3（DoS·archive）：容器声称 zip/OOXML 但中央目录读取失败 → 拒"
            f"（损坏 / 伪装，外来容器不可信）。原因：{e}"
        ) from e

    if len(infos) > limits.max_archive_entries:
        raise DocumentIntakeError(
            f"摄入安全门#3（DoS·archive）：容器条目数 {len(infos)} > 上限 "
            f"{limits.max_archive_entries} → 拒（zip bomb / 海量小文件）。"
        )

    total_uncompressed = sum(i.file_size for i in infos)
    if total_uncompressed > limits.max_uncompressed_bytes:
        raise DocumentIntakeError(
            f"摄入安全门#3（DoS·archive）：容器解压后总计 {total_uncompressed} 字节 > 上限 "
            f"{limits.max_uncompressed_bytes} → 拒（解压炸弹）。"
        )

    compressed = max(len(data), 1)
    ratio = total_uncompressed / compressed
    if ratio > limits.max_compression_ratio:
        raise DocumentIntakeError(
            f"摄入安全门#3（DoS·archive）：解压 / 压缩比 {ratio:.1f} > 上限 "
            f"{limits.max_compression_ratio} → 拒（zip bomb 核心特征）。"
        )


__all__ = [
    "EXTENSION_EXPECTED_FORMATS",
    "MAGIC_HEAD_BYTES",
    "DocumentIntakeError",
    "IntakeLimits",
    "assert_mime_matches_extension",
    "assert_url_allowed",
    "check_pages",
    "check_size",
    "inspect_archive_safety",
    "no_network",
    "sniff_format",
]
