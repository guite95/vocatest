import os
import json
from datetime import datetime, timedelta
import google.generativeai as genai
from fastapi import FastAPI, Depends, HTTPException, Request, Body # [Body 추가]
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
from database import SessionLocal, engine, Base
import models

# DB 초기화 (기존 데이터가 있다면 충돌날 수 있으니 db 파일 삭제 후 재시작 권장)
Base.metadata.create_all(bind=engine)

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Gemini API 설정 (사용자님의 gemini-2.0-flash 모델 적용)
GENAI_API_KEY = os.getenv("GENAI_API_KEY")
genai.configure(api_key=GENAI_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash') 

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin1234")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Models ---
class WordSetCreate(BaseModel):
    name: str
    content: str
    password: str

class QuizCreateRequest(BaseModel):
    title: str
    word_set_ids: list[int]
    password: str
    available_from: datetime = None # [추가] 공개 시간 (없으면 즉시 공개)

class GradeRequest(BaseModel):
    answers: list

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/word-sets")
def read_word_sets(db: Session = Depends(get_db)):
    return db.query(models.WordSet).order_by(models.WordSet.id.desc()).all()

@app.post("/api/word-sets")
def create_word_set(item: WordSetCreate, db: Session = Depends(get_db)):
    if item.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    db_item = models.WordSet(name=item.name, content=item.content)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@app.get("/api/quizzes")
def read_quizzes(db: Session = Depends(get_db)):
    return db.query(models.Quiz).order_by(models.Quiz.id.desc()).all()

# [수정] 퀴즈 상세 조회 (시간 제한 로직 추가)
@app.get("/api/quizzes/{quiz_id}")
def read_quiz(quiz_id: int, db: Session = Depends(get_db)):
    quiz = db.query(models.Quiz).filter(models.Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="퀴즈를 찾을 수 없습니다.")
    
    # [수정] 서버 시간(UTC)에 9시간을 더해 한국 시간(KST)으로 변환 후 비교
    if quiz.available_from:
        # 현재 서버 시간이 UTC라고 가정하고 9시간을 더해줌
        now_kst = datetime.now() + timedelta(hours=9)
        
        if quiz.available_from > now_kst:
            raise HTTPException(status_code=403, detail="아직 시험이 공개되지 않았습니다.")

    return json.loads(quiz.quiz_data)

# [추가] 퀴즈 삭제 API
@app.delete("/api/quizzes/{quiz_id}")
def delete_quiz(quiz_id: int, password: str = Body(..., embed=True), db: Session = Depends(get_db)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    
    quiz = db.query(models.Quiz).filter(models.Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="퀴즈를 찾을 수 없습니다.")
    
    db.delete(quiz)
    db.commit()
    return {"message": "삭제되었습니다."}

@app.post("/api/quiz/create")
async def create_quiz(req: QuizCreateRequest, db: Session = Depends(get_db)):
    if req.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")

    selected_sets = db.query(models.WordSet).filter(models.WordSet.id.in_(req.word_set_ids)).all()
    if not selected_sets:
        raise HTTPException(status_code=404, detail="선택된 범위가 없습니다.")
    
    combined_content = "\n".join([s.content for s in selected_sets])

    prompt = f"""
    You are a quiz generator.
    Source Text Format: "Number [tab/space] English Word [tab/space] Korean Meaning". 
    Example 1: "1 potter / pottery / pot 옹기장이 / 도자기"
    Example 2: "2 by chance 우연히"
    
    Task:
    1. Parse the source text below. Ignore the leading numbers.
    2. Create a JSON object with exactly 40 questions.
    3. Randomly select words from the source.
    4. If there are multiple English word divisions (e.g., "word1 / word2"), use only one as the answer.
    5. Create 27 questions: Show English Word -> Ask Korean Meaning (type: "en_to_kr").
    6. Create 13 questions: Show Korean Meaning -> Ask English Word (type: "kr_to_en").
    7. Shuffle the order completely.
    8. There must be no duplicate questions.
    9. One's English and Korean pair should not appear again in reverse.
    10. Important : en_to_kr : kr_to_en ratio must be exactly 27:13.
    11. Output ONLY raw JSON array.
    Source Text:
    {combined_content}
    
    JSON Format(only example, do not include in output):
    [
        {{"id": 1, "question": "apple", "answer_key": "사과", "type": "en_to_kr"}},
        {{"id": 2, "question": "자동차", "answer_key": "car", "type": "kr_to_en"}}
    ]
    """
    
    try:
        response = model.generate_content(prompt)
        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
        json.loads(cleaned_text) # 유효성 검사
        
        # 공개 시간 설정 (없으면 현재 시간)
        start_time = req.available_from if req.available_from else datetime.now()

        db_quiz = models.Quiz(
            title=req.title, 
            quiz_data=cleaned_text,
            available_from=start_time # [저장]
        )
        db.add(db_quiz)
        db.commit()
        
        return {"message": "퀴즈가 생성되었습니다.", "id": db_quiz.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 생성 실패: {str(e)}")

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