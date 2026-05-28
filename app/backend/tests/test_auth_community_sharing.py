"""v0.8.0 · auth + community + strategy sharing 全套测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.auth import AuthError, AuthService
from app.community import CommunityService
from app.sharing import SharingService


@pytest.fixture()
def auth(tmp_path: Path) -> AuthService:
    return AuthService(tmp_path / "c.db")


@pytest.fixture()
def community(tmp_path: Path) -> CommunityService:
    return CommunityService(tmp_path / "c.db")


@pytest.fixture()
def sharing(tmp_path: Path) -> SharingService:
    run_root = tmp_path / "runs"
    run_root.mkdir()
    # 一个最小 run_json 便于 publish snapshot metrics
    demo = run_root / "demo-run"
    demo.mkdir()
    (demo / "run.json").write_text(
        json.dumps({"metrics": {"sharpe": 1.5, "total_return": 0.42, "max_drawdown": -0.15, "pbo": {"pbo": 0.3}, "deflated_sharpe": 0.8}}),
        encoding="utf-8",
    )
    return SharingService(tmp_path / "c.db", run_root)


# ---- AUTH ----

def test_auth_register_login_logout(auth: AuthService) -> None:
    user = auth.register("alice", "passw0rd", "Alice")
    assert user.username == "alice"
    assert user.user_id.startswith("user-")
    u2, token = auth.login("alice", "passw0rd")
    assert u2.user_id == user.user_id
    fetched = auth.user_by_token(token)
    assert fetched and fetched.username == "alice"
    auth.logout(token)
    assert auth.user_by_token(token) is None


def test_auth_register_validation(auth: AuthService) -> None:
    with pytest.raises(AuthError):
        auth.register("ab", "passw0rd")  # 太短
    with pytest.raises(AuthError):
        auth.register("alice space", "passw0rd")  # 含空格
    with pytest.raises(AuthError):
        auth.register("aliceok", "123")  # 密码太短


def test_auth_register_duplicate(auth: AuthService) -> None:
    auth.register("alice", "passw0rd")
    with pytest.raises(AuthError, match="已被占用"):
        auth.register("alice", "another1")


def test_auth_local_user_exists(auth: AuthService) -> None:
    u = auth.get_user_by_username("local")
    assert u is not None
    assert u.user_id == "user-local"


def test_auth_login_wrong_password(auth: AuthService) -> None:
    auth.register("alice", "passw0rd")
    with pytest.raises(AuthError, match="错误"):
        auth.login("alice", "wrongpwd")


# ---- COMMUNITY ----

def test_community_post_crud(auth: AuthService, community: CommunityService) -> None:
    u = auth.register("alice", "passw0rd")
    post = community.create_post(u.user_id, "Hello quant!", tags=["intro"])
    assert post.author_id == u.user_id
    fetched = community.get_post(post.post_id)
    assert fetched is not None
    assert fetched.post.content == "Hello quant!"
    assert fetched.author_username == "alice"
    # 删除
    assert community.delete_post(post.post_id, u.user_id)
    assert community.get_post(post.post_id) is None


def test_community_post_validation(auth: AuthService, community: CommunityService) -> None:
    u = auth.register("alice", "passw0rd")
    with pytest.raises(ValueError, match="不能为空"):
        community.create_post(u.user_id, "")
    with pytest.raises(ValueError, match="最多 5000"):
        community.create_post(u.user_id, "x" * 5001)


def test_community_like_unlike_idempotent(auth: AuthService, community: CommunityService) -> None:
    u = auth.register("alice", "passw0rd")
    post = community.create_post(u.user_id, "hi")
    assert community.like(u.user_id, post.post_id)
    assert not community.like(u.user_id, post.post_id)  # 重复 like 应 false
    after = community.get_post(post.post_id, u.user_id)
    assert after and after.post.likes == 1 and after.liked_by_me
    assert community.unlike(u.user_id, post.post_id)
    after2 = community.get_post(post.post_id, u.user_id)
    assert after2 and after2.post.likes == 0 and not after2.liked_by_me


def test_community_comment_and_count(auth: AuthService, community: CommunityService) -> None:
    u = auth.register("alice", "passw0rd")
    post = community.create_post(u.user_id, "hi")
    c1 = community.add_comment(post.post_id, u.user_id, "first")
    c2 = community.add_comment(post.post_id, u.user_id, "second", reply_to=c1.comment_id)
    comments = community.list_comments(post.post_id)
    assert len(comments) == 2
    assert comments[1]["reply_to"] == c1.comment_id
    after = community.get_post(post.post_id)
    assert after and after.post.comments_count == 2


def test_community_follow_unfollow(auth: AuthService, community: CommunityService) -> None:
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    assert community.follow(a.user_id, b.user_id)
    assert not community.follow(a.user_id, b.user_id)  # 重复
    stats = community.follow_stats(b.user_id, current_user_id=a.user_id)
    assert stats["followers"] == 1 and stats["i_follow"]
    assert community.unfollow(a.user_id, b.user_id)
    stats2 = community.follow_stats(b.user_id, current_user_id=a.user_id)
    assert stats2["followers"] == 0 and not stats2["i_follow"]


def test_community_follow_self_rejected(auth: AuthService, community: CommunityService) -> None:
    u = auth.register("alice", "passw0rd")
    with pytest.raises(ValueError):
        community.follow(u.user_id, u.user_id)


def test_community_feed_following(auth: AuthService, community: CommunityService) -> None:
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    community.follow(a.user_id, b.user_id)
    community.create_post(a.user_id, "from alice")
    community.create_post(b.user_id, "from bob")
    feed = community.feed(feed_type="following", current_user_id=a.user_id)
    contents = [it.post.content for it in feed]
    assert contents == ["from bob"]  # 我只看我关注的人


def test_community_feed_hot_orders_by_engagement(auth: AuthService, community: CommunityService) -> None:
    u = auth.register("alice", "passw0rd")
    cold = community.create_post(u.user_id, "cold")
    hot = community.create_post(u.user_id, "hot")
    community.like(u.user_id, hot.post_id)
    feed = community.feed(feed_type="hot")
    # hot 帖应排前
    assert feed[0].post.post_id == hot.post_id


# ---- SHARING ----

def test_sharing_publish_snapshots_metrics(auth: AuthService, sharing: SharingService) -> None:
    u = auth.register("alice", "passw0rd")
    s = sharing.publish_strategy(
        run_id="demo-run", author_id=u.user_id, title="Alice strat",
        description="MA crossover", tags=["mom", "ma"], asset_class="equity_cn",
    )
    assert s.share_id.startswith("share-")
    assert s.metric_sharpe == 1.5
    assert s.metric_total_return == 0.42
    assert s.metric_pbo == 0.3
    assert s.metric_dsr == 0.8


def test_sharing_publish_requires_existing_run(auth: AuthService, sharing: SharingService) -> None:
    u = auth.register("alice", "passw0rd")
    with pytest.raises(ValueError):
        sharing.publish_strategy(run_id="no-such", author_id=u.user_id, title="x")


def test_sharing_fork_increments_count(auth: AuthService, sharing: SharingService) -> None:
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    s = sharing.publish_strategy(run_id="demo-run", author_id=a.user_id, title="A")
    forked = sharing.fork_strategy(s.share_id, b.user_id)
    assert forked.fork_from_share_id == s.share_id
    assert forked.author_id == b.user_id
    original = sharing.get_strategy(s.share_id)
    assert original and original.forks == 1


def test_sharing_leaderboard_sort_by_sharpe(auth: AuthService, sharing: SharingService, tmp_path: Path) -> None:
    a = auth.register("alice", "passw0rd")
    # 多搞几个 demo run
    for i, sr in enumerate([0.5, 2.5, 1.2]):
        run_dir = (tmp_path / "runs" / f"r{i}")
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text(json.dumps({"metrics": {"sharpe": sr}}), encoding="utf-8")
        sharing.publish_strategy(run_id=f"r{i}", author_id=a.user_id, title=f"S{i}")
    top = sharing.list_strategies(sort_by="sharpe", limit=10)
    sharpes = [s.metric_sharpe for s in top if s.metric_sharpe is not None]
    assert sharpes == sorted(sharpes, reverse=True)


def test_sharing_delete_only_by_author(auth: AuthService, sharing: SharingService) -> None:
    a = auth.register("alice", "passw0rd")
    b = auth.register("bob", "passw0rd")
    s = sharing.publish_strategy(run_id="demo-run", author_id=a.user_id, title="A")
    with pytest.raises(PermissionError):
        sharing.delete_strategy(s.share_id, b.user_id)
    assert sharing.delete_strategy(s.share_id, a.user_id)
    assert sharing.get_strategy(s.share_id) is None


def test_sharing_like_idempotent(auth: AuthService, sharing: SharingService) -> None:
    a = auth.register("alice", "passw0rd")
    s = sharing.publish_strategy(run_id="demo-run", author_id=a.user_id, title="X")
    assert sharing.like(a.user_id, s.share_id)
    assert not sharing.like(a.user_id, s.share_id)
    refreshed = sharing.get_strategy(s.share_id)
    assert refreshed and refreshed.likes == 1
