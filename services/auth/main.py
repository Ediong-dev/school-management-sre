import os
import random
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="School Auth Service")
Instrumentator().instrument(app).expose(app)

SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-in-prod")
ALGORITHM = "HS256"
FAILURE_RATE = float(os.getenv("AUTH_FAILURE_RATE", "0"))

security = HTTPBearer()

# In-memory for Lab 0. Moves to Postgres in Lab 4.
USERS = {
    "admin@school.edu":   {"password": "admin123",   "role": "admin",   "name": "Admin User"},
    "teacher@school.edu": {"password": "teacher123", "role": "teacher", "name": "Ms. Johnson"},
    "student@school.edu": {"password": "student123", "role": "student", "name": "Alex Smith"},
    "parent@school.edu":  {"password": "parent123",  "role": "parent",  "name": "Mr. Smith"},
}

@app.get("/health")
def health():
    return {"status": "ok", "service": "auth"}

@app.post("/login")
def login(email: str, password: str):
    # Fault injection — used in Lab 1 and Lab 8
    if FAILURE_RATE > 0 and random.random() < FAILURE_RATE:
        raise HTTPException(status_code=500, detail="Injected auth failure")

    user = USERS.get(email)
    if not user or user["password"] != password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = jwt.encode({
        "sub": email,
        "role": user["role"],
        "name": user["name"],
        "exp": datetime.utcnow() + timedelta(hours=8),
    }, SECRET_KEY, algorithm=ALGORITHM)

    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user["role"],
        "name": user["name"],
    }

@app.get("/me")
def me(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return {
            "email": payload["sub"],
            "role": payload["role"],
            "name": payload["name"],
        }
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")