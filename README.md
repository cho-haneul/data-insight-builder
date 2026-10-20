# 📊 AI Data Insight Builder (공식 통계 데이터 정밀 진단 & AI 인사이트 빌더)

> **공식기관(World Bank 등) 통계 CSV 자동 진단 ➜ Google Gemini 자연어 질의 & 맞춤 제안 ➜ Pandas 엄밀 계산 ➜ Chart.js 맞춤 시각화 ➜ 초보자 눈높이 AI 멘토링 보고서**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![Flask](https://img.shields.io/badge/Flask-3.x-black?logo=flask)
![Pandas](https://img.shields.io/badge/Pandas-2.x-150458?logo=pandas)
![Gemini](https://img.shields.io/badge/Google%20Gemini-3.5%20Flash%20Lite-8E75C2?logo=googlegemini)
![PWA](https://img.shields.io/badge/PWA-Installable-2563EB?logo=pwa)
![License](https://img.shields.io/badge/License-MIT-green)

---

## 💡 프로젝트 소개

**AI Data Insight Builder**는 공공 데이터나 공식기관(World Bank, 통계청 등)의 복잡한 통계 CSV 파일을 업로드하면, 데이터의 구조와 결측치·집계행 왜곡을 자동으로 진단하고, **자연어 질문을 분석하여 가장 알맞은 통계 차트와 교육용 해설 보고서를 원클릭으로 제공하는 교육용 데이터 분석 웹앱**입니다.

### 🎯 핵심 원칙 (Core Philosophy)
1. **수치 계산은 100% Python/Pandas가 수행**: AI(LLM)에게 절대로 숫자를 직접 계산하거나 추정하도록 지시하지 않습니다 (환각 방지).
2. **AI(Google Gemini)는 맥락 해석과 교육 멘토링 담당**: 계산된 표와 통계 지표를 바탕으로 초보자도 쉽게 이해할 수 있는 일상 비유와 인과관계 주의점을 해설합니다.
3. **가벼움과 접근성**: 외부 무거운 프레임워크 없이 순수 Vanilla JS, CSS3, Chart.js로 초경량 구현되어 모바일/데스크톱 어디서나 빠르고 쾌적하게 동작합니다.

---

## ✨ 주요 기능

### 1. 🔍 CSV 13대 데이터 종합 자동 진단
- **인코딩 자동 감지**: `utf-8-sig`, `utf-8`, `cp949`, `euc-kr` 순차 시도
- **헤더 행 자동 감지**: 공공기관 데이터의 불필요한 메타데이터 상단 줄을 자동으로 건너뜀
- **자동 품질 분석**: 행/열 수, 결측치 비율(80% 이상 경고), 중복행 검사, 대륙/그룹 집계행(World, High Income 등) 감지
- **권장 기준연도 판별**: 결측치가 가장 적고 최신 유효 데이터가 풍부한 연도를 자동 추천

### 2. 💬 자연어 질문(NL Query) & 스마트 도구 매핑
- *"2024년 세계 1~10등까지 순위국가와 대한민국을 함께 비교해줘"*
- 사용자가 일상 언어로 질문하면 질문 의도를 파악하여:
  - 초보자 맞춤 사전 답변 제공
  - 질문에 꼭 맞는 **12대 분석 도구 및 최적 파라미터 자동 구성**
  - 원클릭 **[📊 맞춤 시각화 그래프 보기]** 버튼 생성

### 3. 📈 12대 공식 통계 분석 도구 (Pandas 기반 엄밀 계산)
- **Top / Bottom N 순위 분석** (특정 국가 포함 및 주황색 막대 하이라이트 지원)
- **개체 vs 전체 비교 (One vs All)**: 특정 국가와 글로벌 전체 평균·중앙값·분포 격차 비교
- **연도별 시계열 추이 (Trend Line)**
- **구간별 데이터 분포 (Distribution Histogram)**
- **연도 간 증감률 / 성장률 분석 (Change Rate)**
- **2개 지표 상관관계 산점도 (Correlation Scatter)** 등

### 4. 📝 듀얼 모드 AI 해설 리포트 (모드 A vs 모드 B 비교)
- **모드 A (자연어 직접 해석)**: 계산 도구 없이 AI가 직관적으로 요약한 가벼운 해설
- **모드 B (정식 과학적 보고서)**: 8대 통계 윤리 규칙과 7대 정규 헤딩 형식을 엄격히 준수한 고신뢰 리포트
  - *## 무엇을 봤는가 / ## 데이터 출처와 정의 / ## 기준 시점과 제외된 항목 / ## 계산 결과 / ## 읽어낼 수 있는 것 / ## 이 데이터로는 알 수 없는 것 / ## 다음에 확인해볼 것*

### 5. 🧑‍🏫 초보자를 위한 1:1 후속 질문 Q&A 멘토링
- 시각화 결과 아래에서 *"1위와 차이가 큰 이유는?"*, *"제외된 행은 왜 뺀 거야?"* 등 자유롭게 질문
- 데이터에 없는 사실은 솔직히 한계를 밝히고, 통계 초보자도 바로 이해할 수 있는 친절한 일상 비유 해설 제공

### 6. 🔒 4자리 PIN 잠금 & 📱 PWA 모바일 앱 지원
- **접속 보안**: 첫 진입 시 4자리 숫자 비밀번호(`0110`) 입력 모달을 통한 보안 잠금
- **PWA (Progressive Web App)**: 스마트폰(Chrome, Safari) 및 PC(Chrome, Edge)에서 브라우저 주소창 없이 홈 화면에 단독 앱으로 설치 가능
- **빨강-노랑-파랑 차트 아이콘**: 직관적이고 생동감 넘치는 3색 막대 차트 앱 아이콘 탑재

---

## 🛠️ 기술 스택 (Tech Stack)

| 구분 | 사용 기술 |
|---|---|
| **Backend** | Python 3.10+, Flask, Pandas, NumPy, python-dotenv |
| **AI / LLM** | Google Gemini API (`gemini-3.5-flash-lite`, `gemini-2.5-flash`) |
| **Frontend** | Vanilla JavaScript (ES6+), HTML5, CSS3 (No Framework) |
| **Visualization** | Chart.js 4.x, Marked.js (Markdown Rendering) |
| **Web App / PWA** | Service Worker Cache API, Web App Manifest, Standalone PWA |
| **Deployment** | Vercel Serverless / Any WSGI Host |

---

## 🚀 빠른 시작 가이드 (Local Run)

### 1. 저장소 복제 및 가상환경 설정
```bash
git clone https://github.com/cho-haneul/data-insight-builder.git
cd data-insight-builder

# 가상환경 생성 및 활성화 (Windows)
python -m venv .venv
.venv\Scripts\activate

# 가상환경 생성 및 활성화 (Mac / Linux)
python3 -m venv .venv
source .venv/bin/activate
```

### 2. 패키지 설치
```bash
pip install -r requirements.txt
```

### 3. 환경 변수 설정
`.env.example` 파일을 복사하여 `.env` 파일을 생성하고 본인의 Google Gemini API Key를 입력합니다.
```ini
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.5-flash-lite
PORT=5000
FLASK_DEBUG=false
```

### 4. 서버 실행
```bash
python app.py
```
브라우저에서 `http://127.0.0.1:5000`으로 접속합니다.
- **초기 접속 비밀번호**: `0110`

---

## 📂 프로젝트 구조 (Directory Structure)

```
data-insight-builder/
├── app.py                     # Flask 메인 애플리케이션 & API 엔드포인트
├── tools.py                   # 12대 정밀 Pandas 통계 분석 도구 및 별칭 사전
├── test_pipeline.py           # 파이프라인 무결성 E2E 단위 테스트 스크립트
├── requirements.txt           # 파이썬 의존성 목록
├── .env.example               # 환경 변수 템플릿
├── .gitignore                 # 보안 및 캐시 파일 제외 설정
├── data/                      # 샘플 데이터셋 (World Bank 인터넷 보급률 통계 등)
├── templates/
│   └── index.html             # 메인 SPA 뷰 템플릿 (PIN 모달, PWA 태그 포함)
└── static/
    ├── app.js                 # 프론트엔드 비즈니스 로직 및 이벤트 핸들러
    ├── style.css              # 모던 반응형 순수 CSS 스타일시트
    ├── manifest.json          # PWA 웹앱 매니페스트
    ├── sw.js                  # PWA 서비스 워커 (오프라인 캐싱)
    └── icons/
        ├── icon.svg           # 빨강·노랑·파랑 벡터 차트 아이콘
        ├── icon-192.png       # 192x192 PWA 아이콘
        └── icon-512.png       # 512x512 PWA 아이콘
```

---

## 🛡️ 복원력 및 오류 방어 설계 (Fault Tolerance)

- **Gemini API 500 INTERNAL 회복탄력성 (`call_gemini_resilient`)**: Google 서버의 일시적 오류 발생 시 지수 백오프로 재시도하고, 예비 모델로 자동 전환합니다.
- **자체 로컬 규칙 엔진 Fallback (`smart_rule_based_query_fallback`)**: 외부 AI API가 완전히 마비되더라도 키워드 기반 로컬 엔진이 질문을 분석하여 멈춤 없이 차트 버튼을 생성합니다.
- **국가명 별칭 사전 자동 매칭**: '한국', '대한민국', '미국', '중국' 등 한글/영문 비정형 입력을 데이터셋의 정식 명칭(`Korea, Rep.`, `United States` 등)으로 자동 치환합니다.
- **연도 자동 보정**: 결측치가 100%이거나 데이터가 없는 연도를 요청하더라도 가장 유효 데이터가 풍부한 최적 연도로 자동 보정합니다.

---

## 📄 라이선스 (License)

This project is licensed under the MIT License - see the LICENSE file for details.
