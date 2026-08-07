from fastapi import APIRouter, Response, Depends, Request, HTTPException
from sqlalchemy.orm import Session
from user_operations import UserRegister, UserLogin
from database.create_tables import get_db
from database.tables import User, UserRole
from services.auth_service import AuthService, security
# Берем чистый движок лимитов, БЕЗ slowapi
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

from fastapi.security import HTTPBearer

security_bearer = HTTPBearer(auto_error=False)

# 1. Инициализируем хранилище и стратегию (движок лимитера)
storage = MemoryStorage()
strategy = MovingWindowRateLimiter(storage)

# 2. Создаем нашу собственную FastAPI-зависимость
def rate_limit_dependency(request: Request):
    token = AuthService.get_token_from_request(request)
    role = None
    user_id = None
    # Пытаемся понять, кто к нам пришел
    if token:
        try:
            payload = security._decode_token(token)
            role = payload.role
            user_id = payload.sub
        except Exception:
            pass
            
    # Динамически раздаем лимиты и ключи
    if role in (UserRole.SERVICE.name, UserRole.ADMIN.name):
        limit_str = "120/minute"
        key = f"privileged_{user_id}"
    elif user_id:
        limit_str = "10/minute"
        key = f"user_{user_id}"
    else:
        # Для неавторизованных (регистрация/логин) берем IP
        limit_str = "10/minute"
        key = request.client.host 

    # Проверяем лимит в движке
    limit_obj = parse(limit_str)
    if not strategy.hit(limit_obj, key):
        raise HTTPException(
            status_code=429, 
            detail=f"Rate limit exceeded: {limit_str}. Try again later."
        )
    
class AccessChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, token_payload = Depends(security.access_token_required)):
        if token_payload.role not in self.allowed_roles:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        return token_payload

router_auth = APIRouter(tags=["Authentification"])

# Register (writing to bd)
@router_auth.post("/auth/register", dependencies=[Depends(rate_limit_dependency)])
def register(request: Request, user_data: UserRegister, db: Session = Depends(get_db)):
    return AuthService.register_user(user_data, db)

# Login (read from BD)
@router_auth.post("/auth/login", dependencies=[Depends(rate_limit_dependency)])
def login(request: Request, user_data: UserLogin, response: Response, db: Session = Depends(get_db)):
    return AuthService.login_user(user_data, db, response)

@router_auth.post("/auth/logout", dependencies=[Depends(rate_limit_dependency)])
def logout(response: Response, db: Session = Depends(get_db), request: Request = None):
    token = AuthService.get_token_from_request(request)
    return AuthService.logout_user(token, db, request)


# Protected route with check token
@router_auth.get("/audio/verify",
                dependencies=[
                    Depends(rate_limit_dependency),
                    Depends(AccessChecker(["SERVICE", "ADMIN"])),
                    Depends(security_bearer)
                ])
def protected_route(request: Request, db: Session = Depends(get_db)):
    token = AuthService.get_token_from_request(request)
    return AuthService.protected_route(token, db)


@router_auth.get("/")
def home():
    return {"message": "Server is running with DATABASE!"}

@router_auth.post("/auth/refresh")
def refresh_route(request: Request, response: Response, db: Session = Depends(get_db)):
    refresh_token = request.cookies.get("refresh_token")
    return AuthService.refresh_token_update(refresh_token, db, response)
