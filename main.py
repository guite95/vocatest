import os
import json
import google.generativeai as genai
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import SessionLocal, engine, Base
import models

# 데이터베이스 테이블 생성 (스키마가 변경되었으므로 기존 db파일 삭제 권장)
Base.metadata.create_all(bind=engine)

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Gemini API 설정
GENAI_API_KEY = os.getenv("GENAI_API_KEY")
genai.configure(api_key=GENAI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin1234")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Pydantic Models ---
class WordSetCreate(BaseModel):
    name: str
    content: str
    password: str

class QuizCreateRequest(BaseModel):
    title: str
    word_set_ids: list[int] # 다중 선택된 범위 ID들
    password: str

class GradeRequest(BaseModel):
    answers: list

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# 1. 문제 범위(단어장) 목록 조회 (관리자용)
@app.get("/api/word-sets")
def read_word_sets(db: Session = Depends(get_db)):
    return db.query(models.WordSet).all()

# 2. 문제 범위 추가
@app.post("/api/word-sets")
def create_word_set(item: WordSetCreate, db: Session = Depends(get_db)):
    if item.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    
    db_item = models.WordSet(name=item.name, content=item.content)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

# 3. 퀴즈 목록 조회 (사용자용 메인 화면)
@app.get("/api/quizzes")
def read_quizzes(db: Session = Depends(get_db)):
    return db.query(models.Quiz).all()

# 4. 퀴즈 상세 조회 (시험 치기용)
@app.get("/api/quizzes/{quiz_id}")
def read_quiz(quiz_id: int, db: Session = Depends(get_db)):
    quiz = db.query(models.Quiz).filter(models.Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="퀴즈를 찾을 수 없습니다.")
    return json.loads(quiz.quiz_data)

# 5. 퀴즈 생성 및 저장 (관리자용 - 핵심 변경 기능)
@app.post("/api/quiz/create")
async def create_quiz(req: QuizCreateRequest, db: Session = Depends(get_db)):
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")

    # 선택된 모든 범위의 단어 합치기
    selected_sets = db.query(models.WordSet).filter(models.WordSet.id.in_(req.word_set_ids)).all()
    if not selected_sets:
        raise HTTPException(status_code=404, detail="선택된 범위가 없습니다.")
    
    combined_content = "\n".join([s.content for s in selected_sets])

    prompt = f"""
    You are a quiz generator.
    Source Text Format: "Number [tab/space] English Word [tab/space] Korean Meaning". 
    Example: "1 potter / pottery / pot 옹기장이 / 도자기"
    
    Task:
    1. Parse the source text below. Ignore the leading numbers.
    2. Create a JSON object with exactly 40 questions.
    3. Randomly select words from the source.
    4. Create 27 questions: Show English Word -> Ask Korean Meaning (type: "en_to_kr").
    5. Create 13 questions: Show Korean Meaning -> Ask English Word (type: "kr_to_en").
    6. Shuffle the order completely.
    7. Output ONLY raw JSON array.

    Source Text:
    {combined_content}
    
    JSON Format:
    [
        {{"id": 1, "question": "apple", "answer_key": "사과", "type": "en_to_kr"}},
        {{"id": 2, "question": "자동차", "answer_key": "car", "type": "kr_to_en"}}
    ]
    """
    
    try:
        response = model.generate_content(prompt)
        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
        # 유효성 검사
        json.loads(cleaned_text)
        
        # DB에 저장
        db_quiz = models.Quiz(title=req.title, quiz_data=cleaned_text)
        db.add(db_quiz)
        db.commit()
        
        return {"message": "퀴즈가 생성되었습니다.", "id": db_quiz.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 생성 실패: {str(e)}")

# 6. 채점 (기존 유지)
@app.post("/api/quiz/grade")
async def grade_quiz(req: GradeRequest):
    prompt = f"""
    You are an English teacher grading a vocabulary test.
    
    Rules:
    1. en_to_kr: If the user's Korean meaning is contextually similar, mark true.
    2. kr_to_en: If the user provides a valid synonym, mark true. Spelling must be correct.
    3. Return a RAW JSON array.

    Data:
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
        return json.loads(cleaned_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"채점 실패: {str(e)}")