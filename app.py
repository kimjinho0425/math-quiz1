# app.py — Streamlit Math Quiz (계정 로그인 + 재출제 방지 + 로컬 이미지 표시 + 관리자 패널)
import time, hashlib, re, os
from pathlib import Path
from typing import Dict, Any
import pandas as pd
import streamlit as st

st.set_page_config(page_title="수학 퀴즈", page_icon="🧮", layout="centered")

# ===== 계정 & 로그인 유지 =====
SECRET_SALT = "KEEP_THIS_CONSTANT_AND_PRIVATE"

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
ACCOUNTS_FILE = DATA_DIR / "accounts.csv"

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

# --- 쿠키 레이어 ---
def _has_exp_cookies() -> bool:
    return all(hasattr(st, a) for a in ["experimental_set_cookie","experimental_get_cookie","experimental_delete_cookie"])

def _cget(k: str, default=""):
    if _has_exp_cookies():
        v = st.experimental_get_cookie(k)
        return v if v is not None else default
    if hasattr(st, "cookies") and k in st.cookies:
        return st.cookies.get(k, default)
    return default

def _cset(k: str, v: str):
    if _has_exp_cookies():
        st.experimental_set_cookie(k, v, max_age=60*60*24*365*20, secure=True, samesite="Lax")
        return
    if hasattr(st, "cookies"):
        st.cookies[k] = v

def _cdel(k: str):
    if _has_exp_cookies():
        st.experimental_delete_cookie(k, samesite="Lax"); return
    if hasattr(st, "cookies"):
        try: del st.cookies[k]
        except Exception: st.cookies[k] = ""

def _persist_login(name,pwd_hash): _cset("acc_name", name); _cset("acc_sig", _make_sig(name,pwd_hash))
def _clear_login(): _cdel("acc_name"); _cdel("acc_sig")

def _load_account_row(name):
    try:
        df = pd.read_csv(ACCOUNTS_FILE)
        row = df[df["name"].astype(str).str.strip()==name.strip()]
        if row.empty: return None
        r = row.iloc[0]
        return {"name":r["name"],"pwd_hash":str(r["pwd_hash"]),"salt":str(r["salt"])}
    except: return None

def _account_exists(name):
    try:
        df=pd.read_csv(ACCOUNTS_FILE)
        return name.strip() in df["name"].astype(str).str.strip().values
    except: return False

def _create_account(name,pw):
    if not name or not pw or _account_exists(name): return False
    salt=os.urandom(8).hex()
    pwd_hash=_hash_pw(pw,salt)
    row={"name":name.strip(),"pwd_hash":pwd_hash,"salt":salt,"created_at":time.strftime("%Y-%m-%d %H:%M:%S")}
    header_needed=(not ACCOUNTS_FILE.exists()) or pd.read_csv(ACCOUNTS_FILE).empty
    pd.DataFrame([row]).to_csv(ACCOUNTS_FILE,mode="a",header=header_needed,index=False,encoding="utf-8-sig")
    return True

def _verify_login(name,pw):
    acc=_load_account_row(name)
    return bool(acc) and _hash_pw(pw,acc["salt"])==acc["pwd_hash"]

def _auto_login_from_cookie():
    name=_cget("acc_name"); sig=_cget("acc_sig")
    if not name or not sig: return False
    acc=_load_account_row(name)
    if not acc: return False
    if sig==_make_sig(name,acc["pwd_hash"]):
        st.session_state.auth={"name":name,"remember":True}
        st.session_state.locked_name=name
        return True
    return False

def auth_gate():
    _ensure_accounts_csv(); ss=st.session_state
    if ss.get("auth") and ss.auth.get("name"): return True
    if _auto_login_from_cookie(): return True

    st.markdown("## 🔐 로그인 / 회원가입")
    c1,c2=st.columns(2)
    with c1:
        st.markdown("#### 회원가입")
        with st.form("signup_form"):
            n=st.text_input("이름(중복 불가)",key="su_n")
            p=st.text_input("비밀번호",type="password",key="su_p")
            s=st.form_submit_button("회원가입")
        if s:
            if not n.strip() or not p.strip(): st.error("입력 누락"); st.stop()
            if _account_exists(n): st.error("이미 존재함"); st.stop()
            _create_account(n,p); st.success("가입 완료")
    with c2:
        st.markdown("#### 로그인")
        with st.form("login_form"):
            n=st.text_input("이름",key="li_n")
            p=st.text_input("비밀번호",type="password",key="li_p")
            r=st.checkbox("로그인 유지",value=True)
            s=st.form_submit_button("로그인")
        if s:
            if not n.strip() or not p.strip(): st.error("입력 누락"); st.stop()
            if not _account_exists(n) or not _verify_login(n,p): st.error("오류"); st.stop()
            ss.auth={"name":n,"remember":r}; ss.locked_name=n
            if r: acc=_load_account_row(n); _persist_login(n,acc["pwd_hash"])
            else: _clear_login()
            st.rerun()
    st.stop()

# ===== 시트 설정 =====
SHEET_CSV_URL="https://docs.google.com/spreadsheets/d/e/2PACX-1vQv-m184X3IvYWV0Ntur0gEQhs2DO9ryWJGYiLV30TFV_jB0iSatddQoPAfNFAUybXjoyEHEg4ld5ZY/pub?output=csv"
ADMIN_PASSWORD="081224"
LEVELS=["전체","하","중","상","최상"]
LEVEL_SCORE={"하":1,"중":3,"상":5,"최상":7}

# ===== 경로 =====
RANKING_FILE=DATA_DIR/"quiz_ranking.csv"
PROGRESS_FILE=DATA_DIR/"quiz_progress.csv"
for p,c in [(RANKING_FILE,["timestamp","user_name","total","correct","wrong","blank","rate","score"]),
            (PROGRESS_FILE,["timestamp","user_name","qid","status","level"])]:
    if not p.exists(): pd.DataFrame(columns=c).to_csv(p,index=False,encoding="utf-8-sig")

# ===== 시트 로드 =====
@st.cache_data(show_spinner=False)
def load_sheet(_cache_buster:int=0)->pd.DataFrame:
    df=pd.read_csv(SHEET_CSV_URL,keep_default_na=False)
    df.columns=[c.strip().lower() for c in df.columns]
    for c in ["level","topic","question","answer","image"]:
        if c not in df.columns: df[c]=""
        df[c]=df[c].astype(str).str.strip()
    if "id" not in df.columns or (df["id"].astype(str).str.strip()=="").any():
        df["id"]=df.apply(lambda r:hashlib.md5(
            f"{r['level']}|{r['topic']}|{r['question']}|{r['answer']}".encode("utf-8")
        ).hexdigest()[:12],axis=1)
    return df

def normalize_ans(s:str)->str:
    if s is None: return ""
    return str(s).replace(" ","").replace("$","").replace("**","").lower().strip()

def filter_df(df,level,kw):
    cond=pd.Series(True,index=df.index)
    if level in ("하","중","상","최상"): cond&=(df["level"]==level)
    kw=(kw or "").strip().lower()
    if kw:
        hay=(df["topic"]+" "+df["question"]+" "+df["answer"]).str.lower()
        for t in kw.split(): cond&=hay.str.contains(re.escape(t),na=False)
    return df[cond].copy()

def calc_weighted_score(df_log):
    if df_log.empty: return 0
    return int(df_log[df_log["status"]=="correct"]["level"].map(LEVEL_SCORE).fillna(0).sum())

# ===== 로컬 이미지 로드 (기존 구글드라이브 방식 대체) =====
def get_image_paths(raw:str)->list[str]:
    """
    시트 'image' 셀에 파일명만 적으면 data/images/quiz 폴더에서 불러옴.
    여러개일 땐 ';'로 구분. 예: sin1.png; sin2.png
    """
    if not raw: return []
    base=DATA_DIR/"images"/"quiz"
    parts=[p.strip() for p in re.split(r"[;,]+",raw) if p.strip()]
    found=[]
    for p in parts:
        local=base/p
        if local.exists():
            found.append(str(local))
    return found

# ===== 진행/랭킹 관리 =====
def append_progress(user,qid,status,level):
    row={"timestamp":time.strftime("%Y-%m-%d %H:%M:%S"),"user_name":user.strip(),"qid":qid,"status":status,"level":level}
    pd.DataFrame([row]).to_csv(PROGRESS_FILE,mode="a",header=False,index=False,encoding="utf-8-sig")

def recompute_from_progress(user,dfp):
    try: prog=pd.read_csv(PROGRESS_FILE)
    except: return {"total":0,"correct":0,"wrong":0,"blank":0,"rate":0.0,"score":0}
    if prog.empty: return {"total":0,"correct":0,"wrong":0,"blank":0,"rate":0.0,"score":0}
    mine=prog[prog["user_name"].astype(str).str.strip()==user.strip()].copy()
    if mine.empty: return {"total":0,"correct":0,"wrong":0,"blank":0,"rate":0.0,"score":0}
    total=len(mine)
    correct=int((mine["status"]=="correct").sum())
    blank=int((mine["status"]=="blank").sum())
    wrong=total-correct-blank
    rate=round((correct/total*100),1) if total else 0.0
    score=int(mine.loc[mine["status"]=="correct","level"].map(LEVEL_SCORE).fillna(0).sum())
    return {"total":total,"correct":correct,"wrong":wrong,"blank":blank,"rate":rate,"score":score}

def replace_ranking(user,stats):
    try: r=pd.read_csv(RANKING_FILE)
    except: r=pd.DataFrame(columns=["timestamp","user_name","total","correct","wrong","blank","rate","score"])
    r=r[r["user_name"].astype(str).str.strip()!=user.strip()]
    row={"timestamp":time.strftime("%Y-%m-%d %H:%M:%S"),"user_name":user.strip(),**stats}
    r=pd.concat([r,pd.DataFrame([row])],ignore_index=True)
    r.to_csv(RANKING_FILE,index=False,encoding="utf-8-sig")

def load_ranking_sorted():
    try: df=pd.read_csv(RANKING_FILE)
    except: return pd.DataFrame()
    if df.empty: return df
    df=df.sort_values(by=["correct"],ascending=False).reset_index(drop=True)
    df.insert(0,"순위",df.index+1)
    return df

# ===== 관리자 전용 헬퍼 (최소 기능) =====
def _ensure_admin_flag_column():
    try:
        df = pd.read_csv(ACCOUNTS_FILE)
    except Exception:
        return
    if "is_admin" not in df.columns:
        df["is_admin"] = False
        df.to_csv(ACCOUNTS_FILE, index=False, encoding="utf-8-sig")

def _delete_account_by_name(username: str) -> bool:
    """관리자가 계정 삭제"""
    try:
        df = pd.read_csv(ACCOUNTS_FILE)
    except Exception:
        return False
    if "name" not in df.columns:
        return False
    before = len(df)
    df = df[df["name"].astype(str).str.strip() != str(username).strip()]
    if len(df) == before:
        return False
    df.to_csv(ACCOUNTS_FILE, index=False, encoding="utf-8-sig")
    return True

def _delete_ranking_all() -> None:
    pd.DataFrame(columns=["timestamp","user_name","total","correct","wrong","blank","rate","score"])\
      .to_csv(RANKING_FILE, index=False, encoding="utf-8-sig")

def _delete_ranking_by_user(username: str) -> bool:
    try:
        rk = pd.read_csv(RANKING_FILE)
    except Exception:
        return False
    if rk.empty:
        return False
    before = len(rk)
    rk = rk[rk["user_name"].astype(str).str.strip() != str(username).strip()]
    if len(rk) == before:
        return False
    rk.to_csv(RANKING_FILE, index=False, encoding="utf-8-sig")
    return True

def _refresh_sheet_globally():
    """관리자 전용: 전 프로세스 캐시 무효화 + 즉시 재적재(모든 사용자에게 새 시트 적용)"""
    st.cache_data.clear()
    st.session_state.df = load_sheet(_cache_buster=int(time.time()))

# ===== 세션 초기 =====
ss=st.session_state
ss.setdefault("df",load_sheet())
ss.setdefault("stage","home")
ss.setdefault("filters",{"level":"전체","keyword":""})
ss.setdefault("locked_name","")
ss.setdefault("seen_ids",set())
ss.setdefault("logs",[])
ss.setdefault("result_saved",False)
auth_gate()

st.title("수학 퀴즈")
st.caption("📘 시트 문제를 불러오고, 로컬 이미지(data/images/quiz)에서 파일명을 매칭해 표시합니다.")

with st.sidebar:
    st.markdown(f"**👤 {ss.locked_name}**")
    if st.button("로그아웃"):
        _clear_login(); ss.clear(); st.rerun()

    st.markdown("---")
    # 관리자 진입 (일반 사용자에겐 새로고침 버튼 없음)
    if "admin_unlocked" not in ss:
        ss.admin_unlocked = False

    with st.expander("🔐 관리자"):
        if not ss.admin_unlocked:
            pw = st.text_input("관리자 비밀번호", type="password")
            if st.button("관리자 로그인"):
                if pw == ADMIN_PASSWORD:
                    ss.admin_unlocked = True
                    _ensure_admin_flag_column()
                    st.success("관리자 모드 활성화")
                    st.rerun()
                else:
                    st.error("비밀번호가 올바르지 않습니다.")
        else:
            st.success("관리자 모드 ON")
            if st.button("관리자 패널로 이동"):
                ss.stage = "admin"; st.rerun()

if ss.stage=="home":
    df=ss.df
    level=st.selectbox("난이도",LEVELS,index=LEVELS.index(ss.filters.get("level","전체")))
    keyword=st.text_input("키워드",value=ss.filters.get("keyword",""))
    if st.button("문제 풀기",type="primary"):
        ss.filters={"level":level,"keyword":keyword}
        df_f=filter_df(df,level,keyword)
        unseen=df_f[~df_f["id"].isin(ss.seen_ids)]
        if unseen.empty: st.info("조건에 맞는 문제가 없습니다.")
        else:
            ss.current_row_idx=int(unseen.sample(1).index[0])
            ss.stage="quiz"; st.rerun()
    st.markdown("### 🏆 랭킹")
    rd=load_ranking_sorted()
    if not rd.empty: st.dataframe(rd,use_container_width=True)
    else: st.info("랭킹 기록이 없습니다.")

elif ss.stage=="quiz":
    row=ss.df.loc[ss.current_row_idx]
    st.markdown(f"**[{row.get('topic','')}] {row.get('level','')} 난이도**")
    st.markdown("> 문제:\n"+row.get("question",""))
    # ✅ 로컬 이미지 표시
    imgs=get_image_paths(row.get("image",""))
    if imgs:
        for im in imgs: st.image(im,use_container_width=True)

    ans_key=f"ans_{row['id']}"
    st.text_input("정답 입력",key=ans_key)
    b1,b2,b3=st.columns(3)
    def commit(nextq=False):
        ua=normalize_ans(st.session_state.get(ans_key,""))
        gt=normalize_ans(row.get("answer",""))
        status="correct" if ua and ua==gt else ("blank" if ua=="" else "wrong")
        append_progress(ss.locked_name,row["id"],status,row["level"])
        ss.logs.append({"qid":row["id"],"status":status,"level":row["level"]})
        ss.seen_ids.add(row["id"])
        if not nextq:
            ss.stage="result"; st.rerun()
        else:
            df_f=filter_df(ss.df,ss.filters.get("level","전체"),ss.filters.get("keyword",""))
            unseen=df_f[~df_f["id"].isin(ss.seen_ids)]
            ss.stage="result" if unseen.empty else "quiz"
            if not unseen.empty: ss.current_row_idx=int(unseen.sample(1).index[0])
            st.rerun()
    with b1:
        if st.button("제출 후 다음 문제"): commit(True)
    with b2:
        if st.button("제출 후 그만하기"): commit(False)
    with b3:
        if st.button("그만풀기"): ss.stage="home"; st.rerun()

elif ss.stage=="result":
    st.subheader("결과 요약")
    if not ss.logs: st.info("제출 없음.")
    else:
        df_log=pd.DataFrame(ss.logs)
        total=len(df_log); correct=(df_log["status"]=="correct").sum()
        blank=(df_log["status"]=="blank").sum(); wrong=total-correct-blank
        rate=(correct/total*100) if total else 0
        sc=calc_weighted_score(df_log)
        st.write(f"총 {total}문항 | 정답 {correct} | 오답 {wrong} | 미기입 {blank} | 정답률 {rate:.1f}% | 점수 {sc}")
        if st.button("랭킹에 저장",type="primary",disabled=ss.result_saved):
            stats=recompute_from_progress(ss.locked_name,ss.df)
            replace_ranking(ss.locked_name,stats); ss.result_saved=True; st.success("저장됨"); ss.stage="home"; st.rerun()

elif ss.stage == "admin":
    if not ss.get("admin_unlocked", False):
        st.error("관리자 권한이 필요합니다.")
        if st.button("홈으로"):
            ss.stage = "home"; st.rerun()
        st.stop()

    st.header("🛠️ 관리자 패널 (최소 기능)")
    tab1, tab2 = st.tabs(["🧹 시트 새로고침(전역)", "🗂️ 데이터 삭제"])

    # --- 탭1: 시트 전역 새로고침 ---
    with tab1:
        st.subheader("시트 전역 새로고침")
        st.caption("배포 후 시트가 수정되었을 때, 여기서 한 번 누르면 모든 사용자가 새 문제를 즉시 보게 됩니다.")
        if st.button("🔄 전역 새로고침 실행", type="primary", use_container_width=True):
            try:
                _refresh_sheet_globally()
                st.success("성공: 캐시를 비우고 최신 시트를 다시 불러왔습니다. (전 사용자에게 적용)")
            except Exception as e:
                st.error(f"실패: {e}")

    # --- 탭2: 데이터 삭제(랭킹, 계정) ---
    with tab2:
        st.subheader("랭킹 기록 삭제")
        c1, c2 = st.columns([2,1])
        target_user_rk = c1.text_input("랭킹 삭제할 사용자 이름")
        if c2.button("해당 사용자 랭킹 삭제"):
            ok = _delete_ranking_by_user(target_user_rk.strip())
            st.success("삭제 완료") if ok else st.warning("대상 랭킹이 없거나 실패")

        st.markdown("— 또는 —")
        danger_r = st.checkbox("⚠️ 랭킹 전체 삭제에 동의")
        if st.button("랭킹 전체 삭제", type="secondary", disabled=not danger_r):
            _delete_ranking_all()
            st.success("랭킹 전체 초기화 완료")

        st.divider()
        st.subheader("회원가입(계정) 삭제")
        st.caption("주의: 로그인 정보만 삭제합니다. 사용자 풀이기록/랭킹은 별도 삭제해야 합니다.")
        c3, c4 = st.columns([2,1])
        target_user_acc = c3.text_input("삭제할 계정 이름")
        if c4.button("계정 삭제"):
            ok = _delete_account_by_name(target_user_acc.strip())
            st.success("계정 삭제 완료") if ok else st.warning("해당 계정이 없거나 실패")

    st.markdown("---")
    if st.button("🏠 홈으로"):
        ss.stage = "home"; st.rerun()

