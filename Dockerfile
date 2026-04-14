FROM node:20-bookworm-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git libopenmpi-dev openmpi-bin \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY lsslider ./lsslider
COPY matrices_nfftlog128_Afull-True_use_TNS-False.npy ./
COPY --from=frontend-build /app/lsslider/static ./lsslider/static

EXPOSE 8000

CMD ["python", "-m", "lsslider"]
