import os
import random
from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="School Auth Service")
Instrumentator().instrument(app).expose(app)

SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-in-prod")
ALGORITHM = "HS256"
FAILURE_RATE = float(os.getenv("AUTH_FAILURE_RATE", "0"))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")

# Small connection pool. In production this would be tuned, and often
# replaced with pgbouncer or a similar pooler in front of Postgres.
pool = SimpleConnectionPool(minconn=2, maxconn=10, dsn=DATABASE_URL)

security = HTTPBearer()


@app.get("/health")
def health():
    """Readiness: also verifies the database is reachable."""
    try:
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        finally:
            pool.putconn(conn)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {e}")
    return {"status": "ok", "service": "auth"}


@app.post("/login")
def login(email: str, password: str):
    if FAILURE_RATE > 0 and random.random() < FAILURE_RATE:
        raise HTTPException(status_code=500, detail="Injected auth failure")

    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Postgres performs the bcrypt comparison via pgcrypto.
            cur.execute(
                """
                SELECT email, role, name
                FROM users
                WHERE email = %s
                  AND password_hash = crypt(%s, password_hash)
                """,
                (email, password),
            )
            user = cur.fetchone()
    finally:
        pool.putconn(conn)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = jwt.encode(
        {
            "sub": user["email"],
            "role": user["role"],
            "name": user["name"],
            "exp": datetime.utcnow() + timedelta(hours=8),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user["role"],
        "name": user["name"],
    }


@app.get("/me")
def me(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(
            credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM]
        )
        return {
            "email": payload["sub"],
            "role": payload["role"],
            "name": payload["name"],
        }
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")