let adminPassword = "";
let currentQuizData = [];
let gradeResult = [];
let currentUser = null;

// [최적화] 타이머 변수 전역 관리
let activeInterval = null;
let wakeupTimeout = null;

// --- 라우팅 시스템 ---
function handleRoute() {
    const path = window.location.pathname;
    
    // 모든 뷰 숨기기
    document.querySelectorAll('[id^="view-"]').forEach(el => el.classList.add('hidden'));
    
    if (path === '/' || path === '/home') {
        showView('view-home');
        loadQuizzes();
    } else if (path.startsWith('/quiz/')) {
        const quizId = path.split('/')[2];
        showView('view-quiz-play');
        startQuizPlay(quizId);
    } else if (path === '/admin') {
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

function navigate(path) {
    window.history.pushState({}, "", path);
    handleRoute();
}

// 관리자 권한 체크 (간이)
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
        const loginBtn = document.getElementById('btn-login');
        if (currentUser) {
            loginBtn.classList.add('hidden'); // 로그인 상태면 버튼 숨김
        } else {
            loginBtn.innerHTML = `🔑 로그인 (Discord)`;
            loginBtn.onclick = () => window.location.href = '/auth/discord/login';
        }
    } catch (e) { console.error("Auth check failed", e); }
}

// --- 스마트 감시 시스템 ---
function startSmartMonitoring(quizzes) {
    if (activeInterval) clearInterval(activeInterval);
    if (wakeupTimeout) clearTimeout(wakeupTimeout);
    
    const now = new Date();
    let urgentQuizzes = [];
    let minDiffForNextWakeup = Infinity;

    quizzes.forEach(q => {
        const openTime = parseDateSafe(q.available_from);
        if (!openTime || openTime <= now) return;

        const diff = openTime - now;
        if (diff <= 60000) { 
            urgentQuizzes.push(q);
        } else {
            const timeUntilUrgent = diff - 60000;
            if (timeUntilUrgent < minDiffForNextWakeup) {
                minDiffForNextWakeup = timeUntilUrgent;
            }
        }
    });

    if (urgentQuizzes.length > 0) {
        activeInterval = setInterval(() => checkUrgentQuizzes(urgentQuizzes), 1000);
    }

    if (minDiffForNextWakeup !== Infinity) {
        wakeupTimeout = setTimeout(() => startSmartMonitoring(quizzes), minDiffForNextWakeup);
    }
}

function checkUrgentQuizzes(urgentList) {
    const now = new Date();
    let opened = false;
    urgentList.forEach((q, idx) => {
        if (!q) return;
        const openTime = parseDateSafe(q.available_from);
        if (openTime <= now) {
            myAlert(`📢 딩동! '${q.title}' 시험이 지금 공개되었습니다!`);
            delete urgentList[idx];
            opened = true;
        }
    });
    if (opened) loadQuizzes();
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

        startSmartMonitoring(res.data);
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
                    <div><h3 class="font-bold text-lg text-gray-800 ${isLocked ? 'text-gray-500' : ''}">${quiz.title}</h3>${timeText}</div>
                    <button onclick="event.stopPropagation(); deleteQuiz(${quiz.id})" class="text-gray-300 hover:text-red-500 p-2 rounded-full transition" title="삭제">X</button>
                </div>`;

            if (isLocked) {
                div.onclick = () => myAlert(`이 시험은 ${availableFrom.toLocaleString()}부터 볼 수 있습니다.`);
            } else {
                div.onclick = () => navigate(`/quiz/${quiz.id}`);
            }
            list.appendChild(div);
        });
    } catch(e) { console.error(e); }
}

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

async function startQuizPlay(quizId) {
    try {
        const res = await axios.get(`/api/quizzes/${quizId}`);
        currentQuizData = res.data;
        // 제목 설정 로직이 필요하다면 API에서 제목도 리턴받아야 함 (현재는 quiz_data만 리턴)
        // document.getElementById('play-title').innerText = "시험"; 
        renderQuizQuestions();
        window.scrollTo(0, 0);
    } catch(e) { 
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
    document.getElementById('btn-submit').classList.add('hidden');
    document.getElementById('grading-loading').classList.remove('hidden');
    
    const answers = currentQuizData.map((q, idx) => ({
        question: q.question, user_answer: document.getElementById(`answer-${idx}`).value, correct_answer: q.answer_key, type: q.type
    }));

    try {
        const res = await axios.post('/api/quiz/grade', { answers });
        gradeResult = res.data;
        renderResultTable();
        navigate('/result');
        window.scrollTo(0, 0);
    } catch(e) { await myAlert("채점 오류: " + (e.response?.data?.detail || e.message)); document.getElementById('btn-submit').classList.remove('hidden'); }
    finally { document.getElementById('grading-loading').classList.add('hidden'); }
}

function renderResultTable() {
    const tbody = document.getElementById('result-table-body');
    tbody.innerHTML = '';
    const score = Math.round((gradeResult.filter(r => r.is_correct).length / gradeResult.length) * 100);
    document.querySelector('#view-result h2').innerHTML = `채점 결과 <span class="text-blue-600 ml-2">(${score}점)</span>`;

    gradeResult.forEach(row => {
        const tr = document.createElement('tr');
        tr.className = row.is_correct ? '' : 'bg-red-50';
        tr.innerHTML = `<td class="px-4 py-3">${row.question}</td><td class="px-4 py-3 font-bold ${row.is_correct ? 'text-blue-600' : 'text-red-600'}">${row.user_answer}</td><td class="px-4 py-3 text-gray-500">${row.correct_answer}</td><td class="px-4 py-3 text-center">${row.is_correct ? '✅' : '❌'}</td>`;
        tbody.appendChild(tr);
    });
}

// --- 초기화 ---
window.addEventListener('popstate', handleRoute);
window.addEventListener('DOMContentLoaded', () => {
    checkLoginStatus();
    handleRoute();
});

// --- 오답노트 다운로드 ---
function downloadWrongAnswers() {
    if(typeof gradeResult === 'undefined' || gradeResult.length === 0) return myAlert("데이터가 없습니다.");
    const wrong = gradeResult.filter(r => !r.is_correct);
    if(wrong.length === 0) return myAlert("틀린 문제가 없습니다!");
    let text = "오답노트\n====================\n";
    wrong.forEach(r => text += `[문제] ${r.question}\n[내 답] ${r.user_answer}\n[정답] ${r.correct_answer}\n--------------------\n`);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], {type: 'text/plain'}));
    a.download = '오답노트.txt';
    a.click();
}

// --- 모달(알림창) 시스템 ---
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