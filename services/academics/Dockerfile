# ---- Build stage ----
FROM python:3.12-slim AS builder
WORKDIR /app

COPY requirements.txt .
# --prefix puts everything in a clean location we can copy in one shot.
# No --user flag; we want system-wide install in /install/.
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Runtime stage ----
FROM python:3.12-slim

# Create a non-root user with a fixed UID for reproducibility.
# -r = system user, -g = primary group, -u 10001 = fixed uid.
RUN groupadd -r -g 10001 app && useradd -r -g app -u 10001 -d /home/app -m app

WORKDIR /app

# Copy installed packages from builder to /usr/local (system site-packages).
COPY --from=builder /install /usr/local

# Copy app code with explicit ownership and read-only permissions.
COPY --chown=app:app --chmod=0444 main.py .

# Don't write .pyc files — we want a read-only runtime FS if possible.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH=/usr/local/bin:$PATH

# Drop privileges. This must come before CMD.
USER app

EXPOSE 3002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3002"]