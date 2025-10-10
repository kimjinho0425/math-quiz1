import time, hashlib, re, os
from pathlib import Path
from typing import Dict, Any
import pandas as pd
import streamlit as st

st.set_page_config(page_title="수학 퀴즈", page_icon="🧮", layout="centered")

# ===== 고정 설정 =====
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQv-m184X3IvYWV0Ntur0gEQhs2DO9ryWJGYiLV30TFV_jB0iSatddQoPAfNFAUybXjoyEHEg4ld5ZY/pub?output=csv"
ADMIN_PASSWORD = "081224"
LEVELS = ["전체", "하", "중", "상", "최상"]
LEVEL_SCORE = {"하": 1, "중": 3, "상": 5, "최상": 7}

# ===== 데이터 경로(안정화) =====
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
RANKING_FILE = DATA_DIR / "quiz_ranking.csv"
PROGRESS_FILE = DATA_DIR / "quiz_progress.csv"

def ensure_csv(path: Path, cols):
    if not path.exists():
        pd.DataFrame(columns=cols).to_csv(path, index=False, encoding="utf-8-sig")

ensure_csv(RANKING_FILE, ["timestamp","user_name","total","correct","wrong","blank","rate","score"])
ensure_csv(PROGRESS_FILE, ["timestamp","user_name","qid","status","level"])

# ===== 시트 로드 =====
@st.cache_data(show_spinner=False)
def load_sheet(_cache_buster: int = 0) -> pd.DataFrame:
    df = pd.read_csv(SHEET_CSV_URL)
    df.columns = [c.strip().lower() for c in df.columns]
    # image 열까지 표준화 (⚠ NaN → "" → str 순서)
    for c in ["level","topic","question","answer","image"]:
        if c not in df.columns:
            df[c] = ""
        df[c] = df[c].fillna("").astype(str).str.strip()
    # 문제 고유 id 생성/보정
    if "id" not in df.columns:
        df["id"] = df.apply(lambda r: hashlib.md5(
            f"{r['level']}|{r['topic']}|{r['question']}|{r['answer']}".encode("utf-8")
        ).hexdigest()[:12], axis=1)
    else:
        df["id"] = df["id"].fillna("").astype(str).str.strip()
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
        cond &= hay.str.contains(re.escape(kw), na=False)
    return df[cond].copy()

def calc_weighted_score(df_log: pd.DataFrame) -> int:
    if df_log.empty: return 0
    return int(df_log[df_log["status"]=="correct"]["level"].map(LEVEL_SCORE).fillna(0).sum())

def _resolve_image_items(raw: str):
    """image 셀(세미콜론/줄바꿈/쉼표 구분) → 유효 URL 리스트 (nan/none/- 제거)"""
    if not raw:
        return []
    parts = re.split(r"[;\n,]+", str(raw).strip())
    cleaned = []
    for p in parts:
        u = p.strip()
        if not u:
            continue
        lu = u.lower()
        if lu in {"nan", "none", "-"}:
            continue
        if lu.startswith("http://") or lu.startswith("https://"):
            cleaned.append(u)
    return cleaned

# ===== 진행파일/랭킹파일 로직 =====
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
    # 부족한 level 보완
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

def enforce_locked_name():
    if ss.locked_name:
        cur = (ss.user_name or "").strip()
        if cur and cur != ss.locked_name:
            st.error(f"이 기기에서는 '{ss.locked_name}' 이름으로만 진행할 수 있습니다.")
            ss.user_name = ss.locked_name

def lock_name_now():
    if ss.user_name and not ss.locked_name:
        ss.locked_name = ss.user_name.strip()

def go_home():
    ss.stage = "home"
    ss.current_row_idx = None
    ss.result_saved = False

# ===== UI: 공통 헤더 =====
st.title("수학 퀴즈")
st.caption("고정된 구글 시트에서 문제를 불러와 난이도/키워드 조건으로 랜덤 출제합니다. (푼 문제는 다시 안 나옴)")

# ===== 이름 입력(잠금 유지) =====
enforce_locked_name()
st.text_input("이름을 입력하세요 (예: 홍길동)", key="user_name", disabled=bool(ss.locked_name))
lock_name_now()

st.divider()

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
            keyword = st.text_input("키워드 검색 (예: 미분)", value=ss.filters.get("keyword",""))

        if st.button("문제 풀기", type="primary", use_container_width=True):
            if not ss.locked_name:
                st.error("이름을 먼저 입력하세요.")
            else:
                ss.filters = {"level": level, "keyword": keyword}
                df_filtered = filter_df(ss.df, level, keyword)
                unseen = df_filtered[~df_filtered["id"].isin(ss.seen_ids)]
                if unseen.empty:
                    st.info("조건에 맞는 문제가 없습니다. 난이도/키워드를 조정하세요.")
                else:
                    ss.current_row_idx = int(unseen.sample(1).index[0])
                    ss.stage = "quiz"
                    st.rerun()

        # 랭킹 표
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
# QUIZ (기존 UI 유지)
# ==========================
elif ss.stage == "quiz":
    enforce_locked_name()
    row = ss.df.loc[ss.current_row_idx]
    st.markdown(f"**[{row.get('topic','')}] {row.get('level','')} 난이도**")
    st.markdown("> 문제:\n" + str(row.get("question","")))

    # ✅ image 열(URL/여러 장) 자동 표시 (유효 URL만)
    raw_img = str(row.get("image","")).strip()
    urls = _resolve_image_items(raw_img)
    if urls:
        st.image(urls, use_container_width=True)

    # ★ 문제별 고유 key
    ans_key = f"quiz_answer_{row['id']}"
    st.text_input("정답 입력", key=ans_key)

    b1, b2, b3 = st.columns([1,1,1])

    def commit_current_answer_and_mark_next(finish: bool = False):
        ua_raw = st.session_state.get(ans_key, "")
        ua = normalize_ans(ua_raw)
        gt = normalize_ans(row.get("answer",""))
        status = "correct" if (ua and ua == gt) else ("blank" if ua == "" else "wrong")

        # 영구 진행 로그 저장(csv)
        append_progress(ss.locked_name, str(row["id"]), status, str(row["level"]))

        # 세션 로그에도 기록 (topic 포함)
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

        # 다음 문제 선택
        df_filtered = filter_df(ss.df, ss.filters.get("level","전체"), ss.filters.get("keyword",""))
        unseen = df_filtered[~df_filtered["id"].isin(ss.seen_ids)]
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
# RESULT (기존 UI 유지)
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

        # ✅ topic/qid 존재 여부 안전 처리
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
#   우하단 '관리자' FAB (기존 느낌 유지)
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
        ss.admin_open = not ss.admin_open
    st.markdown('</div>', unsafe_allow_html=True)

def _admin_panel_password():
    st.markdown('<div id="admin-panel">', unsafe_allow_html=True)
    st.markdown('<div class="admin-title">🔐 관리자 인증</div>', unsafe_allow_html=True)
    pwd = st.text_input("비밀번호", type="password", key="admin_pwd_input")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("확인", key="admin_pwd_ok"):
            if pwd == ADMIN_PASSWORD:
                ss.admin_ok = True; st.toast("인증되었습니다."); st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
    with c2:
        if st.button("닫기", key="admin_pwd_close"):
            ss.admin_open = False; st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

def _admin_panel_menu():
    st.markdown('<div id="admin-panel">', unsafe_allow_html=True)
    st.markdown('<div class="admin-title">🛠 관리자 패널</div>', unsafe_allow_html=True)
    st.markdown('<div class="admin-help">랭킹 삭제 / 시트 최신 반영 / 캐시 초기화</div>', unsafe_allow_html=True)

    # 랭킹 삭제
    st.text_input("삭제할 사용자 이름", key="admin_del_target", placeholder="예: 홍길동")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("기록 삭제", key="admin_del_exec"):
            target = (ss.get("admin_del_target") or "").strip()
            if target:
                # 랭킹에서 제거
                try:
                    df = pd.read_csv(RANKING_FILE)
                    df["user_name"] = df["user_name"].astype(str).str.strip()
                    df = df[df["user_name"] != target.strip()]
                    df.to_csv(RANKING_FILE, index=False, encoding="utf-8-sig")
                except Exception:
                    pass
                # 진행기록도 제거
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

    # 시트 최신 반영 (전역 캐시 초기화)
    if st.button("시트 최신 반영(새로고침)", key="admin_sheet_reload"):
        try:
            st.cache_data.clear()
            ss.df = load_sheet(_cache_buster=int(time.time()))
            st.success("✅ 최신 시트를 반영했습니다.")
            st.rerun()
        except Exception as e:
            st.error(f"새로고침 실패: {e}")

    cc1, cc2, cc3 = st.columns(3)
    with cc1:
        if st.button("닫기", key="admin_close"): ss.admin_open=False; st.rerun()
    with cc2:
        if st.button("잠그기", key="admin_lock"): ss.admin_ok=False; st.rerun()
    with cc3:
        if st.button("캐시 전체 초기화", key="admin_clear_cache"):
            try:
                st.cache_data.clear(); st.success("캐시 초기화 완료.")
            except Exception:
                st.error("캐시 초기화 실패")

    st.markdown('</div>', unsafe_allow_html=True)

if ss.admin_open:
    if ss.admin_ok: _admin_panel_menu()
    else: _admin_panel_password()

