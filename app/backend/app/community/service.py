"""Community service · post/comment/like/follow + Square 风 feed。

数据库与 auth 共享 sqlite；表名加 `c_` 前缀避免与 auth/sharing 冲突。
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Post:
    post_id: str
    author_id: str
    content: str
    tags: list[str] = field(default_factory=list)
    attached_run_id: str | None = None
    attached_factor_id: str | None = None
    repost_of: str | None = None  # 转发的原贴
    created_at_utc: str = ""
    likes: int = 0
    reposts: int = 0
    comments_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PostListItem:
    """list view 加 author 信息（join 后的 view）。"""

    post: Post
    author_username: str
    author_display_name: str
    author_avatar_url: str = ""
    liked_by_me: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = self.post.to_dict()
        d["author_username"] = self.author_username
        d["author_display_name"] = self.author_display_name
        d["author_avatar_url"] = self.author_avatar_url
        d["liked_by_me"] = self.liked_by_me
        return d


@dataclass
class Comment:
    comment_id: str
    post_id: str
    author_id: str
    content: str
    reply_to: str | None = None
    created_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_INIT_LOCK = threading.Lock()
_INITIALIZED: set[str] = set()


def init_community_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    key = str(db_path.resolve()) + "#community"
    with _INIT_LOCK:
        if key in _INITIALIZED:
            return
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS c_posts (
                post_id TEXT PRIMARY KEY,
                author_id TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT,
                attached_run_id TEXT,
                attached_factor_id TEXT,
                repost_of TEXT,
                created_at_utc TEXT NOT NULL,
                likes INTEGER DEFAULT 0,
                reposts INTEGER DEFAULT 0,
                comments_count INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_posts_author ON c_posts(author_id);
            CREATE INDEX IF NOT EXISTS idx_posts_created ON c_posts(created_at_utc);

            CREATE TABLE IF NOT EXISTS c_comments (
                comment_id TEXT PRIMARY KEY,
                post_id TEXT NOT NULL,
                author_id TEXT NOT NULL,
                content TEXT NOT NULL,
                reply_to TEXT,
                created_at_utc TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_comments_post ON c_comments(post_id);

            CREATE TABLE IF NOT EXISTS c_likes (
                user_id TEXT NOT NULL,
                post_id TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                PRIMARY KEY (user_id, post_id)
            );

            CREATE TABLE IF NOT EXISTS c_follows (
                follower_id TEXT NOT NULL,
                followee_id TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                PRIMARY KEY (follower_id, followee_id)
            );
            CREATE INDEX IF NOT EXISTS idx_follows_followee ON c_follows(followee_id);
            """
        )
        conn.close()
        _INITIALIZED.add(key)


class CommunityService:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        init_community_db(db_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    # ---- posts ----

    def create_post(
        self,
        author_id: str,
        content: str,
        *,
        tags: list[str] | None = None,
        attached_run_id: str | None = None,
        attached_factor_id: str | None = None,
        repost_of: str | None = None,
    ) -> Post:
        content = (content or "").strip()
        if not content and not repost_of:
            raise ValueError("帖子内容不能为空")
        if len(content) > 5000:
            raise ValueError("帖子最多 5000 字")
        conn = self._conn()
        try:
            post_id = f"post-{secrets.token_hex(8)}"
            now = _now()
            conn.execute(
                "INSERT INTO c_posts (post_id, author_id, content, tags, attached_run_id, attached_factor_id, repost_of, created_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    post_id,
                    author_id,
                    content,
                    json.dumps(tags or []),
                    attached_run_id,
                    attached_factor_id,
                    repost_of,
                    now,
                ),
            )
            if repost_of:
                conn.execute("UPDATE c_posts SET reposts = reposts + 1 WHERE post_id = ?", (repost_of,))
            return Post(
                post_id=post_id,
                author_id=author_id,
                content=content,
                tags=tags or [],
                attached_run_id=attached_run_id,
                attached_factor_id=attached_factor_id,
                repost_of=repost_of,
                created_at_utc=now,
            )
        finally:
            conn.close()

    def delete_post(self, post_id: str, author_id: str) -> bool:
        conn = self._conn()
        try:
            row = conn.execute("SELECT author_id FROM c_posts WHERE post_id = ?", (post_id,)).fetchone()
            if row is None:
                return False
            if row["author_id"] != author_id:
                raise PermissionError("只能删自己的帖子")
            conn.execute("DELETE FROM c_posts WHERE post_id = ?", (post_id,))
            conn.execute("DELETE FROM c_comments WHERE post_id = ?", (post_id,))
            conn.execute("DELETE FROM c_likes WHERE post_id = ?", (post_id,))
            return True
        finally:
            conn.close()

    def get_post(self, post_id: str, current_user_id: str | None = None) -> PostListItem | None:
        conn = self._conn()
        try:
            row = conn.execute(
                """
                SELECT p.*, u.username AS author_username, u.display_name AS author_display_name, u.avatar_url AS author_avatar_url
                FROM c_posts p
                LEFT JOIN users u ON p.author_id = u.user_id
                WHERE p.post_id = ?
                """,
                (post_id,),
            ).fetchone()
            if row is None:
                return None
            liked = False
            if current_user_id:
                lr = conn.execute(
                    "SELECT 1 FROM c_likes WHERE user_id = ? AND post_id = ?",
                    (current_user_id, post_id),
                ).fetchone()
                liked = lr is not None
            return _row_to_post_item(row, liked)
        finally:
            conn.close()

    def feed(
        self,
        *,
        feed_type: str = "recent",  # recent | following | hot | by_author
        current_user_id: str | None = None,
        author_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PostListItem]:
        conn = self._conn()
        try:
            params: list[Any] = []
            where = ""
            order = "p.created_at_utc DESC"
            if feed_type == "following":
                if not current_user_id:
                    return []
                where = "WHERE p.author_id IN (SELECT followee_id FROM c_follows WHERE follower_id = ?)"
                params.append(current_user_id)
            elif feed_type == "hot":
                # 简化：按 likes + reposts*2 + comments_count*3 综合得分
                order = "(p.likes + p.reposts*2 + p.comments_count*3) DESC, p.created_at_utc DESC"
            elif feed_type == "by_author" and author_id:
                where = "WHERE p.author_id = ?"
                params.append(author_id)
            params.extend([limit, offset])
            rows = conn.execute(
                f"""
                SELECT p.*, u.username AS author_username, u.display_name AS author_display_name, u.avatar_url AS author_avatar_url
                FROM c_posts p
                LEFT JOIN users u ON p.author_id = u.user_id
                {where}
                ORDER BY {order}
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
            liked_ids: set[str] = set()
            if current_user_id and rows:
                pids = [r["post_id"] for r in rows]
                placeholders = ",".join("?" * len(pids))
                liked_rows = conn.execute(
                    f"SELECT post_id FROM c_likes WHERE user_id = ? AND post_id IN ({placeholders})",
                    [current_user_id, *pids],
                ).fetchall()
                liked_ids = {r["post_id"] for r in liked_rows}
            return [_row_to_post_item(r, r["post_id"] in liked_ids) for r in rows]
        finally:
            conn.close()

    # ---- likes ----

    def like(self, user_id: str, post_id: str) -> bool:
        conn = self._conn()
        try:
            try:
                conn.execute(
                    "INSERT INTO c_likes (user_id, post_id, created_at_utc) VALUES (?, ?, ?)",
                    (user_id, post_id, _now()),
                )
            except sqlite3.IntegrityError:
                return False  # 已经赞过
            conn.execute("UPDATE c_posts SET likes = likes + 1 WHERE post_id = ?", (post_id,))
            return True
        finally:
            conn.close()

    def unlike(self, user_id: str, post_id: str) -> bool:
        conn = self._conn()
        try:
            cur = conn.execute(
                "DELETE FROM c_likes WHERE user_id = ? AND post_id = ?", (user_id, post_id)
            )
            if cur.rowcount > 0:
                conn.execute("UPDATE c_posts SET likes = MAX(0, likes - 1) WHERE post_id = ?", (post_id,))
                return True
            return False
        finally:
            conn.close()

    # ---- comments ----

    def add_comment(self, post_id: str, author_id: str, content: str, reply_to: str | None = None) -> Comment:
        content = (content or "").strip()
        if not content:
            raise ValueError("评论不能为空")
        if len(content) > 2000:
            raise ValueError("评论最多 2000 字")
        conn = self._conn()
        try:
            cid = f"cmt-{secrets.token_hex(8)}"
            now = _now()
            conn.execute(
                "INSERT INTO c_comments (comment_id, post_id, author_id, content, reply_to, created_at_utc) VALUES (?, ?, ?, ?, ?, ?)",
                (cid, post_id, author_id, content, reply_to, now),
            )
            conn.execute("UPDATE c_posts SET comments_count = comments_count + 1 WHERE post_id = ?", (post_id,))
            return Comment(comment_id=cid, post_id=post_id, author_id=author_id, content=content, reply_to=reply_to, created_at_utc=now)
        finally:
            conn.close()

    def list_comments(self, post_id: str, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            rows = conn.execute(
                """
                SELECT c.*, u.username, u.display_name, u.avatar_url
                FROM c_comments c LEFT JOIN users u ON c.author_id = u.user_id
                WHERE c.post_id = ? ORDER BY c.created_at_utc ASC LIMIT ?
                """,
                (post_id, limit),
            ).fetchall()
            return [
                {
                    "comment_id": r["comment_id"],
                    "post_id": r["post_id"],
                    "author_id": r["author_id"],
                    "content": r["content"],
                    "reply_to": r["reply_to"],
                    "created_at_utc": r["created_at_utc"],
                    "author_username": r["username"],
                    "author_display_name": r["display_name"],
                    "author_avatar_url": r["avatar_url"] or "",
                }
                for r in rows
            ]
        finally:
            conn.close()

    # ---- follow ----

    def follow(self, follower_id: str, followee_id: str) -> bool:
        if follower_id == followee_id:
            raise ValueError("不能关注自己")
        conn = self._conn()
        try:
            try:
                conn.execute(
                    "INSERT INTO c_follows (follower_id, followee_id, created_at_utc) VALUES (?, ?, ?)",
                    (follower_id, followee_id, _now()),
                )
                return True
            except sqlite3.IntegrityError:
                return False
        finally:
            conn.close()

    def unfollow(self, follower_id: str, followee_id: str) -> bool:
        conn = self._conn()
        try:
            cur = conn.execute(
                "DELETE FROM c_follows WHERE follower_id = ? AND followee_id = ?",
                (follower_id, followee_id),
            )
            return cur.rowcount > 0
        finally:
            conn.close()

    def follow_stats(self, user_id: str, current_user_id: str | None = None) -> dict[str, Any]:
        conn = self._conn()
        try:
            followers = conn.execute(
                "SELECT COUNT(*) as n FROM c_follows WHERE followee_id = ?", (user_id,)
            ).fetchone()["n"]
            following = conn.execute(
                "SELECT COUNT(*) as n FROM c_follows WHERE follower_id = ?", (user_id,)
            ).fetchone()["n"]
            follows_me = False
            i_follow = False
            if current_user_id:
                a = conn.execute(
                    "SELECT 1 FROM c_follows WHERE follower_id = ? AND followee_id = ?",
                    (user_id, current_user_id),
                ).fetchone()
                follows_me = a is not None
                b = conn.execute(
                    "SELECT 1 FROM c_follows WHERE follower_id = ? AND followee_id = ?",
                    (current_user_id, user_id),
                ).fetchone()
                i_follow = b is not None
            return {
                "user_id": user_id,
                "followers": followers,
                "following": following,
                "follows_me": follows_me,
                "i_follow": i_follow,
            }
        finally:
            conn.close()


def _row_to_post_item(row: sqlite3.Row, liked: bool) -> PostListItem:
    tags = []
    if row["tags"]:
        try:
            tags = json.loads(row["tags"])
        except Exception:  # noqa: BLE001
            tags = []
    post = Post(
        post_id=row["post_id"],
        author_id=row["author_id"],
        content=row["content"],
        tags=tags,
        attached_run_id=row["attached_run_id"],
        attached_factor_id=row["attached_factor_id"],
        repost_of=row["repost_of"],
        created_at_utc=row["created_at_utc"],
        likes=row["likes"],
        reposts=row["reposts"],
        comments_count=row["comments_count"],
    )
    return PostListItem(
        post=post,
        author_username=row["author_username"] or "unknown",
        author_display_name=row["author_display_name"] or "unknown",
        author_avatar_url=row["author_avatar_url"] or "",
        liked_by_me=liked,
    )
