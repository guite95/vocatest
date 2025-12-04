import os
import json
import google.generativeai as genai
from fastapi import FastAPI, Depends, HTTPException, Request, Body
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import SessionLocal, engine, Base
import models

# 데이터베이스 테이블 생성
Base.metadata.create_all(bind=engine)

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Gemini API 설정
GENAI_API_KEY = os.getenv("GENAI_API_KEY")
genai.configure(api_key=GENAI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash') # 가볍고 빠른 모델

# 관리자 비밀번호
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin1234")

# 의존성: DB 세션
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Pydantic 모델
class WordSetCreate(BaseModel):
    name: str
    content: str
    password: str

class GenerateQuizRequest(BaseModel):
    word_set_id: int
    password: str

class GradeRequest(BaseModel):
    answers: list # [{question: "", user_answer: "", type: "en_to_kr" | "kr_to_en"}]

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/word-sets")
def read_word_sets(db: Session = Depends(get_db)):
    return db.query(models.WordSet).all()

@app.post("/api/word-sets")
def create_word_set(item: WordSetCreate, db: Session = Depends(get_db)):
    if item.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    
    db_item = models.WordSet(name=item.name, content=item.content)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@app.post("/api/quiz/generate")
async def generate_quiz(req: GenerateQuizRequest, db: Session = Depends(get_db)):
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")

    word_set = db.query(models.WordSet).filter(models.WordSet.id == req.word_set_id).first()
    if not word_set:
        raise HTTPException(status_code=404, detail="단어장을 찾을 수 없습니다.")

    prompt = f"""
    You are a quiz generator. I have a list of words.
    Create a JSON object with exactly 40 questions.
    
    Source Words:
    {word_set.content}

    Rules:
    1. Randomly select words from the source.
    2. Create 27 questions where you show the English word and ask for the Korean meaning (type: "en_to_kr").
    3. Create 13 questions where you show the Korean meaning and ask for the English word (type: "kr_to_en").
    4. Shuffle the order of questions completely.
    5. The output must be a RAW JSON array. No markdown formatting.
    
    JSON Format:
    [
        {{"id": 1, "question": "apple", "answer_key": "사과", "type": "en_to_kr"}},
        {{"id": 2, "question": "자동차", "answer_key": "car", "type": "kr_to_en"}}
    ]
    """
    
    try:
        response = model.generate_content(prompt)
        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
        quiz_data = json.loads(cleaned_text)
        return quiz_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 생성 실패: {str(e)}")

@app.post("/api/quiz/grade")
async def grade_quiz(req: GradeRequest):
    # 채점 로직을 Gemini에게 위임
    prompt = f"""
    You are an English teacher grading a vocabulary test.
    Compare the user's answer with the correct answer key.
    
    Rules:
    1. For "en_to_kr" (English -> Korean): If the user's Korean meaning is contextually similar or close enough, mark it correct (true).
    2. For "kr_to_en" (Korean -> English): If the user provides a valid synonym (e.g., 'huge' for 'enormous'), mark it correct (true). Spelling mistakes should be marked incorrect.
    3. Return a RAW JSON array. No markdown.

    Data to grade:
    {json.dumps(req.answers, ensure_ascii=False)}

    Output Format:
    [
        {{"question": "...", "user_answer": "...", "correct_answer": "...", "is_correct": true}},
        ...
    ]
    """
    
    try:
        response = model.generate_content(prompt)
        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
        graded_data = json.loads(cleaned_text)
        return graded_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"채점 실패: {str(e)}")