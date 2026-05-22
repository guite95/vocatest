from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from datetime import datetime
from database import Base

class WordSet(Base):
    __tablename__ = "word_sets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    content = Column(Text)
    words_json = Column(Text, nullable=True)

class Quiz(Base):
    __tablename__ = "quizzes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    quiz_data = Column(Text)
    available_from = Column(DateTime, default=datetime.now)

class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"))
    owner_username = Column(String)
    status = Column(String, default="waiting") # waiting, running, finished
    created_at = Column(DateTime, default=datetime.now)

class RoomParticipant(Base):
    __tablename__ = "room_participants"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"))
    username = Column(String)
    is_finished = Column(Boolean, default=False)
    joined_at = Column(DateTime, default=datetime.now)

class QuizRecord(Base):
    __tablename__ = "quiz_records"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"))
    graded_result_json = Column(Text)
    score = Column(Integer)
    created_at = Column(DateTime, default=datetime.now)