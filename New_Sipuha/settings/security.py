from passlib.hash import argon2
from authx import AuthX
from settings.config import AuthConfig

# Initialize config for check tokens
auth_config = AuthConfig()
security = AuthX(config=auth_config)


def hash_password(password: str) -> str:
    return argon2.hash(password)


def verify_password(inp_pass: str, hash_pass: str) -> bool:
    return argon2.verify(inp_pass, hash_pass)
