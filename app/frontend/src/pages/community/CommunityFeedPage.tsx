import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { authFetch, getStoredUser } from "../../lib/auth";

interface PostItem {
  post_id: string;
  author_id: string;
  author_username: string;
  author_display_name: string;
  content: string;
  tags: string[];
  attached_run_id?: string | null;
  attached_factor_id?: string | null;
  repost_of?: string | null;
  created_at_utc: string;
  likes: number;
  reposts: number;
  comments_count: number;
  liked_by_me: boolean;
}

type FeedType = "recent" | "following" | "hot";

export function CommunityFeedPage() {
  const me = getStoredUser();
  const [feedType, setFeedType] = useState<FeedType>("recent");
  const [posts, setPosts] = useState<PostItem[]>([]);
  const [draft, setDraft] = useState("");
  const [attachRun, setAttachRun] = useState("");
  const [posting, setPosting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const reload = useCallback(() => {
    authFetch(`/api/community/feed?feed_type=${feedType}&limit=50`)
      .then((r) => r.json())
      .then(setPosts)
      .catch((e) => setErr(String(e)));
  }, [feedType]);
  useEffect(() => { reload(); }, [reload]);

  const submitPost = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!draft.trim()) return;
    if (!me) { setErr("请先登录"); return; }
    setPosting(true);
    try {
      const res = await authFetch("/api/community/posts", {
        method: "POST",
        body: JSON.stringify({
          content: draft,
          attached_run_id: attachRun || null,
          tags: extractTags(draft),
        }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "post failed");
      setDraft("");
      setAttachRun("");
      reload();
    } catch (e) {
      setErr(String(e));
    } finally {
      setPosting(false);
    }
  };

  const toggleLike = async (post: PostItem) => {
    if (!me) { alert("请先登录"); return; }
    const method = post.liked_by_me ? "DELETE" : "POST";
    try {
      const res = await authFetch(`/api/community/posts/${post.post_id}/like`, { method });
      if (!res.ok) return; // 失败保持原状，不刷新（下次 reload 自纠），不抛未捕获异常
      reload();
    } catch {
      /* 网络失败：忽略本次点赞操作 */
    }
  };

  return (
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title"><span className="cc-prompt">#</span>community</h1>
          <p className="cc-page-subtitle">
            社区广场 · 分享想法 / 关注作者 / 转发回测 — 参考 Binance Square 风格
          </p>
        </div>
        {!me && (
          <Link to="/login" className="cc-btn cc-btn--accent">登录 / 注册</Link>
        )}
      </div>

      {/* tabs */}
      <div className="cc-tabs">
        {(["recent", "hot", "following"] as FeedType[]).map((t) => (
          <button
            key={t}
            type="button"
            className={`cc-tab${feedType === t ? " active" : ""}`}
            onClick={() => setFeedType(t)}
          >
            {t === "recent" ? "最新" : t === "hot" ? "最热" : "关注"}
          </button>
        ))}
      </div>

      {/* compose */}
      {me && (
        <form onSubmit={submitPost} className="cc-card" style={{ marginBottom: 16 }}>
          <textarea
            className="cc-textarea"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={`${me.display_name}，分享你的策略 / 因子 / 想法（用 #tag 加标签）`}
            rows={3}
          />
          <div className="cc-row" style={{ marginTop: 8, justifyContent: "space-between" }}>
            <input
              className="cc-input"
              style={{ width: 260 }}
              placeholder="附加 run_id（可选，例：a_share_real_demo）"
              value={attachRun}
              onChange={(e) => setAttachRun(e.target.value)}
            />
            <button type="submit" className="cc-btn cc-btn--accent" disabled={posting || !draft.trim()}>
              {posting ? "..." : "发布 →"}
            </button>
          </div>
        </form>
      )}

      {err && <div className="cc-chip cc-chip--danger" style={{ marginBottom: 12 }}>{err}</div>}

      {/* feed */}
      {posts.length === 0 ? (
        <div className="cc-card cc-dim" style={{ textAlign: "center", padding: 32 }}>
          {feedType === "following"
            ? "你还没关注任何人 — 去 /community 找个有意思的作者关注"
            : "暂无帖子。"}
        </div>
      ) : (
        posts.map((p) => (
          <PostCard key={p.post_id} post={p} onToggleLike={() => toggleLike(p)} />
        ))
      )}
    </>
  );
}

function PostCard({ post, onToggleLike }: { post: PostItem; onToggleLike: () => void }) {
  return (
    <div className="cc-card" style={{ marginBottom: 12 }}>
      <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 6 }}>
        <Link to={`/u/${post.author_username}`} className="cc-mono" style={{ color: "var(--cc-accent)", textDecoration: "none" }}>
          @{post.author_username}
        </Link>
        <span className="cc-dim" style={{ fontSize: 11 }}>{post.created_at_utc.slice(0, 19)}</span>
      </div>
      <div className="cc-chat-content" style={{ marginBottom: 8 }}>{post.content}</div>
      <div className="cc-row" style={{ gap: 6, marginBottom: 8 }}>
        {post.tags.map((t) => <span key={t} className="cc-chip">#{t}</span>)}
        {post.attached_run_id && (
          <Link to={`/runs/${post.attached_run_id}`} className="cc-chip cc-chip--accent" style={{ textDecoration: "none" }}>
            📈 run: {post.attached_run_id}
          </Link>
        )}
      </div>
      <div className="cc-row" style={{ gap: 16, fontSize: 12 }}>
        <button
          type="button"
          onClick={onToggleLike}
          className="cc-btn cc-btn--ghost cc-btn--sm"
          style={{ border: 0, padding: 0 }}
        >
          {post.liked_by_me ? "❤" : "♡"} {post.likes}
        </button>
        <span className="cc-dim">💬 {post.comments_count}</span>
        <span className="cc-dim">🔄 {post.reposts}</span>
      </div>
    </div>
  );
}

function extractTags(text: string): string[] {
  const tags: string[] = [];
  const re = /#([\w一-龥]+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) tags.push(m[1]);
  return tags;
}

export default CommunityFeedPage;
