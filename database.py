import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# SQLite 데이터베이스 파일 생성 (data 폴더 내부에 저장)
SQLALCHEMY_DATABASE_URL = "sqlite:///./data/quiz.db"

# [변경] 데이터베이스 디렉터리가 없으면 생성
db_dir = os.path.dirname("./data/quiz.db")
if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir, exist_ok=True)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()