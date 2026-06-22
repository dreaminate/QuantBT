import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { login, register } from "../../lib/auth";

export function LoginPage({ mode = "login" }: { mode?: "login" | "register" }) {
  const nav = useNavigate();
  const [params] = useSearchParams();
  // 登录后回跳 ?next=（如从定价页升级而来）；只允许站内绝对路径，防开放重定向。
  const next = params.get("next");
  const safeNext = next && next.startsWith("/") && !next.startsWith("//") ? next : "/community";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      if (mode === "login") {
        await login(username, password);
      } else {
        await register(username, password, displayName);
      }
      nav(safeNext);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ maxWidth: 420, margin: "60px auto" }}>
      <div className="cc-card" style={{ padding: 32 }}>
        <h2 className="cc-page-title" style={{ marginBottom: 8 }}>
          <span className="cc-prompt">$</span>
          {mode === "login" ? "login" : "register"}
        </h2>
        <p className="cc-soft" style={{ marginBottom: 20, fontSize: 13 }}>
          {mode === "login" ? "登录到 QuantBT 社区" : "注册新账号（本地 sqlite）"}
        </p>
        <form onSubmit={submit}>
          <div style={{ marginBottom: 12 }}>
            <label className="cc-dim" style={{ fontSize: 11 }}>username</label>
            <input
              className="cc-input"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          {mode === "register" && (
            <div style={{ marginBottom: 12 }}>
              <label className="cc-dim" style={{ fontSize: 11 }}>display name (可选)</label>
              <input
                className="cc-input"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
              />
            </div>
          )}
          <div style={{ marginBottom: 16 }}>
            <label className="cc-dim" style={{ fontSize: 11 }}>password</label>
            <input
              className="cc-input"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {err && <div className="cc-chip cc-chip--danger" style={{ marginBottom: 12 }}>{err}</div>}
          <button type="submit" className="cc-btn cc-btn--accent" disabled={busy} style={{ width: "100%" }}>
            {busy ? "…" : mode === "login" ? "登录" : "创建账号"}
          </button>
        </form>
        <div style={{ marginTop: 16, textAlign: "center", fontSize: 12 }}>
          {mode === "login" ? (
            <Link to="/register" className="cc-soft">没有账号？注册 →</Link>
          ) : (
            <Link to="/login" className="cc-soft">已有账号？登录 →</Link>
          )}
        </div>
        <div className="cc-dim" style={{ marginTop: 16, fontSize: 11, textAlign: "center" }}>
          密码走 PBKDF2-HMAC-SHA256 200k iter · token 走服务端 sessions 表
        </div>
      </div>
    </div>
  );
}

export default LoginPage;
