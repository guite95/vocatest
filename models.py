from sqlalchemy import Column, Integer, String, Text, DateTime # DateTime 추가됨
from datetime import datetime # datetime 추가됨
from database import Base

class WordSet(Base):
    __tablename__ = "word_sets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    content = Column(Text)

class Quiz(Base):
    __tablename__ = "quizzes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    quiz_data = Column(Text)
    available_from = Column(DateTime, default=datetime.now)