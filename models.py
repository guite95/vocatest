from sqlalchemy import Column, Integer, String, Text
from database import Base

class WordSet(Base):
    __tablename__ = "word_sets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    content = Column(Text) # 사용자가 입력한 단어 목록 전체 텍스트