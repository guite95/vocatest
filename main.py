import os
import json
import httpx
import random
import string
from typing import Optional
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, Request, Body
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc, text
from pydantic import BaseModel
from database import SessionLocal, engine, Base
import models
from services import QuizService

# DB 초기화
Base.metadata.create_all(bind=engine)

app = FastAPI()

# 세션 미들웨어
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=1209600)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory="templates")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin1234")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 디스코드 설정
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")

async def get_current_user(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    request.session["last_access"] = str(datetime.now())
    return user

@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    try:
        # 스키마 자동 마이그레이션 (필요 시 추가)
        try:
            db.execute(text("SELECT words_json FROM word_sets LIMIT 1"))
        except Exception:
            db.execute(text("ALTER TABLE word_sets ADD COLUMN words_json TEXT"))
            db.commit()
            
        try:
            db.execute(text("SELECT available_from FROM quizzes LIMIT 1"))
        except Exception:
            db.execute(text("ALTER TABLE quizzes ADD COLUMN available_from DATETIME"))
            db.commit()

        word_sets = db.query(models.WordSet).filter(models.WordSet.words_json == None).all()
        if word_sets:
            for ws in word_sets:
                parsed_data = QuizService.extract_words_from_text(ws.content)
                ws.words_json = json.dumps(parsed_data, ensure_ascii=False)
            db.commit()
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
    available_from: Optional[datetime] = None

class GradeRequest(BaseModel):
    answers: list
    quiz_id: int
    room_code: Optional[str] = None

class RoomCreateRequest(BaseModel):
    quiz_id: int

class RoomJoinRequest(BaseModel):
    code: str

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")
    request.session["last_access"] = str(datetime.now())
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request=request, name="login.html")

@app.get("/auth/discord/login")
async def login_via_discord():
    if not DISCORD_CLIENT_ID or not DISCORD_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="서버 인증 설정 오류")
    return RedirectResponse(
        f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={DISCORD_REDIRECT_URI}&response_type=code&scope=identify"
    )

@app.get("/auth/discord/callback")
async def discord_callback(code: str, request: Request):
    async with httpx.AsyncClient() as client:
        token_resp = await client.post("https://discord.com/api/oauth2/token", data={
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DISCORD_REDIRECT_URI,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        
        if not access_token:
            raise HTTPException(status_code=400, detail="인증 실패")

        user_resp = await client.get("https://discord.com/api/users/@me", headers={
            "Authorization": f"Bearer {access_token}"
        })
        user_data = user_resp.json()
        request.session["user"] = {"id": user_data["id"], "username": user_data["username"]}
        
    return RedirectResponse(url="/")

@app.get("/api/me")
def get_me(request: Request):
    return request.session.get("user", None)

@app.get("/api/word-sets")
def read_word_sets(db: Session = Depends(get_db)):
    return db.query(models.WordSet).order_by(models.WordSet.id.desc()).all()

@app.post("/api/word-sets")
def create_word_set(item: WordSetCreate, db: Session = Depends(get_db)):
    if item.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="비밀번호가 틀렸습니다.")
    parsed_data = QuizService.extract_words_from_text(item.content)
    db_item = models.WordSet(name=item.name, content=item.content, words_json=json.dumps(parsed_data, ensure_ascii=False))
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@app.get("/api/quizzes")
def read_quizzes(db: Session = Depends(get_db)):
    return db.query(models.Quiz).order_by(models.Quiz.id.desc()).all()

@app.get("/api/quizzes/{quiz_id}")
def read_quiz(quiz_id: int, db: Session = Depends(get_db)):
    quiz = db.query(models.Quiz).filter(models.Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="퀴즈를 찾을 수 없습니다.")
    
    if quiz.available_from:
        now_kst = datetime.now() + timedelta(hours=9)
        if quiz.available_from > now_kst:
            raise HTTPException(status_code=403, detail="아직 시험이 공개되지 않았습니다.")

    return {"title": quiz.title, "quiz_data": json.loads(quiz.quiz_data)}

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
    
    combined_data = []
    for s in selected_sets:
        combined_data.append(json.loads(s.words_json) if s.words_json else QuizService.extract_words_from_text(s.content))

    try:
        final_quiz, en_cnt, kr_cnt = QuizService.generate_quiz_from_json(combined_data)
        start_time = req.available_from if req.available_from else datetime.now()
        db_quiz = models.Quiz(title=req.title, quiz_data=json.dumps(final_quiz, ensure_ascii=False), available_from=start_time)
        db.add(db_quiz)
        db.commit()
        return {"message": "퀴즈가 생성되었습니다.", "id": db_quiz.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"생성 실패: {str(e)}")

# --- Room APIs ---

@app.post("/api/rooms")
async def create_room(req: RoomCreateRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    code = ''.join(random.choices(string.digits, k=4))
    while db.query(models.Room).filter(models.Room.code == code).first():
        code = ''.join(random.choices(string.digits, k=4))
    
    db_room = models.Room(code=code, quiz_id=req.quiz_id, owner_username=user['username'], status="waiting")
    db.add(db_room)
    db.commit()
    db.refresh(db_room)
    
    participant = models.RoomParticipant(room_id=db_room.id, username=user['username'])
    db.add(participant)
    db.commit()
    
    return {"code": code}

@app.post("/api/rooms/join")
async def join_room(req: RoomJoinRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    room = db.query(models.Room).filter(models.Room.code == req.code).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다.")
    if room.status != "waiting":
        raise HTTPException(status_code=400, detail="이미 시작되었거나 종료된 방입니다.")
    
    existing = db.query(models.RoomParticipant).filter(models.RoomParticipant.room_id == room.id, models.RoomParticipant.username == user['username']).first()
    if not existing:
        participant = models.RoomParticipant(room_id=room.id, username=user['username'])
        db.add(participant)
        db.commit()
    
    return {"code": room.code}

@app.get("/api/rooms/{code}")
async def get_room_status(code: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    room = db.query(models.Room).filter(models.Room.code == code).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다.")
    
    participants = db.query(models.RoomParticipant).filter(models.RoomParticipant.room_id == room.id).all()
    
    return {
        "code": room.code,
        "quiz_id": room.quiz_id,
        "status": room.status,
        "owner": room.owner_username,
        "participants": [{"username": p.username, "is_finished": p.is_finished} for p in participants]
    }

@app.post("/api/rooms/{code}/start")
async def start_room_quiz(code: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    room = db.query(models.Room).filter(models.Room.code == code).first()
    if not room:
        raise HTTPException(status_code=404, detail="방을 찾을 수 없습니다.")
    if room.owner_username != user['username']:
        raise HTTPException(status_code=403, detail="방장만 시작할 수 있습니다.")
    
    room.status = "running"
    db.commit()
    return {"message": "시작되었습니다."}

@app.post("/api/quiz/grade")
async def grade_quiz(req: GradeRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        graded = QuizService.grade_answers(req.answers)
        correct_count = len([r for r in graded if r.get('is_correct')])
        score = int(round((correct_count / len(graded)) * 100)) if graded else 0
        
        room_id = None
        if req.room_code:
            room = db.query(models.Room).filter(models.Room.code == req.room_code).first()
            if room:
                room_id = room.id
                participant = db.query(models.RoomParticipant).filter(models.RoomParticipant.room_id == room.id, models.RoomParticipant.username == user['username']).first()
                if participant:
                    participant.is_finished = True
                
                total_p = db.query(models.RoomParticipant).filter(models.RoomParticipant.room_id == room.id).count()
                finished_p = db.query(models.RoomParticipant).filter(models.RoomParticipant.room_id == room.id, models.RoomParticipant.is_finished == True).count()
                if total_p == finished_p:
                    room.status = "finished"
                
                db.commit()

        record = models.QuizRecord(
            username=user['username'],
            room_id=room_id,
            quiz_id=req.quiz_id,
            graded_result_json=json.dumps(graded, ensure_ascii=False),
            score=score
        )
        db.add(record)
        db.commit()
        
        return graded
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"채점 실패: {str(e)}")

@app.get("/api/records/{quiz_id}")
async def get_quiz_record(quiz_id: int, username: str = None, room_code: str = None, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    target_username = username if username else user['username']
    
    query = db.query(models.QuizRecord).filter(models.QuizRecord.quiz_id == quiz_id, models.QuizRecord.username == target_username)
    
    if room_code:
        room = db.query(models.Room).filter(models.Room.code == room_code).first()
        if room:
            query = query.filter(models.QuizRecord.room_id == room.id)
            if target_username != user['username']:
                participants = db.query(models.RoomParticipant).filter(models.RoomParticipant.room_id == room.id).all()
                if not all(p.is_finished for p in participants):
                    raise HTTPException(status_code=403, detail="모든 참가자가 제출해야 볼 수 있습니다.")

    record = query.order_by(desc(models.QuizRecord.created_at)).first()
    if not record:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    
    return {
        "username": record.username,
        "score": record.score,
        "result": json.loads(record.graded_result_json)
    }

@app.get("/{full_path:path}", response_class=HTMLResponse)
async def spa_catch_all(request: Request, full_path: str):
    if full_path.startswith("api/") or full_path.startswith("static/") or full_path.startswith("auth/"):
        raise HTTPException(status_code=404)
    if full_path == "login":
        raise HTTPException(status_code=404)
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")
    request.session["last_access"] = str(datetime.now())
    return templates.TemplateResponse(request=request, name="index.html")
