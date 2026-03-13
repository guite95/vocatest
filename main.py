import os
import json
import httpx
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, Request, Body # [Body 추가]
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

# DB 초기화 (기존 데이터가 있다면 충돌날 수 있으니 db 파일 삭제 후 재시작 권장)
Base.metadata.create_all(bind=engine)

app = FastAPI()

# [추가] 세션 미들웨어 (시크릿 키는 환경변수로 관리 권장)
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
# max_age를 설정하여 브라우저를 닫아도 로그인이 유지되도록 함 (예: 14일 = 1209600초)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=1209600)

# [수정] 절대 경로를 사용하여 static 폴더 위치 지정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# 폴더가 없으면 생성
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

# [추가] 디스코드 설정
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI") # 예: https://your-domain.com/auth/discord/callback

# [추가] 사용자 세션 확인 의존성
async def get_current_user(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    # [추가] 세션 갱신 (Sliding Session): API 호출 시마다 세션 데이터 수정 -> 쿠키 유효기간 초기화
    request.session["last_access"] = str(datetime.now())
    return user

# [추가] 시작 시 데이터 마이그레이션 (기존 텍스트 -> JSON 변환)
@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    try:
        # [추가] 스키마 자동 마이그레이션 (기존 DB에 새 컬럼이 없으면 추가)
        try:
            db.execute(text("SELECT words_json FROM word_sets LIMIT 1"))
        except Exception:
            print("🔄 [Schema] 'words_json' 컬럼이 없어 추가합니다.")
            db.execute(text("ALTER TABLE word_sets ADD COLUMN words_json TEXT"))
            db.commit()
            
        try:
            db.execute(text("SELECT available_from FROM quizzes LIMIT 1"))
        except Exception:
            print("🔄 [Schema] 'available_from' 컬럼이 없어 추가합니다.")
            db.execute(text("ALTER TABLE quizzes ADD COLUMN available_from DATETIME"))
            db.commit()

        # 기존 데이터 마이그레이션 로직
        word_sets = db.query(models.WordSet).filter(models.WordSet.words_json == None).all()
        if word_sets:
            print(f"🔄 [Migration] {len(word_sets)}개의 단어장을 JSON 형식으로 변환합니다...")
            for ws in word_sets:
                parsed_data = QuizService.extract_words_from_text(ws.content)
                ws.words_json = json.dumps(parsed_data, ensure_ascii=False)
                print(f"   - '{ws.name}' 변환 완료 ({len(parsed_data)} 단어)")
            db.commit()
            print("✅ Migration 완료")
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
    # [수정] 세션이 없으면 디스코드 로그인으로 강제 리다이렉트
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")
    # [추가] 세션 갱신: 메인 페이지 접속 시에도 세션 유효기간 연장
    request.session["last_access"] = str(datetime.now())
    return templates.TemplateResponse("index.html", {"request": request})

# [추가] 별도의 로그인 페이지
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

# [추가] 디스코드 로그인 엔드포인트
@app.get("/auth/discord/login")
async def login_via_discord():
    if not DISCORD_CLIENT_ID or not DISCORD_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="서버 인증 설정 오류")
    return RedirectResponse(
        f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={DISCORD_REDIRECT_URI}&response_type=code&scope=identify"
    )

# [추가] 디스코드 콜백
@app.get("/auth/discord/callback")
async def discord_callback(code: str, request: Request):
    async with httpx.AsyncClient() as client:
        # 토큰 교환
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

        # 사용자 정보 조회
        user_resp = await client.get("https://discord.com/api/users/@me", headers={
            "Authorization": f"Bearer {access_token}"
        })
        user_data = user_resp.json()
        
        # 세션에 저장 (닉네임 등)
        request.session["user"] = {"id": user_data["id"], "username": user_data["username"]}
        
    return RedirectResponse(url="/")

# [추가] 현재 로그인 정보 확인 API
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
    
    # [수정] 저장 시 바로 JSON 파싱 수행
    parsed_data = QuizService.extract_words_from_text(item.content)
    db_item = models.WordSet(name=item.name, content=item.content, words_json=json.dumps(parsed_data, ensure_ascii=False))
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
    
    # [수정] DB에 저장된 JSON 데이터를 합쳐서 사용 (AI 호출 X -> 속도 대폭 향상)
    combined_data = []
    for s in selected_sets:
        if s.words_json:
            combined_data.append(json.loads(s.words_json))
        else:
            # 마이그레이션이 안 된 데이터가 있다면 즉석 파싱 (fallback)
            combined_data.append(QuizService.extract_words_from_text(s.content))

    try:
        final_quiz, en_cnt, kr_cnt = QuizService.generate_quiz_from_json(combined_data)

        start_time = req.available_from if req.available_from else datetime.now()
        db_quiz = models.Quiz(
            title=req.title, 
            quiz_data=json.dumps(final_quiz, ensure_ascii=False), # JSON 문자열로 저장
            available_from=start_time
        )
        db.add(db_quiz)
        db.commit()
        
        return {"message": "퀴즈가 생성되었습니다.", "id": db_quiz.id, "debug": f"{en_cnt}:{kr_cnt}"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"생성 실패: {str(e)}")

# [수정] 채점 API에 인증 의존성 추가
@app.post("/api/quiz/grade")
async def grade_quiz(req: GradeRequest, user: dict = Depends(get_current_user)):
    try:
        return QuizService.grade_answers(req.answers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"채점 실패: {str(e)}")

# [추가] SPA 프론트엔드 라우팅 지원 (새로고침 시 404 방지)
# 주의: 이 코드는 반드시 파일의 가장 마지막에 위치해야 합니다.
@app.get("/{full_path:path}", response_class=HTMLResponse)
async def spa_catch_all(request: Request, full_path: str):
    # API나 정적 파일, 인증 관련 요청은 제외 (404 반환)
    if full_path.startswith("api/") or full_path.startswith("static/") or full_path.startswith("auth/"):
        raise HTTPException(status_code=404)

    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login")
    request.session["last_access"] = str(datetime.now())
    return templates.TemplateResponse("index.html", {"request": request})