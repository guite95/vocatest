FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성 설치 (필요시)
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스코드 복사
COPY . .

# 데이터 저장소 폴더 생성
RUN mkdir -p /app/data

# 포트 노출
EXPOSE 8000

# 실행 커맨드 (호스트 0.0.0.0 설정 중요)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]