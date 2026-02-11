import os
import pyara
import asyncio
import concurrent.futures
from sqlalchemy.orm import Session
from database import get_db, create_tables
from models import User
from fastapi import FastAPI, Request, UploadFile, File, Depends, HTTPException, status, Form, Cookie, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import timedelta

import security

create_tables()

app = FastAPI(
    max_upload_size=10 * 1024 * 1024,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

thread_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=20,
    thread_name_prefix="audio_worker"
)

async def get_current_user(
        access_token: str = Cookie(default=None),
        db: Session = Depends(get_db)
):
    if not access_token:
        return None

    token = access_token.replace("Bearer ", "") if access_token.startswith("Bearer ") else access_token
    payload = security.verify_token(token)
    if not payload:
        return None

    username = payload.get("sub")
    if not username:
        return None

    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active:
        return None

    return user

async def auth_required(current_user: User = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            detail="Not authenticated",
            headers={"Location": "/login"}
        )
    return current_user

def set_token_cookie(response: Response, token: str):
    response.set_cookie(
        key="access_token",
        value=f"Bearer {token}",
        httponly=True,
        max_age=30 * 60,
        secure=False,
        samesite="lax"
    )
    return response

@app.get("/", response_class=HTMLResponse)
async def home(
        request: Request,
        current_user: User = Depends(auth_required)
):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "current_user": current_user
        }
    )

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    try:
        db = next(get_db())
        current_user = await get_current_user(request.cookies.get("access_token"), db)
        if current_user:
            return RedirectResponse("/", status_code=303)
    except:
        pass

    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(
        username: str = Form(...),
        password: str = Form(...),
        db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()

    if not user or not security.verify_password(password, user.hashed_password):
        response = RedirectResponse("/login?error=1", status_code=303)
        return response

    if not user.is_active:
        response = RedirectResponse("/login?error=2", status_code=303)
        return response

    access_token = security.create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    response = RedirectResponse("/", status_code=303)
    set_token_cookie(response, access_token)
    return response

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
async def register(
        username: str = Form(...),
        email: str = Form(...),
        password: str = Form(...),
        db: Session = Depends(get_db)
):
    existing_user = db.query(User).filter(
        (User.username == username) | (User.email == email)
    ).first()

    if existing_user:
        response = RedirectResponse("/register?error=1", status_code=303)
        return response

    hashed_password = security.get_password_hash(password)
    user = User(
        username=username,
        email=email,
        hashed_password=hashed_password
    )

    db.add(user)
    db.commit()

    access_token = security.create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    response = RedirectResponse("/", status_code=303)
    set_token_cookie(response, access_token)
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(key="access_token")
    return response

@app.get("/upload", response_class=HTMLResponse)
async def upload_page(
        request: Request,
        current_user: User = Depends(auth_required)
):
    return templates.TemplateResponse(
        "upload.html",
        {
            "request": request,
            "current_user": current_user
        }
    )


@app.post("/upload/")
async def upload_file(
        file: UploadFile = File(...),
        current_user: User = Depends(auth_required)
):
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as tmp_file:
        file_path = Path(tmp_file.name)

    try:
        content = await file.read()

        with open(file_path, "wb") as buffer:
            buffer.write(content)

        try:
            decision = await asyncio.wait_for(
                asyncio.to_thread(pyara.main.predict_audio, str(file_path)),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            return JSONResponse({
                "status": "error",
                "message": "Таймаут обработки"
            }, status_code=408)

        if decision == 1:
            result = "Сгенерированно нейросетью"
        else:
            result = "Звуковая дорожка оригинальна"

        return JSONResponse({
            "status": "success",
            "result": result,
            "message": "Файл успешно обработан"
        })

    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": f"Ошибка: {str(e)}"
        }, status_code=500)
    finally:
        try:
            if file_path.exists():
                os.unlink(file_path)
        except:
            pass


@app.get("/program", response_class=HTMLResponse)
async def program_page(request: Request):
    return templates.TemplateResponse("program.html", {"request": request})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)