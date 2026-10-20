import os
import io
import csv
import re
import json
import time
import logging
import traceback
import pandas as pd
import numpy as np
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv
from google import genai
from google.genai import types

from tools import TOOL_CATALOG, find_matching_entity

# .env 환경변수 로드
load_dotenv(override=True)

# 로깅 설정 (print 사용 금지 규칙 준수)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("DataInsightBuilder")

app = Flask(__name__)

# 업로드 용량 제한 설정 (기본 10MB)
max_mb = int(os.getenv("MAX_UPLOAD_MB", 10))
app.config["MAX_CONTENT_LENGTH"] = max_mb * 1024 * 1024

# 메모리에 보관할 1개 데이터셋 (디스크 영구 저장 금지 규칙)
CURRENT_DATASET = None


def call_gemini_resilient(client, primary_model, contents, config, max_retries=2):
    """
    Gemini API 일시적 500 INTERNAL 또는 타임아웃 오류 시:
    1. 지수 백오프(exponential backoff)로 재시도
    2. 계속 실패 시 fallback 모델(gemini-2.5-flash <-> gemini-3.5-flash-lite)로 자동 전환하여 시도
    """
    models_to_try = [primary_model]
    alt_model = "gemini-2.5-flash" if "lite" in primary_model.lower() else "gemini-3.5-flash-lite"
    if alt_model not in models_to_try:
        models_to_try.append(alt_model)

    last_error = None
    for model_name in models_to_try:
        for attempt in range(max_retries + 1):
            try:
                logger.info(f"[AI] Gemini 호출 시도 (model={model_name}, attempt={attempt+1}/{max_retries+1})")
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
                if response and (response.text or "").strip():
                    return response, model_name
                last_error = Exception("Gemini API 빈 응답 수신")
            except Exception as e:
                last_error = e
                err_str = str(e)
                logger.warning(f"[AI] Gemini 호출 오류 (model={model_name}, attempt={attempt+1}): {err_str[:120]}")
                if "500" in err_str or "INTERNAL" in err_str or "ResourceExhausted" in err_str:
                    time.sleep(1.0 * (attempt + 1))
                else:
                    # 500 계열이 아니면 다음 모델로 빠르게 전환
                    break

    raise last_error


def smart_rule_based_query_fallback(user_query, df, diagnosis):
    """
    Gemini API가 500 INTERNAL 등 외부 장애로 전혀 응답하지 못할 때도,
    시스템이 멈추지 않고 사용자의 질문 키워드를 분석하여 안전하게 차트와 답변을 생성하는 자체 로컬 규칙 엔진
    """
    rec_year = diagnosis.get("recommended_reference_year", "2024")
    label_col = diagnosis.get("label_candidate_column", df.columns[0])
    q_lower = user_query.lower()

    # 대상 국가 탐색
    target_entity = None
    for token in ["대한민국", "한국", "korea", "south korea", "미국", "united states", "usa", "중국", "china", "일본", "japan", "독일", "germany"]:
        if token in q_lower:
            target_entity = find_matching_entity(df, label_col, token)
            if target_entity:
                break

    # 1. 시계열/추이 키워드
    if any(k in q_lower for k in ["추이", "변화", "시계열", "흐름", "연도별", "역대", "역사"]):
        items = [target_entity] if target_entity else ["Korea, Rep.", "United States", "Japan", "Germany"]
        # 존재하는 아이템 필터링
        valid_items = [it for it in items if it in df[label_col].values]
        if not valid_items:
            valid_items = list(df[label_col].dropna().unique()[:4])
        return {
            "answer": f"**'{user_query}'**에 대한 연도별 시계열 추이 분석을 준비했습니다.\n\n"
                      f"- 데이터 기준: **{diagnosis.get('row_count', 0):,}개 항목**의 시계열 변화\n"
                      f"- 비교 대상: **{', '.join(valid_items)}**\n"
                      f"- 아래 버튼을 누르면 연도별 변화 흐름을 꺾은선 그래프로 바로 확인할 수 있습니다.",
            "tool": "trend_line",
            "params": {"items": valid_items},
            "button_label": f"📈 {', '.join(valid_items[:2])} 연도별 추이 차트 보기",
            "reason": "연도별 변화 및 시계열 흐름 질의에 가장 적합한 도구입니다."
        }

    # 2. 비교/위치 키워드 (전체 중 어디, 평균 비교)
    if any(k in q_lower for k in ["어디", "위치", "평균", "비교", "차이", "대비", "수준"]) and target_entity:
        return {
            "answer": f"**{target_entity}**의 지표가 전체 분포 및 평균/중앙값 대비 어디에 위치하는지 분석을 구성했습니다.\n\n"
                      f"- 기준 연도: **{rec_year}년** (결측치가 가장 적은 권장 시점)\n"
                      f"- 대상 국가: **{target_entity}**\n"
                      f"- 왜곡 방지: 대륙별·소득그룹별 합산행을 자동 제외하고 독립 국가 단위로만 비교합니다.",
            "tool": "compare_one_vs_all",
            "params": {"reference_period": rec_year, "target_item": target_entity, "exclude_aggregates": True},
            "button_label": f"📊 {target_entity} vs 전체 평균·분포 비교 차트 보기",
            "reason": "특정 국가와 전체 분포(평균, 중앙값)의 격차를 가장 직관적으로 보여줍니다."
        }

    # 3. 기본 및 순위 키워드 (1~10등, 상위, 하위, 순위 등)
    # top_n 또는 기본 fallback
    n_match = re.search(r"(\d+)\s*(?:등|위|개국|개)", user_query)
    n_val = int(n_match.group(1)) if n_match else 10
    if n_val < 3 or n_val > 50:
        n_val = 10

    include_item = target_entity or ("Korea, Rep." if "Korea, Rep." in df[label_col].values else None)
    params = {
        "reference_period": rec_year,
        "n": n_val,
        "mode": "top",
        "exclude_aggregates": True
    }
    if include_item:
        params["include_item"] = include_item

    ans_text = (
        f"**'{user_query}'** 질의에 맞춰 **{rec_year}년 기준 상위 {n_val}개국 순위 분석**을 구성했습니다.\n\n"
        f"- 기준 시점: **{rec_year}년**\n"
        f"- 순위 범위: 상위 1~{n_val}위"
    )
    if include_item:
        ans_text += f" 및 비교를 위해 **{include_item}**을 함께 포함(주황색 막대로 강조 표시)합니다."

    return {
        "answer": ans_text,
        "tool": "top_bottom_n",
        "params": params,
        "button_label": f"📊 {rec_year}년 상위 {n_val}개국" + (f" 및 {include_item}" if include_item else "") + " 순위 차트 보기",
        "reason": "글로벌 순위 및 국가 간 상대적 수준 비교에 가장 최적화된 도구입니다."
    }


def detect_encoding_and_read(raw_bytes):
    """
    허용 인코딩(utf-8-sig, utf-8, cp949, euc-kr)을 순차 시도하여 텍스트와 성공한 인코딩 반환
    """
    encodings = ["utf-8-sig", "utf-8", "cp949", "euc-kr"]
    for enc in encodings:
        try:
            text = raw_bytes.decode(enc)
            logger.info(f"[ENCODING] {enc} 시도 성공")
            return text, enc
        except UnicodeDecodeError as e:
            logger.info(f"[ENCODING] {enc} 시도 실패: {e}")
    return None, None


def detect_header_row(text):
    """
    앞쪽 최대 25줄을 검사하여 유의미한 열 이름이 가장 많은 헤더 행 번호(건너뛸 줄 수)를 감지
    """
    lines = text.splitlines()[:25]
    if not lines:
        return 0

    best_row = 0
    max_valid_cols = 0

    for i in range(min(len(lines), 20)):
        line = lines[i].strip()
        if not line:
            continue
        try:
            reader = csv.reader(io.StringIO(line))
            cols = next(reader, [])
            valid_cols = sum(1 for c in cols if c.strip())
            if valid_cols > max_valid_cols:
                max_valid_cols = valid_cols
                best_row = i
        except Exception:
            continue

    return best_row


def diagnose_dataframe(df):
    """
    13대 종합 진단 항목 분석 함수
    """
    warnings = []
    row_count = len(df)
    col_count = len(df.columns)
    column_names = [str(c) for c in df.columns]

    column_types = {str(c): str(df[c].dtype) for c in df.columns}

    year_pattern = re.compile(r"^(19|20)\d{2}$")
    year_columns = [str(c) for c in df.columns if year_pattern.match(str(c).strip())]
    numeric_columns = [str(c) for c in df.select_dtypes(include=["number"]).columns]
    categorical_columns = [str(c) for c in df.select_dtypes(include=["object", "string", "category"]).columns]

    missing_values = {}
    high_missing_cols = []
    for c in df.columns:
        c_str = str(c)
        na_count = int(df[c].isna().sum())
        na_ratio = round(float(df[c].isna().mean()), 4) if row_count > 0 else 0.0
        missing_values[c_str] = {"count": na_count, "ratio": na_ratio}
        if na_ratio >= 0.8:
            high_missing_cols.append(c_str)

    if high_missing_cols:
        warnings.append(f"결측치 비율이 80% 이상인 열이 {len(high_missing_cols)}개 있습니다 (예: {high_missing_cols[:3]}).")

    dup_count = int(df.duplicated().sum())
    if dup_count > 0:
        warnings.append(f"모든 열의 값이 동일한 중복 행이 {dup_count}개 발견되었습니다.")

    unnamed_cols = [str(c) for c in df.columns if str(c).startswith("Unnamed:") or not str(c).strip()]
    empty_cols = [str(c) for c in df.columns if df[c].isna().all()]
    if unnamed_cols:
        warnings.append(f"이름이 없는 Unnamed 열이 {len(unnamed_cols)}개 감지되었습니다: {unnamed_cols[:3]}")
    if empty_cols:
        warnings.append(f"데이터가 전혀 없는 빈 열이 {len(empty_cols)}개 감지되었습니다: {empty_cols[:3]}")

    year_coverage = {}
    if year_columns:
        for y in year_columns:
            cnt = int(df[y].notna().sum())
            year_coverage[y] = {
                "count": cnt,
                "ratio": round(float(cnt / row_count), 4) if row_count > 0 else 0.0
            }

    recommended_year = None
    if year_columns:
        sorted_years = sorted(year_columns, key=lambda x: int(x), reverse=True)
        max_fill = max(year_coverage[y]["count"] for y in year_columns) if year_coverage else 0
        if max_fill > 0:
            for y in sorted_years:
                if year_coverage[y]["count"] >= max_fill * 0.8:
                    recommended_year = y
                    break
            if not recommended_year:
                recommended_year = max(year_coverage.items(), key=lambda item: item[1]["count"])[0]

    agg_keywords = [
        "world", "oecd members", "euro area", "european union",
        "high income", "low income", "middle income", "income", "area",
        "total", "aggregate", "latin america", "sub-saharan africa",
        "north america", "east asia", "south asia", "arab world"
    ]
    aggregate_rows = []
    label_col = categorical_columns[0] if categorical_columns else (df.columns[0] if len(df.columns) > 0 else None)
    if label_col is not None:
        for idx, val in df[label_col].dropna().items():
            val_lower = str(val).lower()
            matched = [k for k in agg_keywords if k in val_lower]
            if matched:
                aggregate_rows.append({
                    "row_index": int(idx),
                    "label": str(val),
                    "matched_keyword": matched[0]
                })

    if aggregate_rows:
        warnings.append(f"전체 요약 또는 지역 집계 행으로 추정되는 행이 {len(aggregate_rows)}개 감지되었습니다 (개별 개체 분석 시 제외 권장).")

    preview_df = df.head(10).copy()
    preview_rows = json.loads(preview_df.to_json(orient="records", date_format="iso"))

    return {
        "row_count": row_count,
        "column_count": col_count,
        "column_names": column_names,
        "column_types": column_types,
        "numeric_columns": numeric_columns,
        "categorical_columns": categorical_columns,
        "year_columns": year_columns,
        "missing_values": missing_values,
        "duplicate_rows_count": dup_count,
        "unnamed_columns": unnamed_cols,
        "empty_columns": empty_cols,
        "year_coverage": year_coverage,
        "recommended_reference_year": recommended_year,
        "aggregate_rows": aggregate_rows,
        "preview_rows": preview_rows,
        "warnings": warnings
    }


@app.route("/")
def index():
    """메인 화면 라우트 (index.html 제공)"""
    try:
        return render_template("index.html")
    except Exception:
        return "AI Data Insight Builder Server is running."


@app.route("/health", methods=["GET"])
def health():
    """서버 상태와 API Key 설정 여부 확인 라우트 (API Key 원문은 절대 노출 금지)"""
    logger.info("[REQUEST] GET /health")

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

    has_api_key = bool(api_key and api_key != "your_gemini_api_key_here")

    response_data = {
        "status": "ok",
        "api_key_configured": has_api_key,
        "model": model
    }
    logger.info(f"[RESPONSE] status=200 api_key_configured={has_api_key} model={model}")
    return jsonify(response_data)


@app.route("/inspect", methods=["POST"])
def inspect_file():
    """
    POST /inspect:
    - CSV 업로드 검증
    - 인코딩 순차 시도 및 헤더 감지
    - 13대 데이터 종합 진단 수행
    - 메모리에 1개 데이터셋 보관
    """
    global CURRENT_DATASET
    logger.info("[REQUEST] POST /inspect")

    if "file" not in request.files:
        logger.error("[ERROR] 파일 미선택: request.files에 'file' 키가 없습니다.")
        return jsonify({"success": False, "error": "파일이 선택되지 않았습니다. 분석할 CSV 파일을 업로드해 주세요."}), 400

    file = request.files["file"]
    filename = file.filename or ""

    if not filename:
        logger.error("[ERROR] 파일명 없음")
        return jsonify({"success": False, "error": "파일이 선택되지 않았습니다. 분석할 CSV 파일을 업로드해 주세요."}), 400

    if not filename.lower().endswith(".csv"):
        logger.error(f"[ERROR] 허용되지 않은 확장자: {filename}")
        return jsonify({"success": False, "error": "CSV 형식(.csv)의 파일만 지원됩니다."}), 400

    try:
        raw_bytes = file.read()
    except Exception as e:
        logger.error(f"[ERROR] 파일 읽기 실패: {e}\n{traceback.format_exc()}")
        return jsonify({"success": False, "error": "파일을 읽는 도중 오류가 발생했습니다."}), 400

    file_size = len(raw_bytes)
    logger.info(f"[FILE] name={filename} size={file_size}")

    if file_size == 0:
        logger.error("[ERROR] 빈 파일")
        return jsonify({"success": False, "error": "업로드된 파일의 내용이 비어 있습니다."}), 400

    content_text, detected_encoding = detect_encoding_and_read(raw_bytes)
    if not content_text:
        logger.error("[ERROR] 인코딩 전부 실패")
        return jsonify({"success": False, "error": "지원하는 인코딩(utf-8-sig, utf-8, cp949, euc-kr)으로 파일을 읽지 못했습니다."}), 400

    skip_rows = detect_header_row(content_text)
    logger.info(f"[HEADER] 헤더 줄 감지 결과 (건너뛴 줄 수: {skip_rows})")

    try:
        df = pd.read_csv(io.StringIO(content_text), skiprows=skip_rows)
    except Exception as e:
        logger.error(f"[ERROR] CSV 파싱 실패: {e}\n{traceback.format_exc()}")
        return jsonify({"success": False, "error": f"CSV 데이터를 파싱하는 데 실패했습니다: {str(e)}"}), 400

    logger.info(f"[CSV] parsing 완료 rows={len(df)} columns={len(df.columns)}")

    diagnosis = diagnose_dataframe(df)
    logger.info(f"[DIAGNOSE] 진단 완료 warnings={len(diagnosis['warnings'])}")

    CURRENT_DATASET = {
        "filename": filename,
        "file_size": file_size,
        "encoding": detected_encoding,
        "skip_rows": skip_rows,
        "df": df,
        "diagnosis": diagnosis
    }

    response_payload = {
        "success": True,
        "file_name": filename,
        "file_size_bytes": file_size,
        "encoding": detected_encoding,
        "skip_rows": skip_rows,
        "diagnosis": diagnosis,
        "notice": "데이터셋은 서버 메모리에 임시 보관되며, 서버를 재시작하면 사라집니다."
    }

    logger.info(f"[RESPONSE] status=200 rows={diagnosis['row_count']} columns={diagnosis['column_count']}")
    return jsonify(response_payload)


@app.route("/suggest", methods=["POST"])
def suggest_analyses():
    """
    POST /suggest:
    - 진단 결과 요약과 12대 도구 카탈로그를 Gemini에게 전달
    - CSV 원본은 절대 전송하지 않음
    - Gemini JSON 응답 강제 (3~5개 추천 도구)
    - 허용된 도구 및 데이터 열만 제안하도록 엄격 검증
    """
    global CURRENT_DATASET
    logger.info("[REQUEST] POST /suggest")

    # 1. 메모리 데이터셋 존재 여부 확인
    if CURRENT_DATASET is None or "df" not in CURRENT_DATASET:
        logger.error("[ERROR] 메모리에 데이터셋 없음")
        return jsonify({"success": False, "error": "분석할 데이터셋이 없습니다. 먼저 CSV 파일을 업로드하여 진단을 완료해 주세요."}), 400

    # 2. Gemini API Key 및 모델명 확인
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        logger.error("[ERROR] GEMINI_API_KEY 미설정")
        return jsonify({"success": False, "error": "GEMINI_API_KEY 환경변수가 설정되지 않았습니다. .env 파일을 확인해 주세요."}), 400

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

    diagnosis = CURRENT_DATASET.get("diagnosis", {})
    filename = CURRENT_DATASET.get("filename", "")

    # 3. Gemini에게 전달할 진단 요약 구성 (CSV 원본 전체 절대 금지)
    diag_summary = {
        "filename": filename,
        "total_rows": diagnosis.get("row_count"),
        "total_columns": diagnosis.get("column_count"),
        "column_names": diagnosis.get("column_names", [])[:30], # 핵심 열 이름들
        "numeric_columns": diagnosis.get("numeric_columns", [])[:20],
        "categorical_columns": diagnosis.get("categorical_columns", [])[:10],
        "year_columns_range": f"{diagnosis.get('year_columns', ['N/A'])[0]} ~ {diagnosis.get('year_columns', ['N/A'])[-1]}" if diagnosis.get("year_columns") else "None",
        "recommended_reference_year": diagnosis.get("recommended_reference_year"),
        "aggregate_rows_count": len(diagnosis.get("aggregate_rows", [])),
        "aggregate_sample": [r["label"] for r in diagnosis.get("aggregate_rows", [])[:5]],
        "warnings": diagnosis.get("warnings", [])
    }

    # 4. 도구 카탈로그 요약 구성 (Gemini는 카탈로그에 있는 도구만 제안 가능)
    catalog_summary = {}
    for tool_key, info in TOOL_CATALOG.items():
        catalog_summary[tool_key] = {
            "name": info["name"],
            "description": info["description"],
            "requires_reference_period": info["requires_ref_period"]
        }

    # 5. 프롬프트 작성 (JSON 형식 강제)
    system_instruction = (
        "당신은 공공 및 통계 데이터를 분석하는 Senior Data Analyst이자 데이터 교육 전문가입니다.\n"
        "제공된 데이터 진단 요약(Diagnosis Summary)을 바탕으로, "
        "사용자에게 가장 통찰력 있고 실질적인 가치를 주는 분석을 도구 카탈로그(Tool Catalog)에서 골라 3~5개 제안하세요.\n\n"
        "절대 규칙:\n"
        "1. 반드시 제공된 Tool Catalog에 존재하는 도구(tool)만 제안할 수 있습니다.\n"
        "2. params에는 데이터셋에 실제로 존재하는 열 이름만 사용해야 합니다.\n"
        "3. 7~12번 도구(requires_reference_period=True)를 제안할 때는 반드시 권장 기준연도(recommended_reference_year)를 reference_period로 지정하세요.\n"
        "4. 국가/개체 간 비교 시에는 왜곡을 방지하기 위해 exclude_aggregates=True를 설정하세요.\n"
        "5. 반드시 순수 JSON 형식으로만 응답해야 하며 마크다운 코드블록이나 불필요한 설명을 붙이지 마세요.\n"
        "6. 숫자를 직접 계산하지 마세요. 도구 실행을 위한 파라미터와 제안 이유만 작성하세요."
    )

    prompt = f"""
[데이터 진단 요약]
{json.dumps(diag_summary, ensure_ascii=False, indent=2)}

[사용 가능한 12대 도구 카탈로그]
{json.dumps(catalog_summary, ensure_ascii=False, indent=2)}

다음 JSON 스키마를 엄격히 준수하여 3~5개의 분석을 제안하세요:
{{
  "suggestions": [
    {{
      "tool": "카탈로그에_있는_도구_ID",
      "params": {{
        "reference_period": "{diagnosis.get('recommended_reference_year', '2024')}",
        "exclude_aggregates": true
      }},
      "reference_period": "{diagnosis.get('recommended_reference_year', '2024')}",
      "why": "이 분석이 이 데이터에서 의미 있는 이유 (초보자도 이해할 수 있는 명쾌한 설명)",
      "caution": "해석할 때 주의할 점"
    }}
  ]
}}
"""

    logger.info(f"[AI] suggest 요청 시작 (model={model_name})")

    raw_suggestions = []
    try:
        client = genai.Client(api_key=api_key)
        response, used_model = call_gemini_resilient(
            client=client,
            primary_model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json", # JSON 출력 강제
                temperature=0.2
            )
        )
        response_text = response.text or "{}"
        logger.info(f"[AI] suggest 응답 수신 (model={used_model})")
        clean_json_str = re.sub(r"^```json\s*|\s*```$", "", response_text.strip())
        parsed = json.loads(clean_json_str)
        raw_suggestions = parsed.get("suggestions", [])
        logger.info(f"[AI] JSON 파싱 결과: {len(raw_suggestions)}개 제안")
    except Exception as e:
        logger.warning(f"[WARN] Gemini API 호출/파싱 실패 (suggest): {e}. 기본 3대 권장 분석으로 fallback합니다.")
        raw_suggestions = []

    # 7. 카탈로그 제한 및 도구 메타데이터 보강
    valid_suggestions = []
    for item in raw_suggestions:
        tool_id = item.get("tool")
        if tool_id in TOOL_CATALOG:
            tool_meta = TOOL_CATALOG[tool_id]
            valid_suggestions.append({
                "tool": tool_id,
                "tool_name": tool_meta["name"],
                "tool_description": tool_meta["description"],
                "params": item.get("params", {}),
                "reference_period": item.get("reference_period", diagnosis.get("recommended_reference_year", "N/A")),
                "why": item.get("why", "이 데이터셋에서 유의미한 패턴을 파악할 수 있습니다."),
                "caution": item.get("caution", "결측치 및 기준 시점의 적절성을 확인해야 합니다.")
            })

    # 만약 AI가 적합한 도구를 골라내지 못했을 경우의 안전 Fallback (기본 3대 권장 도구)
    if not valid_suggestions:
        rec_yr = diagnosis.get("recommended_reference_year", "2024")
        fallback_tools = ["top_bottom_n", "trend_line", "distribution"]
        for fid in fallback_tools:
            tinfo = TOOL_CATALOG[fid]
            valid_suggestions.append({
                "tool": fid,
                "tool_name": tinfo["name"],
                "tool_description": tinfo["description"],
                "params": {"reference_period": rec_yr, "exclude_aggregates": True},
                "reference_period": rec_yr,
                "why": f"{tinfo['name']}을 통해 핵심 경향을 한눈에 파악할 수 있습니다.",
                "caution": "해당 기준 연도의 결측치 여부를 확인하세요."
            })

    response_payload = {
        "success": True,
        "model": model_name,
        "suggestions": valid_suggestions[:5] # 3~5개 유지
    }

    logger.info(f"[RESPONSE] status=200 suggestions={len(valid_suggestions[:5])}")
    return jsonify(response_payload)


@app.route("/query", methods=["POST"])
def natural_language_query():
    """
    POST /query:
    - 사용자의 자연어 분석 질문을 수신
    - Gemini를 통해 질문에 대한 친절한 사전 해설(answer)과 함께,
      질문 의도에 가장 적합한 도구(tool) 및 파라미터(params)를 JSON으로 도출
    - 프론트엔드는 해설을 출력하고 [맞춤 시각화 분석 실행하기] 버튼을 생성
    - 버튼 클릭 시 /run 및 /explain 파이프라인으로 자연스럽게 이어짐
    """
    global CURRENT_DATASET
    logger.info("[REQUEST] POST /query")

    if CURRENT_DATASET is None or "df" not in CURRENT_DATASET:
        logger.error("[ERROR] 메모리에 데이터셋 없음")
        return jsonify({"success": False, "error": "분석할 데이터셋이 없습니다. 먼저 CSV 파일을 업로드하여 진단을 완료해 주세요."}), 400

    data = request.get_json(silent=True) or {}
    user_query = str(data.get("query", "")).strip()

    if not user_query:
        logger.error("[ERROR] 빈 질의 요청")
        return jsonify({"success": False, "error": "질문 내용을 입력해 주세요."}), 400

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.error("[ERROR] GEMINI_API_KEY 미설정")
        return jsonify({"success": False, "error": "GEMINI_API_KEY가 설정되지 않았습니다."}), 400

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    df = CURRENT_DATASET["df"]
    diagnosis = CURRENT_DATASET.get("diagnosis", {})
    filename = CURRENT_DATASET.get("filename", "")
    rec_year = diagnosis.get("recommended_reference_year", "2024")

    # 대표 라벨 샘플 (국가명 목록 상위 30개 및 Korea 등 검색)
    label_col = diagnosis.get("categorical_columns", [None])[0] or df.columns[0]
    sample_labels = list(df[label_col].dropna().astype(str).unique()[:30])
    korea_matches = [str(x) for x in df[label_col].dropna().unique() if "korea" in str(x).lower()]
    sample_labels.extend(korea_matches)

    # 12대 도구 카탈로그 요약
    catalog_summary = [
        {
            "id": tid,
            "name": tinfo["name"],
            "description": tinfo["description"],
            "requires_ref_period": tinfo.get("requires_ref_period", False)
        }
        for tid, tinfo in TOOL_CATALOG.items()
    ]

    system_instruction = (
        "당신은 공공 통계 데이터셋의 질의를 분석하고 적절한 시각화 도구로 연결해 주는 'Senior Data Analyst'입니다.\n\n"
        "[임무]\n"
        "사용자가 업로드된 데이터셋에 대해 자연어로 질문을 던졌습니다.\n"
        "당신은 2가지를 수행해야 합니다:\n"
        "1. answer: 질문에 대해 초보자도 이해하기 쉬운 친절한 사전 해설(마크다운 지원). "
        "단, 수치를 임의로 지어내지 말고(환각 금지), 데이터 구조와 기준시점의 맥락을 설명하세요.\n"
        "2. tool & params: 사용자의 질문 의도를 시각화하기에 가장 적합한 12대 공식 도구 중 하나를 선택하고, 실행에 필요한 파라미터를 정확히 지정하세요.\n\n"
        "[도구 매핑 가이드]:\n"
        "- 상/하위 순위 또는 특정 국가 포함 순위 (예: 1~10위와 한국 비교):\n"
        "  -> tool: 'top_bottom_n', params: {'reference_period': '" + rec_year + "', 'n': 10, 'mode': 'top', 'include_item': 'Korea, Rep.', 'exclude_aggregates': True}\n"
        "- 특정 개체 vs 전체 평균/중앙값 (예: 한국이 전체 중 어디쯤 위치해?):\n"
        "  -> tool: 'compare_one_vs_all', params: {'reference_period': '" + rec_year + "', 'target_item': 'Korea, Rep.', 'exclude_aggregates': True}\n"
        "- 연도별 시계열 추이 (예: 한국과 미국의 연도별 변화):\n"
        "  -> tool: 'trend_line', params: {'items': ['Korea, Rep.', 'United States']}\n"
        "- 데이터 구간별 분포 (히스토그램):\n"
        "  -> tool: 'distribution', params: {'reference_period': '" + rec_year + "', 'bins': 10}\n"
        "- 변화율/성장률 분석:\n"
        "  -> tool: 'change_rate', params: {'start_period': '2010', 'end_period': '" + rec_year + "'}\n"
        "- 상관관계 산점도:\n"
        "  -> tool: 'correlation_scatter', params: {'reference_period': '" + rec_year + "', 'compare_period': '2010'}\n\n"
        "[반드시 순수 JSON 형식으로 응답]:\n"
        "{\n"
        "  \"answer\": \"친절한 자연어 해설 텍스트\",\n"
        "  \"tool\": \"카탈로그 도구 ID\",\n"
        "  \"params\": { ... },\n"
        "  \"button_label\": \"📊 차트 보기 버튼 라벨 (예: 2024년 상위 10개국 및 대한민국 비교 차트 보기)\",\n"
        "  \"reason\": \"이 도구를 추천한 이유\"\n"
        "}"
    )

    prompt = f"""
[데이터셋 개요]
- 파일명: {filename}
- 전체 규모: {diagnosis.get('row_count')}행 × {diagnosis.get('column_count')}열
- 권장 기준연도: {rec_year}
- 주요 라벨(국가 등) 컬럼명: {label_col}
- 라벨 컬럼 실제 항목 예시: {sample_labels[:20]}
- 4자리 연도 열 목록: {diagnosis.get('year_columns', [])[-10:]}

[12대 도구 카탈로그]
{json.dumps(catalog_summary, ensure_ascii=False, indent=2)}

[사용자의 자연어 질문]
"{user_query}"

위 사용자의 자연어 질문에 대해 정직한 자연어 해설과 가장 적합한 도구 및 파라미터를 JSON으로 응답해 주세요.
"""

    logger.info(f"[AI] query 요청 시작 (model={model_name})")

    parsed = None
    try:
        client = genai.Client(api_key=api_key)
        response, used_model = call_gemini_resilient(
            client=client,
            primary_model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        response_text = response.text or "{}"
        logger.info(f"[AI] query 응답 수신 (model={used_model})")
        clean_json_str = re.sub(r"^```json\s*|\s*```$", "", response_text.strip())
        parsed = json.loads(clean_json_str)
    except Exception as e:
        logger.warning(f"[WARN] Gemini API 호출/파싱 실패 (query): {e}. 로컬 스마트 규칙 엔진으로 fallback 전환합니다.")
        parsed = smart_rule_based_query_fallback(user_query, df, diagnosis)

    # 1. 도구 유효성 검증
    tool_id = parsed.get("tool")
    if tool_id not in TOOL_CATALOG:
        tool_id = "top_bottom_n"

    params = parsed.get("params", {})
    tinfo = TOOL_CATALOG[tool_id]
    warnings_list = []

    # 2. 외부 다중 지표(GDP 등) 요청 시 correlation_scatter 등 우회 방어
    year_pattern = re.compile(r"^(19|20)\d{2}$")
    valid_year_cols = [str(c) for c in df.columns if year_pattern.match(str(c).strip())]

    if tool_id == "correlation_scatter":
        col1 = params.get("col1")
        col2 = params.get("col2")
        non_year_num_cols = [c for c in df.select_dtypes(include=[np.number]).columns if str(c) not in valid_year_cols]
        # 단일 지표 파일인데 2개 이상의 별도 경제 지표 상관분석을 요구한 경우
        if len(non_year_num_cols) < 2 and (not col1 or str(col1) not in df.columns or not col2 or str(col2) not in df.columns):
            tool_id = "trend_line"
            tinfo = TOOL_CATALOG[tool_id]
            params = {"items": ["Korea, Rep.", "United States", "Japan", "Germany"]}
            warnings_list.append("현재 데이터셋에는 GDP 등 2개 이상의 서로 다른 경제 지표가 포함되어 있지 않아, 주요국의 '연도별 시계열 추이 분석'으로 자동 우회하여 시각화합니다.")

    # 3. 기준 연도(reference_period) 유효성 및 결측치 방어
    if tinfo.get("requires_ref_period"):
        req_ref = str(params.get("reference_period", "")).strip()
        if not req_ref or req_ref not in df.columns or df[req_ref].notna().sum() < 3:
            params["reference_period"] = rec_year
            if req_ref and req_ref != rec_year:
                warnings_list.append(f"요청하신 '{req_ref}년'은 데이터가 없거나 결측치가 많아, 가장 데이터가 풍부한 최신 기준연도인 '{rec_year}년'으로 자동 보정되었습니다.")

    # 4. 집계행 제외 기본 활성화
    if "exclude_aggregates" not in params:
        params["exclude_aggregates"] = True

    # 5. 국가명 별칭 사전 자동 매칭 (include_item, target_item, items)
    if "include_item" in params and params["include_item"]:
        matched = find_matching_entity(df, label_col, params["include_item"])
        if matched:
            params["include_item"] = matched
    if "target_item" in params and params["target_item"]:
        matched = find_matching_entity(df, label_col, params["target_item"])
        if matched:
            params["target_item"] = matched
    if "items" in params and isinstance(params["items"], list):
        resolved_items = []
        for it in params["items"]:
            m = find_matching_entity(df, label_col, it)
            if m and m not in resolved_items:
                resolved_items.append(m)
        if resolved_items:
            params["items"] = resolved_items

    answer_text = parsed.get("answer", "질문에 맞춰 분석 파라미터를 구성했습니다.")
    if warnings_list:
        warning_block = "\n\n> 🛡️ **스마트 자동 보정 안내**\n> " + "\n> ".join(warnings_list)
        answer_text += warning_block

    response_payload = {
        "success": True,
        "query": user_query,
        "answer": answer_text,
        "tool": tool_id,
        "tool_name": tinfo["name"],
        "params": params,
        "button_label": parsed.get("button_label", f"📊 {tinfo['name']} 차트 보기"),
        "reason": parsed.get("reason", "질문 의도에 가장 부합하는 분석 도구입니다.")
    }

    logger.info(f"[RESPONSE] status=200 query mapped to tool={tool_id}")
    return jsonify(response_payload)


@app.route("/run", methods=["POST"])
def run_tool():
    """
    POST /run:
    - 선택된 도구를 Pandas로 직접 실행
    - 숫자 계산은 절대 Gemini에게 시키지 않고 Pandas가 수행
    - 7~12번 도구는 reference_period 필수 검증
    - 계산 결과 + 차트 데이터 + 메타데이터(기준시점, 사용/제외 행 수, 이유 등) 반환
    - 직전 실행 결과를 CURRENT_DATASET["last_run_result"]에 보관하여 /explain에서 활용
    """
    global CURRENT_DATASET
    logger.info("[REQUEST] POST /run")

    if CURRENT_DATASET is None or "df" not in CURRENT_DATASET:
        logger.error("[ERROR] 메모리에 데이터셋 없음")
        return jsonify({"success": False, "error": "분석할 데이터셋이 없습니다. 먼저 CSV 파일을 업로드하여 진단을 완료해 주세요."}), 400

    data = request.get_json(silent=True) or {}
    tool_id = data.get("tool")
    params = data.get("params", {})

    if not tool_id:
        logger.error("[ERROR] 도구명 미지정")
        return jsonify({"success": False, "error": "실행할 도구(tool)를 지정해 주세요."}), 400

    if tool_id not in TOOL_CATALOG:
        logger.error(f"[ERROR] 도구 카탈로그에 없는 도구 요청: {tool_id}")
        return jsonify({"success": False, "error": f"도구 카탈로그에 존재하지 않는 도구입니다: '{tool_id}'"}), 400

    tool_info = TOOL_CATALOG[tool_id]
    tool_func = tool_info["func"]
    df = CURRENT_DATASET["df"]

    # 도구 실행 (순수 Pandas 연산) - 허용된 파라미터만 안전하게 필터링
    import inspect
    sig = inspect.signature(tool_func)
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    if not accepts_kwargs:
        filtered_params = {k: v for k, v in params.items() if k in sig.parameters}
    else:
        filtered_params = params

    try:
        result = tool_func(df, **filtered_params)
    except TypeError as e:
        logger.error(f"[ERROR] 도구 '{tool_id}' 파라미터 불일치: {e}")
        return jsonify({"success": False, "error": f"도구 파라미터가 올바르지 않습니다: {str(e)}"}), 400
    except Exception as e:
        logger.error(f"[ERROR] 도구 '{tool_id}' 실행 중 예외 발생: {e}\n{traceback.format_exc()}")
        return jsonify({"success": False, "error": f"도구 실행 중 오류가 발생했습니다: {str(e)}"}), 500

    if not result.get("success"):
        logger.error(f"[ERROR] 도구 '{tool_id}' 실행 실패: {result.get('error')}")
        return jsonify(result), 400

    used_rows = result.get("used_rows", 0)
    excluded_rows = result.get("excluded_rows", 0)
    logger.info(f"[TOOL] 도구명={tool_id}, 파라미터={params}, 사용 행 수={used_rows}, 제외 행 수={excluded_rows}")

    # Step 19 /explain을 위해 직전 분석 결과 메모리 저장
    CURRENT_DATASET["last_run_result"] = result

    logger.info(f"[RESPONSE] status=200 tool={tool_id}")
    return jsonify(result)


@app.route("/explain", methods=["POST"])
def explain_result():
    """
    POST /explain:
    - Gemini를 통한 분석 결과 해석
    - 모드 A (비교용, 의도적으로 허술하게):
      진단 요약만 전달하고 계산 결과를 주지 않은 채 자유 보고서 작성 요청 (추정/환각 발생)
    - 모드 B (정식):
      Pandas 계산 결과(표, 기준시점, 사용/제외 행 수)만 전달하고 8대 해석 규칙과 7대 헤딩 구조 준수 강제
    """
    global CURRENT_DATASET
    logger.info("[REQUEST] POST /explain")

    if CURRENT_DATASET is None or "df" not in CURRENT_DATASET:
        logger.error("[ERROR] 메모리에 데이터셋 없음")
        return jsonify({"success": False, "error": "분석할 데이터셋이 없습니다. 먼저 CSV 파일을 업로드하여 진단을 완료해 주세요."}), 400

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        logger.error("[ERROR] GEMINI_API_KEY 미설정")
        return jsonify({"success": False, "error": "GEMINI_API_KEY 환경변수가 설정되지 않았습니다. .env 파일을 확인해 주세요."}), 400

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode", "B")).strip().upper()
    if mode not in ("A", "B"):
        mode = "B"

    # 계산 결과 확보
    calc_result = data.get("calculation_result") or CURRENT_DATASET.get("last_run_result")
    if not calc_result and mode == "B":
        logger.error("[ERROR] 계산 결과 없음 (/run 선행 필요)")
        return jsonify({"success": False, "error": "해석할 계산 결과가 없습니다. 먼저 분석 도구(/run)를 실행해 주세요."}), 400

    diagnosis = CURRENT_DATASET.get("diagnosis", {})
    filename = CURRENT_DATASET.get("filename", "")

    logger.info(f"[AI] explain 요청 시작 (모드={mode}, model={model_name})")

    try:
        client = genai.Client(api_key=api_key)

        if mode == "A":
            # ----------------------------------------------------
            # 모드 A (비교용, 의도적으로 허술하게):
            # 진단 요약만 전달하고 계산 결과는 주지 않음 -> AI의 추정/환각 유도
            # ----------------------------------------------------
            system_instruction = (
                "당신은 일반 AI 어시스턴트입니다. "
                "사용자가 제공한 데이터 개요만 보고, 자유롭게 분석 보고서를 작성해 주세요."
            )
            prompt = f"""
다음 데이터 파일에 대한 데이터 분석 보고서를 작성해 주세요.
파일명: {filename}
데이터 행 수: {diagnosis.get('row_count')}
열 수: {diagnosis.get('column_count')}
열 목록: {diagnosis.get('column_names', [])[:15]}

이 데이터의 주요 트렌드, 특징, 원인을 자유롭게 추정하여 분석 보고서를 작성해 주세요.
"""
        else:
            # ----------------------------------------------------
            # 모드 B (정식):
            # Pandas 계산 결과만 전달 + 8대 규칙 + 7대 헤딩 구조
            # ----------------------------------------------------
            system_instruction = (
                "당신은 데이터 리터러시와 엄밀한 과학적 통계 해석을 중시하는 Senior Data Analyst입니다.\n"
                "오직 제공된 Pandas 계산 결과에만 기반하여 초보자도 쉽게 이해할 수 있는 신뢰성 높은 보고서를 작성하세요.\n\n"
                "반드시 지켜야 할 8대 절대 규칙:\n"
                "1. 제공된 계산 결과에 있는 숫자만 사용하세요.\n"
                "2. 직접 계산하거나 추정하지 마세요.\n"
                "3. 데이터에 없는 국가·연도·열을 임의로 언급하지 마세요.\n"
                "4. 기준 시점과 제외된 행 수를 반드시 본문에 명시하세요.\n"
                "5. 상관관계를 인과관계로 표현하지 마세요 (상관관계 != 인과관계).\n"
                "6. 지표의 정의와 출처를 보고서 앞부분에 표기하세요.\n"
                "7. 확인할 수 없는 것은 '이 데이터로는 확인할 수 없다'라고 분명하게 쓰세요.\n"
                "8. 중학생도 이해할 수 있게 쉬운 말로 쓰되 정확성을 희생하지 마세요.\n\n"
                "보고서는 반드시 아래 7개 마크다운 헤딩 형식을 순서대로 정확히 지켜서 작성하세요:\n"
                "## 무엇을 봤는가\n"
                "## 데이터 출처와 정의\n"
                "## 기준 시점과 제외된 항목\n"
                "## 계산 결과\n"
                "## 읽어낼 수 있는 것\n"
                "## 이 데이터로는 알 수 없는 것\n"
                "## 다음에 확인해볼 것"
            )

            # 계산 결과 요약 페이로드
            calc_summary = {
                "tool": calc_result.get("tool"),
                "title": calc_result.get("title"),
                "summary": calc_result.get("summary"),
                "reference_period": calc_result.get("reference_period"),
                "used_rows": calc_result.get("used_rows"),
                "excluded_rows": calc_result.get("excluded_rows"),
                "exclusion_reason": calc_result.get("exclusion_reason"),
                "used_columns": calc_result.get("used_columns"),
                "unit": calc_result.get("unit"),
                "cautions": calc_result.get("cautions"),
                "calculated_data_table": calc_result.get("data", {}).get("table") or calc_result.get("data", {}).get("statistics") or calc_result.get("data", {})
            }

            prompt = f"""
[데이터셋 출처 메타데이터]
- 파일명: {filename}
- 전체 항목 수: {diagnosis.get('row_count')}행

[Pandas 실제 계산 결과]
{json.dumps(calc_summary, ensure_ascii=False, indent=2)}

위 Pandas 계산 결과만을 정확히 근거로 삼아, 8대 규칙과 7개 헤딩 구조를 준수하여 마크다운 보고서를 작성해 주세요.
"""

        client = genai.Client(api_key=api_key)
        response, used_model = call_gemini_resilient(
            client=client,
            primary_model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.3
            )
        )
        explanation_text = response.text or ""
        logger.info(f"[AI] explain 응답 수신 (모드={mode}, model={used_model})")

    except Exception as e:
        logger.error(f"[ERROR] Gemini API 호출 실패 (explain): {e}\n{traceback.format_exc()}")
        return jsonify({"success": False, "error": f"AI 해석 생성 중 오류가 발생했습니다: {str(e)}"}), 500

    response_payload = {
        "success": True,
        "mode": mode,
        "model": model_name,
        "explanation": explanation_text
    }

    logger.info(f"[RESPONSE] status=200 mode={mode}")
    return jsonify(response_payload)


@app.route("/followup", methods=["POST"])
def followup_question():
    """
    POST /followup:
    - 현재 분석 결과(계산표, 메타데이터, 진단정보)에 대해 사용자의 후속 질문을 수신
    - 초보자 눈높이에 맞춰 친절하고 명쾌하게 일상 언어로 해설
    - 절대 데이터에 없는 사실을 지어내지 않고(환각 방지), 알 수 없는 점은 솔직히 한계를 명시
    """
    global CURRENT_DATASET
    logger.info("[REQUEST] POST /followup")

    if CURRENT_DATASET is None or "df" not in CURRENT_DATASET:
        logger.error("[ERROR] 메모리에 데이터셋 없음")
        return jsonify({"success": False, "error": "분석할 데이터셋이 없습니다. 먼저 CSV 파일을 업로드하여 진단을 완료해 주세요."}), 400

    last_run = CURRENT_DATASET.get("last_run_result")
    if not last_run:
        logger.error("[ERROR] 직전 분석 결과 없음")
        return jsonify({"success": False, "error": "먼저 분석 도구를 실행(Step 4)한 후 질문해 주세요."}), 400

    data = request.get_json(silent=True) or {}
    user_question = str(data.get("question", "")).strip()
    history = data.get("history", [])

    if not user_question:
        logger.error("[ERROR] 빈 질문 요청")
        return jsonify({"success": False, "error": "질문 내용을 입력해 주세요."}), 400

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.error("[ERROR] GEMINI_API_KEY 미설정")
        return jsonify({"success": False, "error": "GEMINI_API_KEY가 설정되지 않았습니다."}), 400

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    diagnosis = CURRENT_DATASET.get("diagnosis", {})
    filename = CURRENT_DATASET.get("filename", "")

    # 직전 계산 결과 요약 준비
    calc_summary = {
        "tool": last_run.get("tool"),
        "title": last_run.get("title"),
        "reference_period": last_run.get("reference_period"),
        "used_rows": last_run.get("used_rows"),
        "excluded_rows": last_run.get("excluded_rows"),
        "exclusion_reason": last_run.get("exclusion_reason"),
        "summary": last_run.get("summary"),
        "cautions": last_run.get("cautions")
    }
    inner_data = last_run.get("data", {})
    table_sample = inner_data.get("table") or inner_data.get("coverage_table") or inner_data.get("statistics")
    if table_sample and isinstance(table_sample, list):
        calc_summary["table_preview"] = table_sample[:15]
    elif table_sample and isinstance(table_sample, dict):
        calc_summary["statistics_preview"] = table_sample

    system_instruction = (
        "당신은 통계와 데이터를 처음 접하는 초보자에게 친절하게 설명해 주는 '데이터 멘토'이자 교육 전문가입니다.\n\n"
        "[핵심 해설 원칙]\n"
        "1. 초보자 눈높이의 친절하고 쉬운 일상 언어로 설명하세요. 전문 용어(예: 결측치, 분위수, 편차, 집계행 등)를 쓸 때는 반드시 일상적인 비유나 쉬운 풀이(예: '결측치(기록이 비어 있는 칸)')를 함께 덧붙이세요.\n"
        "2. 숫자는 오직 제공된 [Pandas 실제 계산 결과]와 [데이터셋 진단]에 실제로 존재하는 수치만 인용하세요. 데이터에 없는 임의의 숫자를 지어내지 마세요(환각 엄금).\n"
        "3. 만약 질문이 데이터에 없는 사실(예: '왜 이런 결과가 나왔는지 배경 정책이나 이유', '인과관계')을 묻는다면, '현재 데이터셋만으로는 그 이유/인과관계를 확정할 수 없습니다'라고 솔직히 한계를 밝히고, 어떤 추가 데이터나 조사가 필요한지 안내하세요.\n"
        "4. 상관관계와 인과관계를 절대 혼동하지 않도록 주의시키세요.\n"
        "5. 답변은 마크다운(강조, 불릿 포인트 등)을 활용하여 읽기 편하고 시각적으로 깔끔하게 구성하세요."
    )

    history_text = ""
    if history and isinstance(history, list):
        history_lines = []
        for turn in history[-4:]:
            role_label = "사용자" if turn.get("role") == "user" else "멘토 답변"
            history_lines.append(f"{role_label}: {turn.get('text', '')}")
        if history_lines:
            history_text = "\n[이전 대화 맥락]\n" + "\n".join(history_lines) + "\n"

    prompt = f"""
[데이터셋 개요]
- 파일명: {filename}
- 전체 규모: {diagnosis.get('row_count')}행 × {diagnosis.get('column_count')}열
- 권장 기준연도: {diagnosis.get('recommended_reference_year')}

[현재 실행된 Pandas 통계 분석 결과]
{json.dumps(calc_summary, ensure_ascii=False, indent=2)}
{history_text}
[사용자의 후속 질문]
"{user_question}"

위 사용자의 후속 질문에 대해 통계 초보자도 바로 이해할 수 있도록 쉽고 친절하게, 그리고 오직 확인된 데이터만을 근거로 정직하게 해설해 주세요.
"""

    logger.info(f"[AI] followup 요청 시작 (model={model_name})")

    try:
        client = genai.Client(api_key=api_key)
        response, used_model = call_gemini_resilient(
            client=client,
            primary_model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.3
            )
        )
        answer_text = response.text or ""
        logger.info(f"[AI] followup 응답 수신 (model={used_model})")
    except Exception as e:
        logger.error(f"[ERROR] Gemini API 호출 실패 (followup): {e}\n{traceback.format_exc()}")
        return jsonify({"success": False, "error": f"답변 생성 중 오류가 발생했습니다: {str(e)}"}), 500

    response_payload = {
        "success": True,
        "question": user_question,
        "answer": answer_text,
        "model": model_name
    }
    logger.info(f"[RESPONSE] status=200 followup question='{user_question[:20]}...'")
    return jsonify(response_payload)


if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() in ("true", "1", "t")
    port = int(os.getenv("PORT", 5000))
    logger.info(f"서버 시작 준비 - port={port}, debug={debug_mode}")
    app.run(host="127.0.0.1", port=port, debug=debug_mode)


