"""
JWT 鉴权中间件

开发模式（SKIP_AUTH=true）跳过验证，直接使用请求中的 user_id。
生产模式验证 Bearer token，从 payload 提取 user_id 覆盖请求参数（防伪造）。

JWT secret 与 Java Gateway 共享，确保 token 由 Gateway 签发后 Python 端可验证。
"""
import os
import jwt
from fastapi import Request, HTTPException
from app.core.logging import setup_logger

logger = setup_logger("auth")

JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
SKIP_AUTH = os.getenv("SKIP_AUTH", "true").lower() == "true"


def get_user_id_from_token(token: str) -> str:
    """从 JWT token 中提取 user_id。验证失败抛出 HTTPException。"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("userId") or payload.get("user_id") or payload.get("sub", "")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token 中缺少用户标识")
        return str(user_id)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token 已过期")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Token 无效: {str(e)}")


async def verify_request(request: Request) -> str:
    """FastAPI 依赖：验证请求并返回可信的 user_id。

    用法：
        @router.post("/chat")
        async def chat(request: ChatRequest, user_id: str = Depends(verify_request)):
            ...
    """
    if SKIP_AUTH:
        # 开发模式：从请求体或查询参数获取 user_id，不做验证
        logger.debug("开发模式，跳过 JWT 验证")
        return "dev_user"

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer token")

    token = auth_header[7:]
    return get_user_id_from_token(token)
