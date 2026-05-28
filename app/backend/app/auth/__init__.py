"""社区 auth：sqlite users + PBKDF2 password + 服务端 session token。

设计原则：
- 无新依赖：用 Python stdlib hashlib (PBKDF2-HMAC-SHA256, 200k iter) + secrets.token_urlsafe(32)
- 密码 hash + salt 存 users 表；token 存 sessions 表（方便 revoke / 多端登出）
- 每个 request 走 `Authorization: Bearer <token>` header；FastAPI Depends 注入 current_user
- 单 'local' user 作 dev fallback，保证不登录也能看历史 demo
"""

from __future__ import annotations

from .service import (
    AuthError,
    AuthService,
    User,
    current_user_dependency,
    init_auth_db,
    require_user_dependency,
)

__all__ = [
    "AuthError",
    "AuthService",
    "User",
    "current_user_dependency",
    "init_auth_db",
    "require_user_dependency",
]
