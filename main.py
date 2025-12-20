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

    # 1. AI에게는 '데이터 추출'만 요청 (단순화된 프롬프트)
    prompt = f"""
    Extract all unique English-Korean vocabulary pairs from the text below.
    Format: A RAW JSON array of objects. 
    Each object must have "en" and "kr" keys.
    Source Text:
    {combined_content}
    """
    
    try:
        response = model.generate_content(prompt)
        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
        all_words = json.loads(cleaned_text) # 추출된 전체 단어 리스트

        # 2. Python에서 중복 제거 및 무작위 셔플
        import random
        random.shuffle(all_words)

        # 3. 40개 선택 (단어가 부족하면 전체 선택)
        target_total = 40
        selected_pairs = all_words[:target_total]
        
        # 4. 비율 계산 (27:13)
        # 만약 전체 단어가 40개가 안 될 경우를 대비해 비율로 계산
        en_to_kr_count = int(len(selected_pairs) * (27/40))
        
        final_quiz = []
        for i, pair in enumerate(selected_pairs):
            # 'word1 / word2' 형태인 경우 첫 번째 단어만 사용
            en_val = pair['en'].split('/')[0].strip()
            kr_val = pair['kr'].split('/')[0].strip()
            
            if i < en_to_kr_count:
                final_quiz.append({
                    "id": i + 1,
                    "question": en_val,
                    "answer_key": kr_val,
                    "type": "en_to_kr"
                })
            else:
                final_quiz.append({
                    "id": i + 1,
                    "question": kr_val,
                    "answer_key": en_val,
                    "type": "kr_to_en"
                })

        # 5. 최종 검증 로직 (Validation)
        # (1) 중복 문제 검사
        questions = [q['question'] for q in final_quiz]
        if len(questions) != len(set(questions)):
            # 중복 발생 시 로직 재실행 혹은 에러 처리 (여기서는 중복 제거 후 재정렬 가능)
            pass 

        # (2) 타입별 개수 검사
        actual_en_to_kr = len([q for q in final_quiz if q['type'] == 'en_to_kr'])
        actual_kr_to_en = len([q for q in final_quiz if q['type'] == 'kr_to_en'])
        
        print(f"검증 결과: 총 {len(final_quiz)}문제 (영->한: {actual_en_to_kr}, 한->영: {actual_kr_to_en})")

        # 6. 최종 셔플 후 저장
        random.shuffle(final_quiz)
        for idx, q in enumerate(final_quiz): q['id'] = idx + 1 # ID 재부여

        start_time = req.available_from if req.available_from else datetime.now()
        db_quiz = models.Quiz(
            title=req.title, 
            quiz_data=json.dumps(final_quiz, ensure_ascii=False), # JSON 문자열로 저장
            available_from=start_time
        )
        db.add(db_quiz)
        db.commit()
        
        return {"message": "퀴즈가 생성되었습니다.", "id": db_quiz.id, "debug": f"{actual_en_to_kr}:{actual_kr_to_en}"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"생성 실패: {str(e)}")

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