"""
用户认证 API — 登录 / 注册

开发模式 (SKIP_AUTH=true): 接受任意用户名，返回简易 token
生产模式: JWT 签发，密码哈希存储
"""
import os
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import jwt
from fastapi import APIRouter
from pydantic import BaseModel
from app.core.logging import setup_logger

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = setup_logger("auth_api")

JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_EXPIRATION = int(os.getenv("JWT_EXPIRATION", "86400000"))  # ms
SKIP_AUTH = os.getenv("SKIP_AUTH", "false").lower() == "true"

# 简易用户存储（JSON 文件，生产环境应迁移到 MySQL）
USER_FILE = Path("./data/users.json")


class AuthRequest(BaseModel):
    username: str
    password: str


def _load_users() -> dict:
    if not USER_FILE.exists():
        return {}
    try:
        return json.loads(USER_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return {}


def _save_users(users: dict):
    USER_FILE.parent.mkdir(parents=True, exist_ok=True)
    USER_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _make_token(username: str) -> str:
    payload = {
        "sub": username,
        "user_id": username,
        "exp": datetime.utcnow() + timedelta(milliseconds=JWT_EXPIRATION),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


@router.post("/register")
async def register(req: AuthRequest):
    """注册新用户"""
    if len(req.username) < 3:
        return {"code": 400, "message": "用户名至少 3 个字符"}
    if len(req.password) < 6:
        return {"code": 400, "message": "密码至少 6 个字符"}

    users = _load_users()
    if req.username in users:
        return {"code": 400, "message": "用户名已存在"}

    users[req.username] = {
        "password_hash": _hash_password(req.password),
        "created_at": datetime.now().isoformat(),
    }
    _save_users(users)
    logger.info(f"用户注册: {req.username}")
    return {"code": 200, "message": "注册成功", "token": _make_token(req.username)}


@router.post("/login")
async def login(req: AuthRequest):
    """用户登录"""
    if SKIP_AUTH:
        # 开发模式：直接签发 token
        logger.debug(f"开发模式登录: {req.username}")
        return {"code": 200, "token": _make_token(req.username), "user_id": req.username}

    users = _load_users()
    user = users.get(req.username)
    if not user or user.get("password_hash") != _hash_password(req.password):
        return {"code": 401, "message": "用户名或密码错误"}

    logger.info(f"用户登录: {req.username}")
    return {"code": 200, "token": _make_token(req.username), "user_id": req.username}
