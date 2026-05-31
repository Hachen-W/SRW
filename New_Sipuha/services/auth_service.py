from datetime import datetime
from sqlalchemy.orm import Session

from fastapi import HTTPException, Response
from settings.security import hash_password, verify_password, security
from database.tables import User, UserRole
from settings.config import settings
from datetime import timedelta, timezone

class AuthService:
    # Register (writing to bd)
    @staticmethod
    def create_new_token(user_id : str, role : UserRole):
        expiry = settings.JWT_ACCESS_TOKEN_EXPIRES
        match role:
            case UserRole.ADMIN: 
                expiry = timedelta(minutes=10)
            case UserRole.SERVICE: 
                expiry = timedelta(hours=24)
            case UserRole.USER: 
                expiry = timedelta(minutes=30)
            case _:
                expiry = timedelta(minutes=30)
        return security.create_access_token(
            uid = user_id, 
            expiry = expiry, 
            data = {"role": role.name}
        )
    @staticmethod
    def register_user(user_data, db: Session):
        # Check for user's existance with username
        existing_user = db.query(User).filter(User.username == user_data.username).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Username already exists")
        
        # Check for user's existance with email
        existing_email = db.query(User).filter(User.email == user_data.email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already registered")

        hash_pass = hash_password(user_data.password)

        # Create new user
        new_user = User(
            username=user_data.username,
            email=user_data.email,
            role=UserRole.ADMIN,
            hashed_password=hash_pass  # Add hash save
        )
        
        db.add(new_user)
        db.commit()
        
        return {"message": "User created", "user_id": new_user.id}

    # Login (read from BD)
    @staticmethod
    def login_user(user_data, db: Session, response: Response):
        # Find user in BD
        user = db.query(User).filter(User.username == user_data.username).first()
        if not user or not verify_password(user_data.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Create token
        access_token = AuthService.create_new_token(user_id = str(user.id), role = user.role)

        refresh_token = security.create_refresh_token(
            uid=str(user.id),
        )

        payload = security._decode_token(refresh_token)
        refresh_jti = payload.jti

        user.current_refresh_jti = refresh_jti
        db.commit()

        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,              # Protect from XSS 
#            secure=True,               # Only through HTTPS
            samesite="lax",             # Protect from CSRF
            max_age=28 * 24 * 3600      # Duration
        )
        return {"access_token": access_token}

    @staticmethod
    def logout_user(token: str, db: Session, request):
        token = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        
        if token:
            payload = security._decode_token(token)
            user_id = payload.sub
            user = db.query(User).get(user_id)
            if user:
                user.last_logout_time = datetime.now(timezone.utc)
                db.commit()
        return {"message": "Logged out"}

    # Protected route with check token
    @staticmethod
    def protected_route(token: str, db: Session):
        if not token:
            raise HTTPException(status_code=401, detail="No token provided")
        try:
            #Last logout time check
            payload = security._decode_token(token)
            user = db.query(User).get(payload.sub)

            if user.last_logout_time and \
                datetime.fromtimestamp(payload.iat, tz=timezone.utc) < user.last_logout_time:
                raise HTTPException(status_code=401, detail="Token issued before last logout")

            if not payload:
                return {"error": "Invalid token"}
            
            return {
                "message": "This is will be pyara tester!", 
                "user_id": user.id,
                "token_valid": True,
                "role": user.role.name
            }
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Invalid or expired token")
    @staticmethod
    def get_token_from_request(request):
        token = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        
        return token
    @staticmethod
    def refresh_token_update(refresh_token, db: Session, response: Response):
        if not refresh_token:
            raise HTTPException(status_code=401, detail="Refresh token missing")
        try:
            payload = security._decode_token(refresh_token)
            user_id = payload.sub
            token_jti = payload.jti
            old_exp = payload.exp

            user = db.query(User).get(user_id)
            if not user:
                raise HTTPException(status_code=401, detail="User not found")
            
            if user.current_refresh_jti != token_jti:
                raise HTTPException(status_code=401, detail="Refresh token revoked or expired")

            # Refresh Token Rotation

            new_refresh = security.create_refresh_token(
                uid=str(user.id),
                expires_at=old_exp
            )
            
            payload = security._decode_token(new_refresh)
            new_jti = payload.jti

            user.current_refresh_jti = new_jti # Update jti in db
            db.commit()

            response.set_cookie(
                key="refresh_token",
                value=new_refresh,
                httponly=True,
#                secure = True https needed
                samesite="lax",
                max_age=int((old_exp - datetime.now(timezone.utc)).total_seconds())
            )

            new_access_token = AuthService.create_new_token(
                user_id=str(user.id), 
                role=user.role
            )

            return {"access_token": new_access_token}
            
        except Exception:
            raise HTTPException(status_code=401, detail="Session expired. Please login again")
