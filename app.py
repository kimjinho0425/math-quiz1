# app.py — Streamlit Math Quiz (복습 + 정답확인 강화 + 키워드 숫자버전)
import time, hashlib, re, os
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title="수학 퀴즈", page_icon="🧮", layout="centered")

# ===== 기본 경로 =====
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# ===== 시트 설정 =====
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQv-m184X3IvYWV0Ntur0gEQhs2DO9ryWJGYiLV30TFV_jB0iSatddQoPAfNFAUybXjoyEHEg4ld5ZY/pub?output=csv"
ADMIN_PASSWORD = "081224"
LEVELS = ["전체", "하", "중", "상", "최상"]
LEVEL_SCORE = {"하":1,"중":3,"상":5,"최상":7}
KEYWORDS = ["전체", "공통수학1", "공통수학2", "수1", "수2"]  # ✅ 숫자 버전 키워드

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
    if kw and kw!="전체":
        hay=(df["topic"]+" "+df["question"]+" "+df["answer"]).str.lower()
        cond&=hay.str.contains(kw.lower(),na=False)
    return df[cond].copy()

def calc_weighted_score(df_log):
    if df_log.empty: return 0
    return int(df_log[df_log["status"]=="correct"]["level"].map(LEVEL_SCORE).fillna(0).sum())


# ======================================================================
# === 🔥 수정된 get_image_paths — PNG + JPG + JPEG 자동 인식 버전 ===
# ======================================================================
def get_image_paths(raw:str)->list[str]:
    if not raw:
        return []
    base = DATA_DIR / "images" / "quiz"
    exts = [".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"]  # 허용 확장자
    parts = [p.strip() for p in re.split(r"[;,]+", raw) if p.strip()]
    found = []

    for p in parts:
        p_path = Path(p)
        stem = p_path.stem       # 파일명(확장자 제거)
        parent = p_path.parent   # 혹시 폴더가 포함된 경우 대비

        # 뒤에 붙은 확장자는 무시하고 동일 이름의 png/jpg/jpeg 탐색
        for ext in exts:
            cand = parent / f"{stem}{ext}"
            local = base / cand
            if local.exists():
                found.append(str(local))
                break

    return found
# ======================================================================
# ======================================================================


def _refresh_sheet_globally():
    st.cache_data.clear()
    st.session_state.df = load_sheet(_cache_buster=int(time.time()))

# ===== 세션 초기 =====
ss=st.session_state
ss.setdefault("df",load_sheet())
ss.setdefault("stage","home")
ss.setdefault("filters",{"level":"전체","keyword":"전체"})
ss.setdefault("seen_ids",set())
ss.setdefault("logs",[])
ss.setdefault("result_saved",False)
ss.setdefault("review_mode", False)
ss.setdefault("review_selected", None)
ss.setdefault("pending_feedback", None)

# ===== 메인 =====
st.title("길거리 수학 챌린지")

with st.sidebar:
    st.markdown("메뉴")

    if "admin_unlocked" not in ss:
        ss.admin_unlocked = False

    with st.expander("관리자"):
        if not ss.admin_unlocked:
            pw = st.text_input("관리자 비밀번호", type="password")
            if st.button("관리자 로그인"):
                if pw == ADMIN_PASSWORD:
                    ss.admin_unlocked = True
                    st.success("관리자 모드 활성화")
                    st.rerun()
                else:
                    st.error("비밀번호가 올바르지 않습니다.")
        else:
            st.success("관리자 모드")
            if st.button("관리자 패널로 이동"):
                ss.stage = "admin"; st.rerun()

# ===== 홈 =====
if ss.stage=="home":
    df=ss.df
    level=st.selectbox("난이도",LEVELS,index=LEVELS.index(ss.filters.get("level","전체")))
    keyword=st.selectbox("단원",KEYWORDS,index=KEYWORDS.index(ss.filters.get("keyword","전체")))  # 숫자 버전

    c1, c2 = st.columns(2)
    with c1:
        if st.button("문제 풀기",type="primary"):
            ss.filters={"level":level,"keyword":keyword}
            ss.review_mode = False
            df_f=filter_df(df,level,keyword)
            unseen=df_f[~df_f["id"].isin(ss.seen_ids)]
            if unseen.empty: st.info("조건에 맞는 문제가 없습니다.")
            else:
                ss.current_row_idx=int(unseen.sample(1).index[0])
                ss.stage="quiz"; st.rerun()

    with c2:
        if st.button("복습하기",type="secondary"):
            if not ss.seen_ids:
                st.warning("아직 푼 문제가 없습니다.")
            else:
                ss.review_mode = True
                ss.stage = "review_select"
                st.rerun()

# ===== 복습 문제 선택 =====
elif ss.stage == "review_select":
    st.subheader("📘 복습할 문제 선택")
    df = ss.df[ss.df["id"].isin(ss.seen_ids)]
    if df.empty:
        st.info("푼 문제가 없습니다.")
        if st.button("홈으로"): ss.stage="home"; st.rerun()
    else:
        st.dataframe(df[["id","level","topic","question"]].reset_index(drop=True), use_container_width=True)
        selected_id = st.text_input("풀고 싶은 문제 ID를 입력하세요:")
        if st.button("해당 문제 풀기", type="primary"):
            if selected_id.strip() in df["id"].values:
                ss.review_selected = selected_id.strip()
                ss.stage = "quiz"
                st.rerun()
            else:
                st.warning("해당 ID의 문제가 없습니다.")
        if st.button("홈으로 돌아가기"): ss.stage="home"; st.rerun()

# ===== 퀴즈 =====
elif ss.stage=="quiz":
    if ss.review_mode and ss.review_selected:
        row = ss.df[ss.df["id"] == ss.review_selected].iloc[0]
    else:
        row = ss.df.loc[ss.current_row_idx]

    st.markdown(f"**[{row.get('topic','')}] {row.get('level','')} 난이도**")
    st.markdown("> 문제:\n"+row.get("question",""))
    imgs=get_image_paths(row.get("image",""))
    if imgs:
        for im in imgs: st.image(im,use_container_width=True)

    ans_key=f"ans_{row['id']}"
    st.text_input("정답 입력",key=ans_key)
    b1,b2,b3=st.columns(3)

    def commit(show_feedback=False,nextq=False):
        ua=normalize_ans(st.session_state.get(ans_key,""))
        gt=normalize_ans(row.get("answer",""))
        correct = (ua and ua==gt)

        if not ss.review_mode:
            status="correct" if correct else ("blank" if ua=="" else "wrong")
            ss.logs.append({"qid":row["id"],"status":status,"level":row["level"]})
            ss.seen_ids.add(row["id"])

        if show_feedback:
            ss.pending_feedback = {
                "correct": correct,
                "ua": ua,
                "gt": gt,
                "nextq": nextq,
                "review": ss.review_mode
            }
            ss.stage = "feedback"; st.rerun()
        else:
            ss.stage="result"; st.rerun()

    with b1:
        if st.button("제출 후 다음 문제"): commit(show_feedback=True,nextq=True)
    with b2:
        if st.button("제출 후 종료"): commit(show_feedback=True,nextq=False)
    with b3:
        if st.button("그만풀기"): ss.stage="home"; st.rerun()

# ===== 정답 확인 =====
elif ss.stage=="feedback":
    fb = ss.pending_feedback
    if not fb: ss.stage="home"; st.rerun()

    st.markdown("### 📊 정답 확인")
    if fb["correct"]:
        st.markdown("<h1 style='color:limegreen; font-size:70px; text-align:center;'>✅ 정답!</h1>", unsafe_allow_html=True)
    else:
        st.markdown("<h1 style='color:red; font-size:70px; text-align:center;'>❌ 오답!</h1>", unsafe_allow_html=True)
        if fb["ua"] == "":
            st.markdown("<h2 style='text-align:center;'>아무 답도 입력하지 않았어요.</h2>", unsafe_allow_html=True)
        else:
            st.markdown(f"<h3 style='text-align:center;'>정답은 <b style='color:orange;'>{fb['gt']}</b> 입니다.</h3>", unsafe_allow_html=True)

    st.markdown("---")
    c1, c2, c3 = st.columns(3)

    if fb["review"]:
        if c2.button("🏠 홈으로 돌아가기"): ss.stage="home"; st.rerun()
    else:
        if c1.button("➡️ 다음 문제로 넘어가기"):
            df_f=filter_df(ss.df,ss.filters.get("level","전체"),ss.filters.get("keyword","전체"))
            unseen=df_f[~df_f["id"].isin(ss.seen_ids)]
            if unseen.empty:
                ss.stage="result"
            else:
                ss.current_row_idx=int(unseen.sample(1).index[0])
                ss.stage="quiz"
            ss.pending_feedback=None; st.rerun()
        if c2.button("📘 결과 요약 보기"):
            ss.pending_feedback=None; ss.stage="result"; st.rerun()
        if c3.button("🛑 그만풀기"):
            ss.pending_feedback=None; ss.stage="home"; st.rerun()

# ===== 결과 =====
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
        if st.button("홈으로 돌아가기",type="primary"):
            ss.stage="home"; st.rerun()

# ===== 관리자 =====
elif ss.stage=="admin":
    if not ss.get("admin_unlocked", False):
        st.error("관리자 권한이 필요합니다.")
        if st.button("홈으로"):
            ss.stage = "home"; st.rerun()
        st.stop()

    st.header("🛠️ 관리자 패널")
    st.subheader("시트 전역 새로고침")
    st.caption("배포 후 시트가 수정되었을 때 눌러주세요.")
    if st.button("🔄 시트 새로고침", type="primary"):
        try:
            _refresh_sheet_globally()
            st.success("시트를 새로 불러왔습니다.")
        except Exception as e:
            st.error(f"실패: {e}")

    if st.button("🏠 홈으로 돌아가기"):
        ss.stage="home"; st.rerun()


