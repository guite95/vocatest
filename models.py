from sqlalchemy import Column, Integer, String, Text
from database import Base

# 문제 범위 (기존 단어장 역할)
class WordSet(Base):
    __tablename__ = "word_sets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True) # 범위 이름 (예: Chapter 1)
    content = Column(Text) # 원본 단어 텍스트

# 생성된 퀴즈 세트 (새로 추가)
class Quiz(Base):
    __tablename__ = "quizzes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True) # 퀴즈 이름 (예: 1~3과 종합평가)
    quiz_data = Column(Text) # 생성된 문제 JSON 문자열 저장