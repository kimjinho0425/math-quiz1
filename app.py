# app.py — Streamlit Math Quiz (계정 로그인 & 자동 로그인 + 재출제 방지 복원)
# - 첫 화면에 회원가입 + 로그인 동시 표시
# - 계정: 이름(고유) + 비밀번호(salt+SHA256 해시) → 서버측 파일(data/accounts.csv)에 영구 저장
# - 어디서 접속해도(새로고침/창닫음/다른 기기) 비밀번호가 맞으면 로그인
# - 로그인 유지 체크 시: 영속 쿠키로 자동 로그인 (약 20년)
# - 새로고침해도 이미 푼 문제는 진행 기록에서 복원하여 재출제 방지

import time, hashlib, re, os, urllib.parse
from pathlib import Path
from typing import Dict, Any
import pandas as pd
import streamlit as st

st.set_page_config(page_title="수학 퀴즈", page_icon="🧮", layout="centered")

# ===== 계정 & 로그인 유지 =====
SECRET_SALT = "KEEP_THIS_CONSTANT_AND_PRIVATE"  # 원하면 다른 임의 문자열로 교체

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
ACCOUNTS_FILE = DATA_DIR / "accounts.csv"  # name, pwd_hash, salt, created_at

def _ensure_accounts_csv():
    if not ACCOUNTS_FILE.exists():
        pd.DataFrame(columns=["name","pwd_hash","salt","created_at"]).to_csv(
            ACCOUNTS_FILE, index=False, encoding="utf-8-sig"
        )

def _hash_pw(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

def _make_sig(name: str, pwd_hash: str) -> str:
    base = f"{name}|{pwd_hash}|{SECRET_SALT}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]

# --- 쿠키 호환 레이어 (버전별 대응) ---
def _has_exp_cookies() -> bool:
    return all(
        hasattr(st, attr) for attr in [
            "experimental_set_cookie", "experimental_get_cookie", "experimental_delete_cookie"
        ]
    )

def _cget(k: str, default: str = "") -> str:
    if _has_exp_cookies():
        v = st.experimental_get_cookie(k)
        return v if v is not None else default
    if hasattr(st, "cookies") and k in st.cookies:
        return st.cookies.get(k, default)
    return default

def _cset(k: str, v: str):
    if _has_exp_cookies():
        st.experimental_set_cookie(
            k, v, max_age=60*60*24*365*20, secure=True, samesite="Lax"  # 약 20년
        )
        return
    if hasattr(st, "cookies"):
        st.cookies[k] = v

def _cdel(k: str):
    if _has_exp_cookies():
        st.experimental_delete_cookie(k, samesite="Lax")
        return
    if hasattr(st, "cookies"):
        try:
            del st.cookies[k]
        except Exception:
            st.cookies[k] = ""

def _persist_login(name: str, pwd_hash: str):
    _cset("acc_name", name)
    _cset("acc_sig", _make_sig(name, pwd_hash))

def _clear_login():
    _cdel("acc_name"); _cdel("acc_sig")

def _load_account_row(name: str):
    try:
        df = pd.read_csv(ACCOUNTS_FILE)
        df["name"] = df["name"].astype(str).str.strip()
        row = df[df["name"] == name.strip()]
        if row.empty:
            return None
        r = row.iloc[0]
        return {"name": r["name"], "pwd_hash": str(r["pwd_hash"]), "salt": str(r["salt"])}
    except Exception:
        return None

def _account_exists(name: str) -> bool:
    try:
        df = pd.read_csv(ACCOUNTS_FILE)
        return name.strip() in df["name"].astype(str).str.strip().values
    except Exception:
        return False

def _create_account(name: str, password: str) -> bool:
    if not name or not password:
        return False
    if _account_exists(name):
        return False
    salt = os.urandom(8).hex()
    pwd_hash = _hash_pw(password, salt)
    row = {
        "name": name.strip(),
        "pwd_hash": pwd_hash,
        "salt": salt,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    header_needed = (not ACCOUNTS_FILE.exists()) or pd.read_csv(ACCOUNTS_FILE).empty
    pd.DataFrame([row]).to_csv(ACCOUNTS_FILE, mode="a",
                               header=header_needed, index=False, encoding="utf-8-sig")
    return True

def _verify_login(name: str, password: str) -> bool:
    acc = _load_account_row(name)
    if not acc:
        return False
    return _hash_pw(password, acc["salt"]) == acc["pwd_hash"]

def _auto_login_from_cookie() -> bool:
    name = _cget("acc_name")
    sig = _cget("acc_sig")
    if not name or not sig:
        return False
    acc = _load_account_row(name)
    if not acc:
        return False
    if sig == _make_sig(name, acc["pwd_hash"]):
        st.session_state.auth = {"name": name, "remember": True}
        st.session_state.locked_name = name
        return True
    return False

def auth_gate():
    """첫 화면: 회원가입 + 로그인 폼 동시 표시. 로그인 성공 시 통과."""
    _ensure_accounts_csv()
    ss = st.session_state

    # 이미 세션 로그인
    if ss.get("auth") and ss.auth.get("name"):
        return True
    # 쿠키 자동 로그인
    if _auto_login_from_cookie():
        return True

    st.markdown("## 🔐 로그인 / 회원가입")

    c1, c2 = st.columns(2)
    # --- 회원가입 ---
    with c1:
        st.markdown("#### 회원가입")
        with st.form("signup_form", clear_on_submit=False):
            su_name = st.text_input("이름(중복 불가)", key="su_name")
            su_pw = st.text_input("비밀번호", type="password", key="su_pw")
            su_submit = st.form_submit_button("회원가입")
        if su_submit:
            name = (su_name or "").strip()
            pw = (su_pw or "").strip()
            if not name:
                st.error("이름을 입력하세요.")
                st.stop()
            if not pw:
                st.error("비밀번호를 입력하세요.")
                st.stop()
            if _account_exists(name):
                st.error(f"'{name}' 은(는) 이미 가입된 이름입니다.")
                st.stop()
            ok = _create_account(name, pw)
            if ok:
                st.success("회원가입 완료! 오른쪽 폼에서 로그인하세요.")

    # --- 로그인 ---
    with c2:
        st.markdown("#### 로그인")
        with st.form("login_form", clear_on_submit=False):
            li_name = st.text_input("이름", key="li_name")
            li_pw = st.text_input("비밀번호", type="password", key="li_pw")
            remember = st.checkbox("로그인 유지(이 브라우저에서 자동 로그인)", value=True, key="login_remember")
            li_submit = st.form_submit_button("로그인")
        if li_submit:
            name = (li_name or "").strip()
            pw = (li_pw or "").strip()
            if not name or not pw:
                st.error("이름과 비밀번호를 모두 입력하세요.")
                st.stop()
            if not _account_exists(name) or not _verify_login(name, pw):
                st.error("이름 또는 비밀번호가 올바르지 않습니다.")
                st.stop()
            # 세션 세팅
            ss.auth = {"name": name, "remember": remember}
            ss.locked_name = name
            # 자동 로그인 유지(영속 쿠키)
            if remember:
                acc = _load_account_row(name)
                _persist_login(name, acc["pwd_hash"])
            else:
                _clear_login()
            st.rerun()

    # 로그인 전 차단
    st.stop()

# ===== 고정 설정 =====
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQv-m184X3IvYWV0Ntur0gEQhs2DO9ryWJGYiLV30TFV_jB0iSatddQoPAfNFAUybXjoyEHEg4ld5ZY/pub?output=csv"
ADMIN_PASSWORD = "081224"
LEVELS = ["전체", "하", "중", "상", "최상"]
LEVEL_SCORE = {"하": 1, "중": 3, "상": 5, "최상": 7}

# ===== 데이터 경로(안정화) =====
RANKING_FILE = DATA_DIR / "quiz_ranking.csv"
PROGRESS_FILE = DATA_DIR / "quiz_progress.csv"

def ensure_csv(path: Path, cols):
    if not path.exists():
        pd.DataFrame(columns=cols).to_csv(path, index=False, encoding="utf-8-sig")

ensure_csv(RANKING_FILE, ["timestamp","user_name","total","correct","wrong","blank","rate","score"])
ensure_csv(PROGRESS_FILE, ["timestamp","user_name","qid","status","level"])
_ensure_accounts_csv()

# ===== 시트 로드 =====
@st.cache_data(show_spinner=False)
def load_sheet(_cache_buster: int = 0) -> pd.DataFrame:
    df = pd.read_csv(SHEET_CSV_URL, keep_default_na=False)  # NA를 '빈문자'로
    df.columns = [c.strip().lower() for c in df.columns]
    for c in ["level","topic","question","answer","image"]:
        if c not in df.columns: df[c] = ""
        df[c] = df[c].astype(str).str.strip()
    if "id" not in df.columns:
        df["id"] = df.apply(lambda r: hashlib.md5(
            f"{r['level']}|{r['topic']}|{r['question']}|{r['answer']}".encode("utf-8")
        ).hexdigest()[:12], axis=1)
    else:
        df["id"] = df["id"].astype(str).str.strip()
        miss = df["id"] == ""
        if miss.any():
            df.loc[miss, "id"] = df[miss].apply(lambda r: hashlib.md5(
                f"{r['level']}|{r['topic']}|{r['question']}|{r['answer']}".encode("utf-8")
            ).hexdigest()[:12], axis=1)
    return df

# ===== 공통 유틸 =====
def normalize_ans(s: str) -> str:
    if s is None: return ""
    s2 = str(s)
    s2 = s2.replace(" ", "").replace("$", "").replace("**", "").lower().strip()
    return s2

def filter_df(df: pd.DataFrame, level: str, keyword: str) -> pd.DataFrame:
    cond = pd.Series(True, index=df.index)
    if level in ("하","중","상","최상"):
        cond &= (df["level"] == level)
    kw = (keyword or "").strip().lower()
    if kw:
        hay = (df["topic"].fillna("") + " " + df["question"].fillna("") + " " + df["answer"].fillna("")).str.lower()
        for token in kw.split():
            cond &= hay.str_contains(re.escape(token), na=False) if hasattr(hay, "str_contains") else hay.str.contains(re.escape(token), na=False)
    return df[cond].copy()

def calc_weighted_score(df_log: pd.DataFrame) -> int:
    if df_log.empty: return 0
    return int(df_log[df_log["status"]=="correct"]["level"].map(LEVEL_SCORE).fillna(0).sum())

# ===== [교체] 이미지 URL 정제기 (URL 정규식 기반 + Drive 변환) =====
def _resolve_image_items(raw: str):
    """
    시트 'image' 셀 값 → 표시 가능한 이미지 URL 리스트로 정제
    - URL 정규식으로 http/https 링크 '전부 추출'
    - Google Drive 'view/open' → 'uc?export=view&id=' 자동 변환
    - 숫자·잡값·빈값은 자동 무시
    - 세미콜론/쉼표/줄바꿈/공백 섞여도 안전
    """
    if not raw:
        return []
    s = str(raw).strip()

    # =IMAGE("...") → 안의 URL만 뽑기
    m = re.match(r'\s*=IMAGE\(\s*["\']([^"\']+)["\']', s, flags=re.I)
    if m:
        s = m.group(1).strip()

    # URL 전부 추출
    urls = re.findall(r'https?://[^\s\]\)\'"]+', s)

    def _drive_to_uc(u: str) -> str:
        m1 = re.search(r"drive\.google\.com/file/d/([^/]+)/", u)
        if m1:
            return f"https://drive.google.com/uc?export=view&id={m1.group(1)}"
        m2 = re.search(r"drive\.google\.com/.*[?&]id=([^&]+)", u)
        if m2:
            return f"https://drive.google.com/uc?export=view&id={m2.group(1)}"
        return u

    cleaned = []
    for u in urls:
        lu = u.lower()
        if "drive.google.com" in lu:
            u = _drive_to_uc(u)
        cleaned.append(u)
    return cleaned

# (이전 호환용 도우미 — 사용 안 해도 무방)
def load_used_names() -> set[str]:
    used = set()
    try:
        r = pd.read_csv(RANKING_FILE)
        if "user_name" in r.columns:
            used |= set(r["user_name"].astype(str).str.strip())
    except Exception:
        pass
    try:
        p = pd.read_csv(PROGRESS_FILE)
        if "user_name" in p.columns:
            used |= set(p["user_name"].astype(str).str.strip())
    except Exception:
        pass
    used.discard("")
    return used

def get_query_user() -> str:
    try:
        params = st.query_params
        val = params.get("user", "")
        if isinstance(val, list):
            return str(val[0]).strip() if val else ""
        return str(val).strip()
    except Exception:
        return ""

def set_query_user(name: str):
    try:
        st.query_params["user"] = name
    except Exception:
        pass

# ===== 진행/랭킹 파일 =====
def append_progress(user: str, qid: str, status: str, level: str):
    row = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "user_name": user.strip(),
        "qid": str(qid),
        "status": status,
        "level": str(level),
    }
    pd.DataFrame([row]).to_csv(PROGRESS_FILE, mode="a", header=False, index=False, encoding="utf-8-sig")

def recompute_from_progress(user: str, problems_df: pd.DataFrame | None) -> Dict[str, Any]:
    try:
        prog = pd.read_csv(PROGRESS_FILE)
    except Exception:
        prog = pd.DataFrame(columns=["timestamp","user_name","qid","status","level"])
    if prog.empty:
        return {"total":0,"correct":0,"wrong":0,"blank":0,"rate":0.0,"score":0}
    prog["user_name"] = prog["user_name"].astype(str).str.strip()
    mine = prog[prog["user_name"] == user.strip()].copy()
    if mine.empty:
        return {"total":0,"correct":0,"wrong":0,"blank":0,"rate":0.0,"score":0}
    for c in ["status","level"]:
        if c not in mine.columns: mine[c] = ""
        mine[c] = mine[c].astype(str)
    if problems_df is not None and "id" in problems_df.columns:
        id2lvl = dict(zip(problems_df["id"].astype(str), problems_df["level"].astype(str)))
        miss = mine["level"].str.strip().eq("") | mine["level"].isna()
        if miss.any():
            mine.loc[miss,"level"] = mine.loc[miss,"qid"].astype(str).map(id2lvl).fillna("")
    total = len(mine)
    correct = int((mine["status"]=="correct").sum())
    blank = int((mine["status"]=="blank").sum())
    wrong = total - correct - blank
    rate = round((correct/total*100),1) if total else 0.0
    score = int(mine.loc[mine["status"]=="correct","level"].map(LEVEL_SCORE).fillna(0).sum())
    return {"total":total,"correct":correct,"wrong":wrong,"blank":blank,"rate":rate,"score":score}

def replace_ranking(user: str, stats: Dict[str, Any]):
    try:
        rank = pd.read_csv(RANKING_FILE)
    except Exception:
        rank = pd.DataFrame(columns=["timestamp","user_name","total","correct","wrong","blank","rate","score"])
    if "user_name" not in rank.columns:
        rank["user_name"] = []
    rank["user_name"] = rank["user_name"].astype(str).str.strip()
    rank = rank[rank["user_name"] != user.strip()].copy()
    row = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "user_name": user.strip(), **stats}
    rank = pd.concat([rank, pd.DataFrame([row])], ignore_index=True)
    rank.to_csv(RANKING_FILE, index=False, encoding="utf-8-sig")

def load_ranking_sorted() -> pd.DataFrame:
    try:
        df = pd.read_csv(RANKING_FILE)
    except Exception:
        return pd.DataFrame()
    if df.empty: return df
    df = df.sort_values(by=["correct"], ascending=[False], kind="mergesort").reset_index(drop=True)
    df.insert(0, "순위", df.index + 1)
    return df

# ===== 세션 상태 =====
ss = st.session_state
ss.setdefault("df", load_sheet())
ss.setdefault("stage", "home")
ss.setdefault("filters", {"level":"전체","keyword":""})
ss.setdefault("user_name", "")
ss.setdefault("locked_name", "")
ss.setdefault("seen_ids", set())
ss.setdefault("current_row_idx", None)
ss.setdefault("logs", [])
ss.setdefault("result_saved", False)
ss.setdefault("admin_open", False)
ss.setdefault("admin_ok", False)
ss.setdefault("admin_del_target", "")
ss.setdefault("seen_ids_hydrated", False)

# (이전 URL 잠금 복원 — 계정 로그인과 무관, 있어도 무해)
if not ss.locked_name:
    q_user = get_query_user()
    if q_user:
        ss.locked_name = q_user
        ss.user_name = q_user

def enforce_locked_name():
    if ss.locked_name:
        cur = (ss.user_name or "").strip()
        if cur and cur != ss.locked_name:
            st.error(f"이 기기에서는 '{ss.locked_name}' 이름으로만 진행할 수 있습니다.")
            ss.user_name = ss.locked_name

def go_home():
    ss.stage = "home"
    ss.current_row_idx = None
    ss.result_saved = False

# ===== [추가] 진행 기록으로부터 이미 풀었던 문제 복원 =====
def _load_seen_ids_for_user(user: str) -> set[str]:
    if not user:
        return set()
    try:
        df = pd.read_csv(PROGRESS_FILE)
        if df.empty:
            return set()
        df["user_name"] = df["user_name"].astype(str).str.strip()
        df["qid"] = df["qid"].astype(str)
        mine = df[df["user_name"] == user.strip()]
        return set(mine["qid"].tolist())
    except Exception:
        return set()

# --- 문제 지문에서 '인라인 이미지'만 무력화 (예: ! → [이미지])
_IMG_MD_PATTERN = re.compile(r'!\[[^\]]*\]\([^)]+\)')
def _neutralize_inline_images_md(s: str) -> str:
    try:
        return _IMG_MD_PATTERN.sub("[이미지]", str(s))
    except Exception:
        return str(s)

# ===== UI: 공통 헤더 =====
auth_gate()

st.title("수학 퀴즈")
st.caption("고정된 구글 시트에서 문제를 불러와 난이도/키워드 조건으로 랜덤 출제합니다. (푼 문제는 다시 안 나옴)")

# 현재 로그인 사용자 표기 + 로그아웃
enforce_locked_name()
with st.sidebar:
    st.markdown(f"**👤 {ss.locked_name}**")
    if st.button("로그아웃", use_container_width=True, key="btn_logout"):
        _clear_login()
        ss.pop("auth", None)
        ss.pop("locked_name", None)
        ss.user_name = ""
        ss.seen_ids = set()
        ss.seen_ids_hydrated = False
        st.rerun()

st.divider()

# [핵심] 로그인 직후 한 번, 진행 기록에서 seen_ids 복원
if ss.locked_name and not ss.seen_ids_hydrated:
    ss.seen_ids = _load_seen_ids_for_user(ss.locked_name)
    ss.seen_ids_hydrated = True

# ==========================
# HOME
# ==========================
if ss.stage == "home":
    if ss.df is None or ss.df.empty:
        st.error("시트를 불러오지 못했습니다.")
    else:
        c1, c2 = st.columns([1,2])
        with c1:
            level = st.selectbox("난이도", LEVELS, index=LEVELS.index(ss.filters.get("level","전체")))
        with c2:
            keyword = st.text_input("키워드 검색 (공백으로 여러 단어 AND 검색, 예: 수1 삼각함수)", value=ss.filters.get("keyword",""))

        if st.button("문제 풀기", type="primary", use_container_width=True):
            if not ss.locked_name:
                st.error("로그인이 필요합니다.")
            else:
                ss.filters = {"level": level, "keyword": keyword}
                df_filtered = filter_df(ss.df, level, keyword)
                unseen = df_filtered[~df_filtered["id"].astype(str).isin(ss.seen_ids)]
                if unseen.empty:
                    st.info("조건에 맞는 문제가 없습니다. 난이도/키워드를 조정하세요.")
                else:
                    ss.current_row_idx = int(unseen.sample(1).index[0])
                    ss.stage = "quiz"
                    st.rerun()

        st.markdown("### 🏆 랭킹 (맞춘 문제 수 기준)")
        rank_df = load_ranking_sorted()
        if not rank_df.empty:
            show_cols = ["순위","user_name","correct","wrong","blank","rate","score","total","timestamp"]
            rank_view = rank_df[show_cols].rename(columns={
                "user_name":"이름","correct":"정답","wrong":"오답","blank":"미기입",
                "rate":"정답률(%)","score":"점수","total":"총문항","timestamp":"기록시각"
            })
            st.dataframe(rank_view, use_container_width=True, height=340)
        else:
            st.info("등록된 랭킹 기록이 없습니다. 결과 화면에서 랭킹에 저장해 보세요.")

# ==========================
# QUIZ
# ==========================
elif ss.stage == "quiz":
    enforce_locked_name()
    row = ss.df.loc[ss.current_row_idx]
    st.markdown(f"**[{row.get('topic','')}] {row.get('level','')} 난이도**")

    # 문제 지문 내 인라인 이미지(![](...))만 치환해 깨짐 방지
    question_txt = _neutralize_inline_images_md(row.get("question",""))
    st.markdown("> 문제:\n" + question_txt)

    raw_img = str(row.get("image","")).strip()
    urls = _resolve_image_items(raw_img)
    if urls:
        for u in urls:
            st.image(u, use_container_width=True)

    ans_key = f"quiz_answer_{row['id']}"
    st.text_input("정답 입력", key=ans_key)

    b1, b2, b3 = st.columns([1,1,1])

    def commit_current_answer_and_mark_next(finish: bool = False):
        ua_raw = st.session_state.get(ans_key, "")
        ua = normalize_ans(ua_raw)
        gt = normalize_ans(row.get("answer",""))
        status = "correct" if (ua and ua == gt) else ("blank" if ua == "" else "wrong")

        append_progress(ss.locked_name, str(row["id"]), status, str(row["level"]))

        ss.logs.append({
            "qid": str(row["id"]),
            "status": status,
            "level": str(row["level"]),
            "topic": str(row.get("topic",""))
        })

        ss.seen_ids.add(str(row["id"]))
        if finish:
            ss.stage = "result"
            st.rerun()
            return

        df_filtered = filter_df(ss.df, ss.filters.get("level","전체"), ss.filters.get("keyword",""))
        unseen = df_filtered[~df_filtered["id"].astype(str).isin(ss.seen_ids)]
        if unseen.empty:
            ss.stage = "result"
        else:
            ss.current_row_idx = int(unseen.sample(1).index[0])
        st.rerun()

    with b1:
        if st.button("새 문제", use_container_width=True):
            commit_current_answer_and_mark_next(finish=False)
    with b2:
        if st.button("그만하기(결과 보기)", use_container_width=True):
            commit_current_answer_and_mark_next(finish=True)
    with b3:
        if st.button("처음으로", use_container_width=True):
            go_home()
            st.rerun()

# ==========================
# RESULT
# ==========================
elif ss.stage == "result":
    enforce_locked_name()
    st.subheader("결과")

    if not ss.logs:
        st.info("제출된 답안이 없습니다.")
        if st.button("처음으로"):
            go_home(); st.rerun()
    else:
        df_log = pd.DataFrame(ss.logs)
        total = len(df_log)
        correct = int((df_log["status"]=="correct").sum())
        blank = int((df_log["status"]=="blank").sum())
        wrong = total - correct - blank
        rate = (correct/total*100) if total else 0.0
        weighted_score = calc_weighted_score(df_log)

        st.write(f"총 {total}문항 | 정답 {correct}개 | 오답 {wrong}개 | 미기입 {blank}개 | 정답률 {rate:.1f}% | 점수 {weighted_score}")

        show_keys = st.checkbox("정답 값도 함께 보기", value=False)

        base_cols = ["level", "status"]
        if "topic" in df_log.columns:
            base_cols.insert(1, "topic")
        display_cols = base_cols.copy()
        if show_keys and "qid" in df_log.columns:
            display_cols.append("qid")

        display_df = df_log[display_cols].copy()
        display_df["결과"] = display_df["status"].map({"correct":"정답","wrong":"오답","blank":"미기입"})
        display_df = display_df.drop(columns=["status"])
        st.dataframe(display_df, use_container_width=True)

        st.markdown("### 🏆 랭킹")
        save_clicked = st.button("현재 결과를 랭킹에 저장(전체 누적을 대체 저장)", type="primary", use_container_width=True, disabled=ss.result_saved)
        if save_clicked:
            stats = recompute_from_progress(ss.locked_name, ss.df)
            replace_ranking(ss.locked_name, stats)
            ss.result_saved = True
            st.success("랭킹에 저장되었습니다. 홈으로 이동합니다.")
            go_home()
            st.rerun()

        rank_df = load_ranking_sorted()
        if not rank_df.empty:
            show_cols = ["순위","user_name","correct","wrong","blank","rate","score","total","timestamp"]
            rank_view = rank_df[show_cols].rename(columns={
                "user_name":"이름","correct":"정답","wrong":"오답","blank":"미기입",
                "rate":"정답률(%)","score":"점수","total":"총문항","timestamp":"기록시각"
            })
            st.dataframe(rank_view, use_container_width=True, height=360)
        else:
            st.info("등록된 랭킹 기록이 없습니다.")

        if st.button("처음으로", use_container_width=True):
            go_home(); st.rerun()

# ==========================
#   우하단 '관리자' FAB
# ==========================
st.markdown("""
<style>
#admin-fab { position: fixed; right: 16px; bottom: 16px; z-index: 9999; }
#admin-fab .stButton>button {
  padding: 6px 12px; font-size: 12px; border-radius: 999px;
  border: 1px solid rgba(0,0,0,0.15);
}
#admin-panel {
  position: fixed; right: 16px; bottom: 56px; width: 300px; z-index: 10000;
  background: var(--background-color);
  border: 1px solid rgba(0,0,0,0.1); border-radius: 12px;
  padding: 12px; box-shadow: 0 6px 24px rgba(0,0,0,0.15);
}
.admin-title { font-weight: 700; margin-bottom: 8px; }
.admin-help { font-size: 12px; opacity: 0.8; margin-bottom: 8px; }
</style>
""", unsafe_allow_html=True)

with st.container():
    st.markdown('<div id="admin-fab">', unsafe_allow_html=True)
    if st.button("관리자", key="btn_admin_fab", help="비밀번호 입력 후 랭킹 관리/시트 새로고침"):
        st.session_state.admin_open = not st.session_state.admin_open
    st.markdown('</div>', unsafe_allow_html=True)

def _admin_panel_password():
    st.markdown('<div id="admin-panel">', unsafe_allow_html=True)
    st.markdown('<div class="admin-title">🔐 관리자 인증</div>', unsafe_allow_html=True)
    pwd = st.text_input("비밀번호", type="password", key="admin_pwd_input")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("확인", key="admin_pwd_ok"):
            if pwd == ADMIN_PASSWORD:
                st.session_state.admin_ok = True; st.toast("인증되었습니다."); st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
    with c2:
        if st.button("닫기", key="admin_pwd_close"):
            st.session_state.admin_open = False; st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

def _admin_panel_menu():
    st.markdown('<div id="admin-panel">', unsafe_allow_html=True)
    st.markdown('<div class="admin-title">🛠 관리자 패널</div>', unsafe_allow_html=True)
    st.markdown('<div class="admin-help">랭킹 삭제 / 시트 최신 반영 / 캐시 초기화</div>', unsafe_allow_html=True)

    st.text_input("삭제할 사용자 이름", key="admin_del_target", placeholder="예: 홍길동")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("기록 삭제", key="admin_del_exec"):
            target = (st.session_state.get("admin_del_target") or "").strip()
            if target:
                try:
                    df = pd.read_csv(RANKING_FILE)
                    df["user_name"] = df["user_name"].astype(str).str.strip()
                    df = df[df["user_name"] != target.strip()]
                    df.to_csv(RANKING_FILE, index=False, encoding="utf-8-sig")
                except Exception:
                    pass
                try:
                    dfp = pd.read_csv(PROGRESS_FILE)
                    dfp["user_name"] = dfp["user_name"].astype(str).str.strip()
                    dfp = dfp[dfp["user_name"] != target.strip()]
                    dfp.to_csv(PROGRESS_FILE, index=False, encoding="utf-8-sig")
                except Exception:
                    pass
                st.success(f"'{target}'의 랭킹 및 푼 문제 기록을 삭제했습니다.")
            else:
                st.error("사용자 이름을 입력하세요.")
    with c2:
        if st.button("랭킹 새로고침", key="admin_rank_refresh"):
            st.rerun()

    st.markdown("---")

    if st.button("시트 최신 반영(새로고침)", key="admin_sheet_reload"):
        try:
            st.cache_data.clear()
            st.session_state.df = load_sheet(_cache_buster=int(time.time()))
            st.success("✅ 최신 시트를 반영했습니다.")
            st.rerun()
        except Exception as e:
            st.error(f"새로고침 실패: {e}")

    cc1, cc2, cc3 = st.columns(3)
    with cc1:
        if st.button("닫기", key="admin_close"): st.session_state.admin_open=False; st.rerun()
    with cc2:
        if st.button("잠그기", key="admin_lock"): st.session_state.admin_ok=False; st.rerun()
    with cc3:
        if st.button("캐시 전체 초기화", key="admin_clear_cache"):
            try:
                st.cache_data.clear(); st.success("캐시 초기화 완료.")
            except Exception:
                st.error("캐시 초기화 실패")

    st.markdown('</div>', unsafe_allow_html=True)

if st.session_state.admin_open:
    if st.session_state.admin_ok: _admin_panel_menu()
    else: _admin_panel_password()
