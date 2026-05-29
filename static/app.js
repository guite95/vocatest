let adminPassword = "";
let currentQuizData = [];
let gradeResult = [];
let currentUser = null;
let currentRoomCode = null;
let currentQuizId = null;
let currentViewingUser = null;
let latestParticipants = [];
let isQuizPlaying = false;

// [최적화] 타이머 변수 전역 관리
let activeInterval = null;
let wakeupTimeout = null;
let roomPollingInterval = null;

// --- 세션 및 상태 유지 ---
function saveSessionState() {
    sessionStorage.setItem('currentQuizId', currentQuizId || '');
    sessionStorage.setItem('currentRoomCode', currentRoomCode || '');
    sessionStorage.setItem('gradeResult', JSON.stringify(gradeResult || []));
    sessionStorage.setItem('currentViewingUser', currentViewingUser || '');
}

function loadSessionState() {
    currentQuizId = sessionStorage.getItem('currentQuizId') || null;
    if (currentQuizId) currentQuizId = parseInt(currentQuizId);
    currentRoomCode = sessionStorage.getItem('currentRoomCode') || null;
    try {
        gradeResult = JSON.parse(sessionStorage.getItem('gradeResult')) || [];
    } catch (e) {
        gradeResult = [];
    }
    currentViewingUser = sessionStorage.getItem('currentViewingUser') || null;
}

function clearSessionState() {
    currentQuizId = null;
    currentRoomCode = null;
    gradeResult = [];
    currentViewingUser = null;
    latestParticipants = [];
    sessionStorage.removeItem('currentQuizId');
    sessionStorage.removeItem('currentRoomCode');
    sessionStorage.removeItem('gradeResult');
    sessionStorage.removeItem('currentViewingUser');
}

function handleRoute() {
    const path = window.location.pathname;
    
    // 폴링 중지
    if (roomPollingInterval) {
        clearInterval(roomPollingInterval);
        roomPollingInterval = null;
    }

    // 모든 뷰 숨기기
    document.querySelectorAll('[id^="view-"]').forEach(el => el.classList.add('hidden'));
    
    if (path === '/' || path === '/home') {
        clearSessionState();
        showView('view-home');
        loadQuizzes();
    } else if (path.startsWith('/room/')) {
        clearSessionState();
        const code = path.split('/')[2];
        showView('view-room-waiting');
        startRoomWaiting(code);
    } else if (path.startsWith('/quiz/')) {
        clearSessionState();
        const quizId = path.split('/')[2];
        showView('view-quiz-play');
        startQuizPlay(quizId);
    } else if (path === '/admin') {
        clearSessionState();
        checkAdminAuth(() => showView('view-admin'));
    } else if (path === '/admin/add') {
        checkAdminAuth(() => showView('view-admin-range'));
    } else if (path === '/admin/create') {
        checkAdminAuth(() => {
            showView('view-admin-create-quiz');
            loadRangesForQuiz();
        });
    } else if (path === '/result') {
        showView('view-result');
        if (gradeResult && gradeResult.length > 0) {
            renderResultTable(gradeResult, currentViewingUser || currentUser?.username);
        }
        if (currentRoomCode) {
            startResultPolling(currentRoomCode);
        }
    } else {
        navigate('/');
    }
}

function showView(viewId) {
    const el = document.getElementById(viewId);
    if(el) {
        el.classList.remove('hidden');
        el.classList.add('animate-fade-in');
    }
}

async function navigate(path) {
    if (isQuizPlaying && path !== '/result') {
        const confirmExit = await myConfirm("정말 시험을 종료하고 나가시겠습니까? 지금까지 푼 답변이 모두 지워집니다.");
        if (!confirmExit) return;
    }
    isQuizPlaying = false;
    window.history.pushState({}, "", path);
    handleRoute();
}

// 관리자 권한 체크
async function checkAdminAuth(callback) {
    if (adminPassword) {
        callback();
    } else {
        const pw = await myPrompt("관리자 비밀번호를 입력하세요:", "비밀번호");
        if (pw) {
            adminPassword = pw;
            callback();
        } else {
            navigate('/');
        }
    }
}

// --- 유틸리티 ---
function parseDateSafe(dateString) {
    if (!dateString) return null;
    return new Date(dateString.replace(" ", "T"));
}

// --- 인증 관련 ---
async function checkLoginStatus() {
    try {
        const res = await axios.get('/api/me');
        currentUser = res.data;
    } catch (e) { console.error("Auth check failed", e); }
}

// --- 앱 로직 ---
async function loadQuizzes() {
    try {
        const res = await axios.get('/api/quizzes');
        const list = document.getElementById('quiz-list');
        list.innerHTML = '';
        
        if(res.data.length === 0) {
            list.innerHTML = `<div class="text-center py-10 bg-gray-50 rounded-lg"><p class="text-gray-500">생성된 퀴즈가 없습니다.</p></div>`;
            return;
        }

        const now = new Date(); 

        res.data.forEach(quiz => {
            const availableFrom = parseDateSafe(quiz.available_from);
            const isLocked = availableFrom && availableFrom > now;
            
            const div = document.createElement('div');
            div.className = `relative p-6 rounded-xl border border-gray-200 shadow-sm transition group ${isLocked ? 'bg-gray-100 cursor-not-allowed' : 'bg-white hover:border-blue-400 cursor-pointer hover:shadow-md'}`;
            
            let timeText = isLocked 
                ? `<div class="text-red-500 text-sm font-bold flex items-center gap-1">🔒 ${availableFrom.toLocaleString()} 오픈</div>`
                : `<div class="text-blue-600 text-sm font-bold flex items-center gap-1">▶ 도전 가능</div>`;

            div.innerHTML = `
                <div class="flex justify-between items-start">
                    <div class="flex-1">
                        <h3 class="font-bold text-lg text-gray-800 ${isLocked ? 'text-gray-500' : ''}">${quiz.title}</h3>
                        ${timeText}
                    </div>
                    <div class="flex gap-2">
                        ${!isLocked ? `<button onclick="event.stopPropagation(); createRoom(${quiz.id})" class="bg-blue-50 text-blue-600 px-3 py-1 rounded-lg text-xs font-bold hover:bg-blue-100">🏠 방 만들기</button>` : ''}
                        <button onclick="event.stopPropagation(); deleteQuiz(${quiz.id})" class="text-gray-300 hover:text-red-500 p-1 rounded-full transition" title="삭제">✕</button>
                    </div>
                </div>`;

            if (isLocked) {
                div.onclick = () => myAlert(`이 시험은 ${availableFrom.toLocaleString()}부터 볼 수 있습니다.`);
            } else {
                div.onclick = () => {
                    currentRoomCode = null;
                    navigate(`/quiz/${quiz.id}`);
                };
            }
            list.appendChild(div);
        });
    } catch(e) { console.error(e); }
}

// --- Room Logic ---
async function createRoom(quizId) {
    try {
        const res = await axios.post('/api/rooms', { quiz_id: quizId });
        navigate(`/room/${res.data.code}`);
    } catch (e) { await myAlert("방 생성 실패: " + (e.response?.data?.detail || e.message)); }
}

async function joinRoomByCode() {
    const code = document.getElementById('join-room-code').value;
    if (!code || code.length !== 4) return myAlert("4자리 참여 코드를 입력해주세요.");
    try {
        await axios.post('/api/rooms/join', { code });
        navigate(`/room/${code}`);
    } catch (e) { await myAlert("입장 실패: " + (e.response?.data?.detail || e.message)); }
}

async function startRoomWaiting(code) {
    currentRoomCode = code;
    updateRoomUI(code);
    saveSessionState();
    
    // 폴링 시작
    if (roomPollingInterval) clearInterval(roomPollingInterval);
    roomPollingInterval = setInterval(() => pollRoomStatus(code), 3000);
    pollRoomStatus(code); // 즉시 1회 실행
}

async function pollRoomStatus(code) {
    try {
        const res = await axios.get(`/api/rooms/${code}`);
        const room = res.data;
        currentQuizId = room.quiz_id;

        // UI 업데이트
        document.getElementById('participant-count').innerText = room.participants.length;
        const list = document.getElementById('room-participant-list');
        list.innerHTML = room.participants.map(p => `
            <div class="bg-white p-3 rounded-xl border border-gray-200 text-center shadow-sm">
                <div class="text-xs text-gray-400 mb-1">${p.username === room.owner ? '👑 방장' : '👤 유저'}</div>
                <div class="font-bold text-gray-800 truncate">${p.username}</div>
            </div>
        `).join('');

        // 방장인 경우 시작 버튼 표시
        if (room.owner === currentUser?.username) {
            document.getElementById('btn-start-quiz').classList.remove('hidden');
            document.getElementById('waiting-msg').classList.add('hidden');
        } else {
            document.getElementById('btn-start-quiz').classList.add('hidden');
            document.getElementById('waiting-msg').classList.remove('hidden');
        }

        // 시험 시작 체크
        if (room.status === 'running') {
            clearInterval(roomPollingInterval);
            roomPollingInterval = null;
            navigate(`/quiz/${room.quiz_id}`);
        }
    } catch (e) {
        clearInterval(roomPollingInterval);
        roomPollingInterval = null;
        myAlert("방 정보를 불러올 수 없습니다.");
        navigate('/');
    }
}

async function startRoomQuiz() {
    try {
        await axios.post(`/api/rooms/${currentRoomCode}/start`);
    } catch (e) { myAlert("시작 실패: " + (e.response?.data?.detail || e.message)); }
}

function updateRoomUI(code) {
    document.getElementById('room-code-display').innerText = code;
}

// --- Result Polling ---
function startResultPolling(code) {
    if (roomPollingInterval) clearInterval(roomPollingInterval);
    const poll = async () => {
        try {
            const res = await axios.get(`/api/rooms/${code}`);
            latestParticipants = res.data.participants;
            renderParticipantStatus(latestParticipants);
        } catch (e) { clearInterval(roomPollingInterval); }
    };
    roomPollingInterval = setInterval(poll, 3000);
    poll();
}

function renderParticipantStatus(participants) {
    const list = document.getElementById('result-participant-list');
    if (!list) return;
    const allFinished = participants.every(p => p.is_finished);
    
    if (!currentViewingUser && currentUser) {
        currentViewingUser = currentUser.username;
    }
    
    list.innerHTML = participants.map(p => {
        const isMe = p.username === currentUser?.username;
        const canClick = isMe || allFinished;
        const isCurrentViewing = p.username === currentViewingUser;
        
        let borderClass = p.is_finished ? 'bg-blue-50 border-blue-200' : 'bg-gray-50 border-gray-200';
        if (isCurrentViewing) {
            borderClass = 'bg-blue-100 border-blue-500 ring-2 ring-blue-200 shadow-sm';
        }
        
        let textClass = p.is_finished ? 'text-blue-700' : 'text-gray-500';
        if (isCurrentViewing) {
            textClass = 'text-blue-800 font-extrabold';
        }
        
        const displayName = p.username + (isMe ? ' (나)' : '');
        
        return `
            <div onclick="${canClick ? `viewOtherResult('${p.username}')` : ''}" 
                 class="flex items-center justify-between p-2.5 rounded-lg border ${borderClass} ${canClick ? 'cursor-pointer hover:bg-blue-100 hover:scale-[1.02] transition-all duration-200' : ''}">
                <span class="text-sm font-bold ${textClass}">${displayName}</span>
                <span class="text-[10px] ${p.is_finished ? 'bg-blue-600 text-white font-semibold' : 'bg-gray-300 text-white'} px-2 py-0.5 rounded-full">
                    ${p.is_finished ? '제출완료' : '풀고있음'}
                </span>
            </div>
        `;
    }).join('');

    document.getElementById('result-notice').innerText = allFinished ? "✅ 전원 제출 완료! 이름을 클릭하여 오답을 확인하세요." : "* 전원 제출 완료 시 이름을 클릭하여 오답 노트를 확인할 수 있습니다.";
}

async function viewOtherResult(username) {
    try {
        const res = await axios.get(`/api/records/${currentQuizId}?username=${username}&room_code=${currentRoomCode}`);
        renderResultTable(res.data.result, username, res.data.score);
    } catch (e) { myAlert("기록을 불러올 수 없습니다."); }
}

// --- Quiz Logic ---
async function startQuizPlay(quizId) {
    currentQuizId = quizId;
    isQuizPlaying = true;
    saveSessionState();
    
    // 이전 시험 제출 후 숨겨진 버튼과 로딩 창 상태 초기화
    const submitBtn = document.getElementById('btn-submit');
    if (submitBtn) submitBtn.classList.remove('hidden');
    const loadingSpinner = document.getElementById('grading-loading');
    if (loadingSpinner) loadingSpinner.classList.add('hidden');

    try {
        const res = await axios.get(`/api/quizzes/${quizId}`);
        currentQuizData = res.data.quiz_data;
        document.getElementById('play-title').innerText = res.data.title;
        renderQuizQuestions();
        window.scrollTo(0, 0);
    } catch(e) { 
        isQuizPlaying = false;
        await myAlert("오류: " + (e.response?.data?.detail || "문제를 불러올 수 없습니다.")); 
        navigate('/');
    }
}

function renderQuizQuestions() {
    const container = document.getElementById('quiz-container');
    container.innerHTML = '';
    currentQuizData.forEach((q, idx) => {
        const isEngToKor = q.type === 'en_to_kr';
        const div = document.createElement('div');
        div.className = 'bg-white p-6 rounded-xl border border-gray-200 shadow-sm';
        div.innerHTML = `
            <div class="flex items-center gap-3 mb-4"><span class="bg-blue-100 text-blue-800 font-bold px-3 py-1 rounded-lg text-sm">Q${idx+1}</span><span class="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">${isEngToKor ? '뜻 쓰기' : '단어 쓰기'}</span></div>
            <div class="mb-4 text-xl font-bold text-gray-800">${q.question}</div>
            <input type="text" id="answer-${idx}" class="w-full border-b-2 border-gray-200 bg-gray-50 p-3 rounded-t-md focus:border-blue-500 focus:outline-none text-lg" placeholder="정답 입력" autocomplete="off">
        `;
        container.appendChild(div);
    });
}

async function submitQuiz() {
    if(!currentUser) {
        await myAlert("채점하려면 로그인이 필요합니다.");
        window.location.href = '/auth/discord/login';
        return;
    }
    if(!await myConfirm("제출하시겠습니까?")) return;
    isQuizPlaying = false;
    document.getElementById('btn-submit').classList.add('hidden');
    document.getElementById('grading-loading').classList.remove('hidden');
    
    const answers = currentQuizData.map((q, idx) => ({
        question: q.question, user_answer: document.getElementById(`answer-${idx}`).value, correct_answer: q.answer_key, type: q.type
    }));

    try {
        const res = await axios.post('/api/quiz/grade', { 
            answers, 
            quiz_id: currentQuizId, 
            room_code: currentRoomCode 
        });
        gradeResult = res.data;
        renderResultTable(gradeResult, currentUser.username);
        navigate('/result');
        window.scrollTo(0, 0);
    } catch(e) { 
        await myAlert("채점 오류: " + (e.response?.data?.detail || e.message)); 
        document.getElementById('btn-submit').classList.remove('hidden'); 
    } finally { 
        document.getElementById('grading-loading').classList.add('hidden'); 
    }
}

function renderResultTable(data, username, scoreOverride = null) {
    currentViewingUser = username;
    saveSessionState();
    const tbody = document.getElementById('result-table-body');
    tbody.innerHTML = '';
    
    let score = scoreOverride;
    if (score === null) {
        const correctCount = data.filter(r => r.is_correct).length;
        score = Math.round((correctCount / data.length) * 100);
    }

    document.querySelector('#view-result h2').innerHTML = `채점 결과 <span class="text-blue-600 ml-2">(${score}점)</span>`;
    document.getElementById('result-user-display').innerText = `${username}님의 시험 결과입니다.`;

    data.forEach(row => {
        const tr = document.createElement('tr');
        tr.className = row.is_correct ? '' : 'bg-red-50';
        tr.innerHTML = `
            <td class="px-4 py-3">${row.question}</td>
            <td class="px-4 py-3 font-bold ${row.is_correct ? 'text-blue-600' : 'text-red-600'}">${row.user_answer}</td>
            <td class="px-4 py-3 text-gray-500">${row.correct_answer}</td>
            <td class="px-4 py-3 text-center">${row.is_correct ? '✅' : '❌'}</td>
        `;
        tbody.appendChild(tr);
    });

    if (latestParticipants && latestParticipants.length > 0) {
        renderParticipantStatus(latestParticipants);
    }
}

// --- 관리자/단어장 로직 ---
async function deleteQuiz(quizId) {
    const pw = await myPrompt("시험지를 삭제하시겠습니까?\n관리자 비밀번호를 입력하세요:", "비밀번호");
    if (!pw) return;
    try {
        await axios.delete(`/api/quizzes/${quizId}`, { data: { password: pw } });
        await myAlert("삭제되었습니다.");
        loadQuizzes();
    } catch (e) { await myAlert("삭제 실패: " + (e.response?.data?.detail || e.message)); }
}

async function createWordRange() {
    const name = document.getElementById('range-name').value;
    const content = document.getElementById('range-content').value;
    if(!name || !content) return await myAlert("내용을 입력해주세요.");
    try {
        await axios.post('/api/word-sets', { name, content, password: adminPassword });
        await myAlert('저장되었습니다!');
        document.getElementById('range-name').value = '';
        document.getElementById('range-content').value = '';
        navigate('/admin');
    } catch (e) { await myAlert('실패: ' + (e.response?.data?.detail || e.message)); }
}

async function loadRangesForQuiz() {
    try {
        const res = await axios.get('/api/word-sets');
        const list = document.getElementById('range-checkbox-list');
        list.innerHTML = '';
        if(res.data.length === 0) return await myAlert("등록된 단어장이 없습니다.");
        res.data.forEach(set => {
            list.innerHTML += `<label class="flex items-center space-x-3 p-3 hover:bg-blue-50 rounded-lg cursor-pointer"><input type="checkbox" value="${set.id}" class="range-chk w-5 h-5 text-blue-600"><span class="text-gray-700">${set.name}</span></label>`;
        });
    } catch(e) { await myAlert("로딩 실패"); }
}

async function generateAndSaveQuiz() {
    const title = document.getElementById('quiz-title').value;
    const dateVal = document.getElementById('quiz-available-from').value;
    const checkboxes = document.querySelectorAll('.range-chk:checked');
    const ids = Array.from(checkboxes).map(cb => parseInt(cb.value));

    if(!title) return await myAlert("제목을 입력해주세요.");
    if(ids.length === 0) return await myAlert("범위를 선택해주세요.");

    document.getElementById('btn-gen-quiz').classList.add('hidden');
    document.getElementById('gen-loading').classList.remove('hidden');

    try {
        await axios.post('/api/quiz/create', {
            title: title, word_set_ids: ids, password: adminPassword, available_from: dateVal || null
        });
        await myAlert('퀴즈 생성 완료!');
        navigate('/'); 
    } catch (e) {
        await myAlert('생성 실패: ' + (e.response?.data?.detail || e.message));
    } finally {
        document.getElementById('btn-gen-quiz').classList.remove('hidden');
        document.getElementById('gen-loading').classList.add('hidden');
    }
}

// --- 오답노트 다운로드 ---
function downloadWrongAnswers() {
    if(!gradeResult || gradeResult.length === 0) return myAlert("데이터가 없습니다.");
    const wrong = gradeResult.filter(r => !r.is_correct);
    if(wrong.length === 0) return myAlert("틀린 문제가 없습니다!");
    let text = "오답노트\n====================\n";
    wrong.forEach(r => text += `[문제] ${r.question}\n[내 답] ${r.user_answer}\n[정답] ${r.correct_answer}\n--------------------\n`);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], {type: 'text/plain'}));
    a.download = '오답노트.txt';
    a.click();
}

// --- 모달 시스템 ---
function showModal({ type, title, message, placeholder = "" }) {
    return new Promise((resolve) => {
        const backdrop = document.getElementById('custom-modal-backdrop');
        const content = document.getElementById('custom-modal-content');
        const titleEl = document.getElementById('modal-title');
        const msgEl = document.getElementById('modal-message');
        const inputEl = document.getElementById('modal-input');
        const btnContainer = document.getElementById('modal-buttons');

        titleEl.innerText = title;
        msgEl.innerText = message;
        btnContainer.innerHTML = '';
        inputEl.value = '';
        
        if (type === 'prompt') {
            inputEl.classList.remove('hidden');
            inputEl.placeholder = placeholder;
        } else {
            inputEl.classList.add('hidden');
        }

        const createBtn = (text, cls, onClick) => {
            const btn = document.createElement('button');
            btn.innerText = text;
            btn.className = `px-4 py-2 rounded-lg font-bold transition ${cls}`;
            btn.onclick = () => { closeModal(); onClick(); };
            btnContainer.appendChild(btn);
        };

        if (type === 'alert') {
            createBtn("확인", "bg-blue-600 text-white hover:bg-blue-700 flex-1", () => resolve(true));
        } else if (type === 'confirm') {
            createBtn("취소", "bg-gray-200 text-gray-700 hover:bg-gray-300", () => resolve(false));
            createBtn("확인", "bg-blue-600 text-white hover:bg-blue-700", () => resolve(true));
        } else if (type === 'prompt') {
            createBtn("취소", "bg-gray-200 text-gray-700 hover:bg-gray-300", () => resolve(null));
            createBtn("확인", "bg-indigo-600 text-white hover:bg-indigo-700", () => resolve(inputEl.value));
            inputEl.onkeydown = (e) => { if(e.key === 'Enter') { closeModal(); resolve(inputEl.value); } };
        }

        backdrop.classList.remove('hidden');
        setTimeout(() => {
            content.classList.remove('scale-95', 'opacity-0');
            content.classList.add('scale-100', 'opacity-100');
            if(type==='prompt') inputEl.focus();
        }, 10);
    });
}

function closeModal() {
    const backdrop = document.getElementById('custom-modal-backdrop');
    const content = document.getElementById('custom-modal-content');
    content.classList.remove('scale-100', 'opacity-100');
    content.classList.add('scale-95', 'opacity-0');
    setTimeout(() => { backdrop.classList.add('hidden'); }, 200);
}

async function myAlert(msg) { await showModal({ type: 'alert', title: '알림', message: msg }); }
async function myConfirm(msg) { return await showModal({ type: 'confirm', title: '확인', message: msg }); }
async function myPrompt(msg, placeholder) { return await showModal({ type: 'prompt', title: '입력', message: msg, placeholder: placeholder }); }

// --- 이탈 경고 및 복구 핸들러 ---
function handleBeforeUnload(e) {
    if (isQuizPlaying) {
        e.preventDefault();
        e.returnValue = '';
    }
}

async function handlePopState() {
    if (isQuizPlaying) {
        const confirmExit = await myConfirm("정말 시험을 종료하고 나가시겠습니까? 지금까지 푼 답변이 모두 지워집니다.");
        if (!confirmExit) {
            window.history.pushState({}, "", `/quiz/${currentQuizId}`);
            return;
        }
        isQuizPlaying = false;
    }
    handleRoute();
}

window.addEventListener('beforeunload', handleBeforeUnload);
window.removeEventListener('popstate', handleRoute);
window.addEventListener('popstate', handlePopState);

window.addEventListener('DOMContentLoaded', async () => {
    loadSessionState();
    await checkLoginStatus();
    handleRoute();
});
