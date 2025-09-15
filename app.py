# Streamlit Math Quiz - Google Sheet 기반 v2.3
# 변경 포인트
# - quiz 화면에서 버튼 클릭 시 session_state를 콜백(on_click)으로 변경 -> 같은 run 내 위젯 상태 충돌 방지
# - '새 문제', '처음으로', '빈 후보일 때 처음으로' 모두 콜백화
# - 위젯 key 안정화(홈: home_*, 퀴즈: quiz_*)
# - LaTeX는 $$...$$ 그대로 사용 가능

import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="수학 퀴즈", page_icon="🧮", layout="centered")

# -----------------------------
# 설정 & 유틸
# -----------------------------
REQUIRED_COLUMNS = ["level", "topic", "question", "answer"]  # 최소 열
LEVELS = ["전체", "하", "중", "상", "최상"]

@st.cache_data(show_spinner=False)
def load_sheet_csv(csv_url: str) -> pd.DataFrame:
    """구글 스프레드시트 CSV 링크에서 문제를 로드.
    - 기대 열: level, topic, question, answer (소문자)
    - 불필요 공백 제거, 결측 제거
    """
    if not csv_url or str(csv_url).strip() == "":
        raise ValueError("CSV 링크가 비어 있습니다.")
    df = pd.read_csv(csv_url)
    # 열 이름 소문자 통일
    df.columns = [c.strip().lower() for c in df.columns]
    # 필수 열 체크
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"필수 열 누락: {missing}. 필요 열: {REQUIRED_COLUMNS}")
    # 문자열 정리
    for c in REQUIRED_COLUMNS:
        df[c] = df[c].astype(str).fillna("").map(lambda s: s.strip())
    return df

def normalize_ans(s: str) -> str:
    """간단 채점용: 공백/달러/별 제거 + 소문자."""
    if s is None:
        return ""
    s2 = str(s)
    s2 = s2.replace(" ", "").replace("$", "").replace("**", "").lower()
    return s2

def filter_problems(df: pd.DataFrame, level: str, keyword: str) -> pd.DataFrame:
    cond = pd.Series([True] * len(df))
    if level in ("하", "중", "상", "최상"):
        cond &= (df["level"] == level)
    kw = (keyword or "").strip().lower()
    if kw:
        hay = (df["topic"].fillna("") + " " + df["question"].fillna("") + " " + df["answer"].fillna("")).str.lower()
        cond &= hay.str.contains(re.escape(kw), na=False)
    return df[cond].copy()

def pick_random_index(df: pd.DataFrame) -> int:
    """DataFrame에서 랜덤한 실제 인덱스 값을 반환(행 존재 가정)."""
    return int(df.sample(1).index[0])

# -----------------------------
# 세션 상태 기본값
# -----------------------------
ss = st.session_state
ss.setdefault("sheet_url", "")
ss.setdefault("problems_df", None)
ss.setdefault("stage", "home")            # 'home' | 'quiz'
ss.setdefault("filters", {"level": "전체", "keyword": ""})
ss.setdefault("current_row_idx", None)
ss.setdefault("quiz_answer", "")          # quiz 입력창 key와 동일하게 유지

# -----------------------------
# 콜백들 (세션 변경은 콜백에서!)
# -----------------------------
def go_next():
    """다음 문제 추첨 & 입력창 초기화 (퀴즈 화면에서만 호출)"""
    level = ss.filters.get("level", "전체")
    keyword = ss.filters.get("keyword", "")
    cands = filter_problems(ss.problems_df, level, keyword)
    if not cands.empty:
        ss.current_row_idx = pick_random_index(cands)
    ss.quiz_answer = ""  # 같은 run 충돌 방지: 콜백에서 초기화

def go_home():
    """홈 화면으로 복귀"""
    ss.stage = "home"
    ss.current_row_idx = None
    ss.quiz_answer = ""

# -----------------------------
# 상단 안내
# -----------------------------
st.title("수학 퀴즈")
st.caption("구글 시트에서 문제를 불러와 난이도/키워드 조건으로 랜덤 출제합니다.")

with st.expander("📄 구글 시트 연결 방법", expanded=(ss.problems_df is None)):
    st.markdown(
        """
        **방법 A — '웹에 게시' CSV 링크 사용(간편 추천)**
        1) 구글 스프레드시트 → 파일 → **웹에 게시** → 전체 시트 또는 특정 시트 선택 → 형식 **CSV** → 게시  
        2) 생성된 **CSV 링크**를 아래 입력칸에 붙여넣기

        **방법 B — export 링크 수동 구성**
        - 형식: `https://docs.google.com/spreadsheets/d/<스프레드시트ID>/export?format=csv&gid=<시트GID>`

        **필수 열(소문자 권장)**: `level, topic, question, answer`
        - `level`: 하/중/상/최상
        - `topic`: 단원/주제(예: 미분)
        - `question`: 문제 본문(LaTeX는 $$...$$ 가능)
        - `answer`: 정답(간단 문자열 채점)
        """
    )

# 시트 로드 영역 (양 화면 공통 상단)
st.text_input(
    "구글 시트 CSV 링크",
    key="sheet_url",
    placeholder="https://docs.google.com/spreadsheets/d/.../export?format=csv&gid=0",
)
colL, colR = st.columns([1, 1])
with colL:
    if st.button("불러오기", key="btn_load", use_container_width=True):
        try:
            df_loaded = load_sheet_csv(ss.sheet_url)
            ss.problems_df = df_loaded
            ss.stage = "home"  # 로드 후 홈으로
            ss.current_row_idx = None
            ss.quiz_answer = ""   # 이 시점은 아직 quiz 위젯이 렌더되지 않았으므로 안전
            st.success(f"문제 {len(df_loaded)}문항 로드 완료")
        except Exception as e:
            ss.problems_df = None
            ss.stage = "home"
            ss.current_row_idx = None
            ss.quiz_answer = ""
            st.error(f"로드 실패: {e}")
with colR:
    if st.button("샘플 시트 링크 예시 보기", key="btn_sample", use_container_width=True):
        st.info("자신의 시트를 CSV로 게시한 뒤 해당 링크를 사용하세요.")

st.divider()

# -----------------------------
# 화면: HOME (조건 선택 → 문제 풀기)
# -----------------------------
if ss.stage == "home":
    if ss.problems_df is None:
        st.warning("먼저 '구글 시트 CSV 링크'를 입력하고 **불러오기**를 눌러주세요.")
    else:
        c1, c2 = st.columns([1, 2])
        with c1:
            level = st.selectbox(
                "난이도",
                LEVELS,
                index=LEVELS.index(ss.filters.get("level", "전체")),
                key="home_level",
            )
        with c2:
            keyword = st.text_input(
                "키워드 검색 (예: 미분)",
                value=ss.filters.get("keyword", ""),
                key="home_keyword",
            )

        if st.button("문제 풀기", type="primary", key="btn_start", use_container_width=True):
            # 여기서는 아직 quiz 위젯이 렌더되지 않음 -> 세션 값 직접 변경 안전
            ss.filters = {"level": level, "keyword": keyword}
            candidates = filter_problems(ss.problems_df, level, keyword)
            if candidates.empty:
                st.info("조건에 맞는 문제가 없습니다. 난이도/키워드를 조정하세요.")
            else:
                ss.current_row_idx = pick_random_index(candidates)
                ss.quiz_answer = ""   # 입장 전 초기화
                ss.stage = "quiz"
                st.rerun()

# -----------------------------
# 화면: QUIZ (문제 표시/채점/새 문제/처음으로)
# -----------------------------
elif ss.stage == "quiz":
    level = ss.filters.get("level", "전체")
    keyword = ss.filters.get("keyword", "")

    candidates = filter_problems(ss.problems_df, level, keyword)
    if candidates.empty:
        st.info("조건에 맞는 문제가 없습니다. 난이도/키워드를 조정하세요.")
        # 같은 run 내 위젯 충돌 방지를 위해 콜백 사용
        st.button("처음으로", key="btn_back_empty", use_container_width=True, on_click=go_home)
        st.stop()

    # 현재 인덱스가 후보에 없다면 새로 뽑음
    if (ss.current_row_idx is None) or (ss.current_row_idx not in candidates.index):
        ss.current_row_idx = pick_random_index(candidates)

    row = candidates.loc[ss.current_row_idx]

    st.markdown(f"**[{row.get('topic','')}] {row.get('level','')} 난이도**")
    # 🔧 줄바꿈은 문자열 내부에서 처리
    st.markdown("> 문제:\n" + str(row.get("question", "")))

    # ⚠️ 이 위젯이 렌더된 이후에는 같은 run 내에서 ss['quiz_answer']를 직접 건드리지 말 것!
    st.text_input("정답 입력", key="quiz_answer")

    q1, q2, q3 = st.columns([1, 1, 1])
    with q1:
        if st.button("정답 확인", key="btn_check", use_container_width=True):
            ua = normalize_ans(ss.get("quiz_answer", ""))
            gt = normalize_ans(row.get("answer", ""))
            if ua != "" and ua == gt:
                st.success("정답! 잘했어요 ✨")
            else:
                st.error("오답입니다. 다시 시도해 보세요.")

    with q2:
        # on_click 콜백으로 다음 문제 & 입력 초기화
        st.button(
            "새 문제",
            key="btn_next",
            use_container_width=True,
            on_click=go_next,
        )

    with q3:
        # on_click 콜백으로 홈 복귀 & 입력 초기화
        st.button(
            "처음으로",
            key="btn_back",
            use_container_width=True,
            on_click=go_home,
        )
