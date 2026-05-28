import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { authFetch, getStoredUser } from "../../lib/auth";

interface ProfileData {
  user: {
    user_id: string;
    username: string;
    display_name: string;
    bio?: string;
    avatar_url?: string;
    created_at_utc: string;
  };
  followers: number;
  following: number;
  i_follow: boolean;
}

export function UserProfilePage() {
  const me = getStoredUser();
  const { username = "" } = useParams<{ username: string }>();
  const [data, setData] = useState<ProfileData | null>(null);
  const [posts, setPosts] = useState<any[]>([]);
  const [strategies, setStrategies] = useState<any[]>([]);

  const reload = useCallback(() => {
    authFetch(`/api/auth/users/${username}`).then((r) => r.json()).then(setData).catch(() => setData(null));
    authFetch(`/api/community/feed?feed_type=by_author&author=${username}`).then((r) => r.json()).then(setPosts).catch(() => setPosts([]));
    fetch(`/api/sharing/feed?author=${username}`).then((r) => r.json()).then(setStrategies).catch(() => setStrategies([]));
  }, [username]);
  useEffect(reload, [reload]);

  const toggleFollow = async () => {
    if (!me) { alert("请先登录"); return; }
    if (!data) return;
    const method = data.i_follow ? "DELETE" : "POST";
    await authFetch(`/api/community/users/${username}/follow`, { method });
    reload();
  };

  if (!data) {
    return <div className="cc-card cc-dim">加载中 / 用户不存在</div>;
  }

  const isMe = me?.username === username;

  return (
    <>
      <div className="cc-card" style={{ marginBottom: 20, padding: 24 }}>
        <div className="cc-row" style={{ justifyContent: "space-between" }}>
          <div>
            <h1 className="cc-page-title">@{data.user.username}</h1>
            <p className="cc-soft" style={{ fontSize: 14, marginTop: 4 }}>{data.user.display_name}</p>
            {data.user.bio && <p className="cc-soft" style={{ marginTop: 8 }}>{data.user.bio}</p>}
            <div className="cc-row" style={{ gap: 16, marginTop: 12 }}>
              <span className="cc-mono"><b>{data.followers}</b> <span className="cc-dim">关注者</span></span>
              <span className="cc-mono"><b>{data.following}</b> <span className="cc-dim">关注中</span></span>
              <span className="cc-dim" style={{ fontSize: 11 }}>加入 {data.user.created_at_utc.slice(0, 10)}</span>
            </div>
          </div>
          {!isMe && me && (
            <button
              type="button"
              className={`cc-btn ${data.i_follow ? "" : "cc-btn--accent"}`}
              onClick={toggleFollow}
            >
              {data.i_follow ? "✓ 关注中" : "+ 关注"}
            </button>
          )}
        </div>
      </div>

      <div className="cc-tabs">
        <a href="#posts" className="cc-tab active">帖子 ({posts.length})</a>
        <a href="#strategies" className="cc-tab">策略 ({strategies.length})</a>
      </div>

      <section id="posts">
        {posts.length === 0 ? (
          <div className="cc-card cc-dim">该用户还没发过帖子。</div>
        ) : (
          posts.map((p) => (
            <div key={p.post_id} className="cc-card" style={{ marginBottom: 12 }}>
              <div className="cc-dim" style={{ fontSize: 11, marginBottom: 4 }}>{p.created_at_utc.slice(0, 19)}</div>
              <div>{p.content}</div>
              {p.attached_run_id && (
                <Link to={`/runs/${p.attached_run_id}`} className="cc-chip cc-chip--accent" style={{ marginTop: 8, textDecoration: "none" }}>
                  📈 run: {p.attached_run_id}
                </Link>
              )}
            </div>
          ))
        )}
      </section>

      {strategies.length > 0 && (
        <section id="strategies" style={{ marginTop: 24 }}>
          <div className="cc-section-title">公开策略</div>
          <div className="cc-grid">
            {strategies.map((s) => (
              <Link key={s.share_id} to={`/runs/${s.run_id}`} className="cc-card cc-card--hover" style={{ display: "block" }}>
                <div className="cc-card-title">{s.title}</div>
                <div className="cc-dim" style={{ fontSize: 11 }}>{s.run_id} · ❤ {s.likes} · 🔀 {s.forks}</div>
                {s.metric_sharpe != null && <div className="cc-chip cc-chip--accent" style={{ marginTop: 6 }}>sharpe {s.metric_sharpe.toFixed(2)}</div>}
              </Link>
            ))}
          </div>
        </section>
      )}
    </>
  );
}

export default UserProfilePage;
