from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import HTTPException, status

SECRET_KEY = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAhQdgJeLP5dUnRRM62+YR61Zum1HftdnMLszXvQ7or2s79qtgr+9ewOQGRxwCkDV499LbnKu9nC1+RQaGMnEm0sgyYavOVTh6xEF/niPofa7QohntloLFyfLvP9rnrRKkl9eJFUpWliFq2FTCwjdwb783/s9FIm9FRPzuiMza+i2l5qhwPyK9DXruki+6tQk3hL7lA8r+RJ2Gc+np26c+DCN489DuQfyLrlXGGyudRf8myJXmD67qklXeTH+Mh3jq9ufdTWhBKvu4RooxhG37iQuSiRzFxccY3Exj8fbaz+DJzuS8owHp8jsXUC3tFQF0lDNAEggV2oApo7wT+grbVQIDAQAB"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def verify_password(plain_password, hashed_password):
    return plain_password == hashed_password

def get_password_hash(password):

    return password

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None