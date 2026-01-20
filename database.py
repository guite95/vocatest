import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# [수정] 현재 파일의 위치를 기준으로 절대 경로 계산 (OS 무관하게 작동)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "quiz.db")

# SQLite URL 생성 (Linux에서는 슬래시 4개, Windows에서는 3개가 됨)
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

# 데이터베이스 디렉터리가 없으면 생성
db_dir = os.path.dirname(DB_PATH)
if not os.path.exists(db_dir):
    os.makedirs(db_dir, exist_ok=True)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()