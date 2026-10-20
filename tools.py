"""
tools.py - AI Data Insight Builder 계산 및 분석 도구 모음

절대 규칙:
- 모든 숫자 계산은 Pandas가 직접 수행한다.
- 모든 도구는 다음 공통 메타데이터를 반드시 반환한다:
  - reference_period (기준 시점)
  - used_rows (사용한 행 수)
  - excluded_rows (제외한 행 수)
  - exclusion_reason (제외 이유)
  - used_columns (사용한 열)
  - unit (단위)
  - cautions (주의사항)
- 7~12번 도구는 기준 시점(reference_period)을 필수 파라미터로 받으며, 없으면 오류를 반환한다.
- 집계 행 제외 여부(exclude_aggregates)는 기본값 True(제외)이다.
- NaN과 Infinity는 JSON 직렬화가 가능하도록 안전하게 변환한다.
"""

import re
import json
import numpy as np
import pandas as pd


def sanitize_value(val):
    """NaN, Inf, -Inf 값을 JSON 호환 None으로 안전하게 변환"""
    if pd.isna(val) or val is None:
        return None
    if isinstance(val, (float, np.floating)):
        if np.isinf(val) or np.isnan(val):
            return None
        return float(val)
    if isinstance(val, (int, np.integer)):
        return int(val)
    return str(val)


def sanitize_dict_list(records):
    """딕셔너리 리스트 내의 모든 NaN/Inf를 None으로 안전 직렬화"""
    return json.loads(json.dumps(records, default=sanitize_value))


def filter_aggregates_helper(df, label_col=None, exclude=True):
    """
    World, OECD members, Area, Income 그룹 등 광역 집계 행 필터링 헬퍼 함수
    """
    if not exclude:
        return df, 0, []

    if label_col is None or label_col not in df.columns:
        cat_cols = [str(c) for c in df.select_dtypes(include=["object", "string", "category"]).columns]
        label_col = cat_cols[0] if cat_cols else str(df.columns[0])

    agg_keywords = [
        "world", "oecd members", "euro area", "european union",
        "high income", "low income", "middle income", "income", "area",
        "total", "aggregate", "latin america", "sub-saharan africa",
        "north america", "east asia", "south asia", "arab world"
    ]
    mask = df[label_col].astype(str).str.lower().apply(lambda s: any(k in s for k in agg_keywords))
    excluded_count = int(mask.sum())
    filtered_df = df[~mask].copy()
    return filtered_df, excluded_count, list(df[mask][label_col].astype(str))


COMMON_COUNTRY_ALIASES = {
    "한국": "Korea", "대한민국": "Korea", "남한": "Korea", "korea": "Korea",
    "북한": "Dem. People's", "north korea": "Dem. People's",
    "미국": "United States", "usa": "United States", "us": "United States",
    "중국": "China", "china": "China",
    "일본": "Japan", "japan": "Japan",
    "영국": "United Kingdom", "uk": "United Kingdom", "britain": "United Kingdom",
    "독일": "Germany", "germany": "Germany",
    "프랑스": "France", "france": "France",
    "러시아": "Russia", "russia": "Russia",
    "인도": "India", "india": "India",
    "브라질": "Brazil", "brazil": "Brazil",
    "캐나다": "Canada", "canada": "Canada",
    "호주": "Australia", "australia": "Australia",
    "베트남": "Viet Nam", "vietnam": "Viet Nam",
    "이탈리아": "Italy", "italy": "Italy",
    "스페인": "Spain", "spain": "Spain"
}


def find_matching_entity(df, label_col, item_name):
    """
    한글/영문 별칭, 대소문자 무시, 부분 문자열 일치 등을 종합하여
    데이터프레임의 label_col에서 가장 적합한 실제 라벨명 반환 (없으면 None)
    """
    if not item_name or label_col not in df.columns:
        return None
    name_str = str(item_name).strip()
    name_lower = name_str.lower()
    
    # 1. 완전 일치 (대소문자 무시)
    exact = df[df[label_col].astype(str).str.lower() == name_lower]
    if len(exact) > 0:
        return str(exact.iloc[0][label_col])
        
    # 2. 별칭 사전 매핑
    alias_term = COMMON_COUNTRY_ALIASES.get(name_lower)
    if not alias_term:
        for k, v in COMMON_COUNTRY_ALIASES.items():
            if k in name_lower:
                alias_term = v
                break
    if alias_term:
        alias_matches = df[df[label_col].astype(str).str.contains(alias_term, case=False, na=False)]
        if len(alias_matches) > 0:
            return str(alias_matches.iloc[0][label_col])
            
    # 3. 일반 부분 문자열 검색
    part = df[df[label_col].astype(str).str.contains(re.escape(name_str), case=False, na=False)]
    if len(part) > 0:
        return str(part.iloc[0][label_col])
        
    return None


# -----------------------------------------------------------------------------
# 도구 1: reshape_wide_to_long (연도 열을 행으로 접기 / Unpivot)
# -----------------------------------------------------------------------------
def reshape_wide_to_long(df, id_vars=None, year_columns=None, value_name="Value", var_name="Year"):
    """
    여러 연도 열(Wide 포맷)을 하나의 'Year' 열과 'Value' 열(Long 포맷)로 변환
    """
    df_copy = df.copy()
    
    # 연도 열 자동 탐색 (4자리 숫자)
    year_pattern = re.compile(r"^(19|20)\d{2}$")
    all_year_cols = [str(c) for c in df_copy.columns if year_pattern.match(str(c).strip())]
    
    if year_columns is None:
        selected_year_cols = all_year_cols
    else:
        selected_year_cols = [str(y) for y in year_columns if str(y) in df_copy.columns]

    if not selected_year_cols:
        return {
            "success": False,
            "error": "변환할 연도 열(1900~2099 형식)을 찾을 수 없습니다."
        }

    # id_vars 자동 탐색 (연도 열이 아닌 열들 중 Unnamed 제외)
    if id_vars is None:
        id_vars = [str(c) for c in df_copy.columns if str(c) not in selected_year_cols and not str(c).startswith("Unnamed:")]

    total_rows = len(df_copy)
    
    # Wide -> Long 변환
    melted = pd.melt(
        df_copy,
        id_vars=id_vars,
        value_vars=selected_year_cols,
        var_name=var_name,
        value_name=value_name
    )

    # 결측치 행 제외
    melted_clean = melted.dropna(subset=[value_name])
    excluded_cells = len(melted) - len(melted_clean)

    sample_preview = sanitize_dict_list(melted_clean.head(15).to_dict(orient="records"))

    return {
        "success": True,
        "tool": "reshape_wide_to_long",
        "title": "연도 열 행 변환 (Wide to Long)",
        "summary": f"{len(selected_year_cols)}개 연도 열을 행으로 재구조화하여 총 {len(melted_clean):,}개의 유효 관측치를 생성했습니다.",
        "data": {
            "sample_rows": sample_preview,
            "total_observations": int(len(melted_clean)),
            "year_range": f"{selected_year_cols[0]} ~ {selected_year_cols[-1]}",
            "id_columns": id_vars,
            "value_column": value_name
        },
        "reference_period": f"{selected_year_cols[0]} - {selected_year_cols[-1]}",
        "used_rows": int(len(melted_clean)),
        "excluded_rows": int(excluded_cells),
        "exclusion_reason": f"해당 연도에 값이 존재하지 않는 결측 셀({excluded_cells:,}건)을 제외했습니다.",
        "used_columns": id_vars + selected_year_cols,
        "unit": "행 (관측치)",
        "cautions": "연도별 결측치가 많은 항목은 변환 후 연도별 관측치 수에 편차가 있을 수 있습니다."
    }


# -----------------------------------------------------------------------------
# 도구 2: quality_report (결측·중복·타입·이상한 열 이름 품질 보고서)
# -----------------------------------------------------------------------------
def quality_report(df):
    """
    데이터셋 전반의 결측치, 중복 행, 데이터 타입, Unnamed 열 등을 체계적으로 감사한 품질 보고서 반환
    """
    total_rows = len(df)
    total_cols = len(df.columns)
    dup_rows = int(df.duplicated().sum())

    report_list = []
    unnamed_cols = []
    high_missing_cols = []

    for col in df.columns:
        col_str = str(col)
        na_count = int(df[col].isna().sum())
        na_ratio = round(float(na_count / total_rows * 100), 2) if total_rows > 0 else 0.0
        unique_cnt = int(df[col].nunique(dropna=True))
        dtype_str = str(df[col].dtype)

        is_unnamed = col_str.startswith("Unnamed:") or not col_str.strip()
        if is_unnamed:
            unnamed_cols.append(col_str)
        if na_ratio >= 80.0:
            high_missing_cols.append(col_str)

        report_list.append({
            "column": col_str,
            "dtype": dtype_str,
            "missing_count": na_count,
            "missing_ratio_pct": na_ratio,
            "unique_count": unique_cnt,
            "is_unnamed": is_unnamed
        })

    return {
        "success": True,
        "tool": "quality_report",
        "title": "데이터 품질 감사 보고서",
        "summary": f"총 {total_rows:,}행 × {total_cols:,}열 데이터셋 검사 결과, 중복 행 {dup_rows}건, Unnamed 열 {len(unnamed_cols)}건, 고결측 열(80% 이상) {len(high_missing_cols)}건이 발견되었습니다.",
        "data": {
            "total_rows": total_rows,
            "total_columns": total_cols,
            "duplicate_rows": dup_rows,
            "columns_quality": sanitize_dict_list(report_list),
            "unnamed_columns": unnamed_cols,
            "high_missing_columns": high_missing_cols
        },
        "reference_period": "전체 수록 기간",
        "used_rows": total_rows,
        "excluded_rows": 0,
        "exclusion_reason": "품질 감사를 위해 전체 행을 검사하였으므로 제외된 행이 없습니다.",
        "used_columns": [str(c) for c in df.columns],
        "unit": "건 / 비율(%)",
        "cautions": "결측 비율이 지나치게 높은 열은 특정 연도나 특정 국가에만 선택적으로 수집된 지표일 수 있으므로 분석 전 필터링이 필요합니다."
    }


# -----------------------------------------------------------------------------
# 도구 3: year_coverage (연도별 값 개수와 권장 기준연도)
# -----------------------------------------------------------------------------
def year_coverage(df):
    """
    각 연도 열별 비결측 데이터 충실도 계산 및 시계열 분석을 위한 최적의 기준연도 도출
    """
    year_pattern = re.compile(r"^(19|20)\d{2}$")
    year_cols = [str(c) for c in df.columns if year_pattern.match(str(c).strip())]

    if not year_cols:
        return {
            "success": False,
            "error": "데이터셋에서 4자리 연도 열(1900~2099)을 찾을 수 없습니다."
        }

    total_rows = len(df)
    coverage_records = []
    counts_dict = {}

    for y in year_cols:
        cnt = int(df[y].notna().sum())
        ratio = round(float(cnt / total_rows * 100), 2) if total_rows > 0 else 0.0
        counts_dict[y] = cnt
        coverage_records.append({
            "year": y,
            "valid_count": cnt,
            "coverage_pct": ratio
        })

    # 권장 기준연도: 최근 연도 중 최대 충실도 대비 80% 이상 채워진 최근 연도
    max_count = max(counts_dict.values()) if counts_dict else 0
    sorted_years = sorted(year_cols, key=lambda x: int(x), reverse=True)
    recommended_year = None
    
    if max_count > 0:
        for y in sorted_years:
            if counts_dict[y] >= max_count * 0.8:
                recommended_year = y
                break
        if not recommended_year:
            recommended_year = max(counts_dict.items(), key=lambda item: item[1])[0]
    else:
        recommended_year = sorted_years[0]

    # Chart.js 차트 데이터 구성
    chart_data = {
        "type": "bar",
        "labels": [r["year"] for r in coverage_records],
        "datasets": [{
            "label": "유효 데이터 개수",
            "data": [r["valid_count"] for r in coverage_records],
            "backgroundColor": "#3b82f6"
        }]
    }

    return {
        "success": True,
        "tool": "year_coverage",
        "title": "연도별 데이터 충실도 분석",
        "summary": f"수집된 {len(year_cols)}개 연도 중 가장 데이터가 충실한 최신 권장 기준연도는 '{recommended_year}' (유효 데이터 {counts_dict.get(recommended_year, 0):,}개)입니다.",
        "data": {
            "coverage_table": sanitize_dict_list(coverage_records),
            "recommended_reference_year": recommended_year,
            "max_coverage_year": max(counts_dict.items(), key=lambda item: item[1])[0],
            "chart": chart_data
        },
        "reference_period": f"{year_cols[0]} - {year_cols[-1]}",
        "used_rows": total_rows,
        "excluded_rows": 0,
        "exclusion_reason": "전체 연도 커버리지 산출을 위해 전수 조사하였으므로 제외된 행이 없습니다.",
        "used_columns": year_cols,
        "unit": "개 (항목 수)",
        "cautions": "가장 최근 1~2개 연도는 집계가 아직 완료되지 않아 급격히 데이터가 줄어들 수 있으므로 권장 기준연도를 사용하는 것이 안전합니다."
    }


# -----------------------------------------------------------------------------
# 도구 4: detect_aggregates (집계 행 후보 탐지 및 필터링)
# -----------------------------------------------------------------------------
def detect_aggregates(df, label_column=None):
    """
    World, OECD members, Income 그룹, 지역 연합 등 개별 개체가 아닌 요약·집계 행을 탐지
    """
    if label_column is None or label_column not in df.columns:
        cat_cols = [str(c) for c in df.select_dtypes(include=["object", "string", "category"]).columns]
        label_column = cat_cols[0] if cat_cols else str(df.columns[0])

    detected = []
    total_rows = len(df)
    _, agg_count, agg_names = filter_aggregates_helper(df, label_col=label_column, exclude=True)
    individual_count = total_rows - agg_count

    return {
        "success": True,
        "tool": "detect_aggregates",
        "title": "집계 및 요약 행 후보 탐지",
        "summary": f"총 {total_rows:,}개 항목 중 {agg_count}개의 광역 지역/소득 그룹 집계 행을 감지했습니다. 순수 개별 항목은 {individual_count:,}개입니다.",
        "data": {
            "aggregate_count": agg_count,
            "individual_count": individual_count,
            "detected_aggregates": agg_names[:30],
            "label_column": label_column
        },
        "reference_period": "전체 데이터",
        "used_rows": total_rows,
        "excluded_rows": agg_count,
        "exclusion_reason": f"순수 개별 국가/개체 분석 시 중복 합산 왜곡을 유발하는 집계 행 {agg_count}개를 탐지 및 분류했습니다.",
        "used_columns": [label_column],
        "unit": "개 (항목 수)",
        "cautions": "집계 행(World, High income 등)과 개별 국가를 동일한 순위 차트에 함께 배치하면 중복 집계로 인해 심각한 통계 왜곡이 발생합니다."
    }


# -----------------------------------------------------------------------------
# 도구 5: describe_numeric (개수·평균·중앙값·최소·최대·표준편차 기술통계)
# -----------------------------------------------------------------------------
def describe_numeric(df, target_column=None, reference_period=None, exclude_aggregates=True, label_column=None):
    """
    지정된 숫자 열(또는 기준연도 열)의 핵심 요약 통계량 산출 (개수, 평균, 중앙값, 표준편차, 4분위수)
    """
    if target_column is None and reference_period is not None:
        target_column = str(reference_period)

    if target_column is None or target_column not in df.columns:
        year_pattern = re.compile(r"^(19|20)\d{2}$")
        year_cols = [str(c) for c in df.columns if year_pattern.match(str(c).strip())]
        if year_cols:
            target_column = year_cols[-1]
        else:
            num_cols = [str(c) for c in df.select_dtypes(include=["number"]).columns]
            if num_cols:
                target_column = num_cols[0]
            else:
                return {"success": False, "error": "분석할 숫자형 열을 찾을 수 없습니다."}

    ref_period = str(reference_period) if reference_period else (target_column if re.match(r"^(19|20)\d{2}$", target_column) else "전체 기간")

    # 집계 행 제외
    clean_df, agg_excluded, _ = filter_aggregates_helper(df, label_col=label_column, exclude=exclude_aggregates)

    series = pd.to_numeric(clean_df[target_column], errors="coerce").dropna()
    na_excluded = len(clean_df) - len(series)
    total_excluded = agg_excluded + na_excluded

    if len(series) == 0:
        return {"success": False, "error": f"선택한 열 '{target_column}'에 유효한 숫자 데이터가 없습니다."}

    stats = {
        "count": int(series.count()),
        "mean": round(float(series.mean()), 4),
        "median": round(float(series.median()), 4),
        "std": round(float(series.std()), 4) if len(series) > 1 else 0.0,
        "min": round(float(series.min()), 4),
        "q25": round(float(series.quantile(0.25)), 4),
        "q75": round(float(series.quantile(0.75)), 4),
        "max": round(float(series.max()), 4)
    }

    reason_parts = []
    if agg_excluded > 0:
        reason_parts.append(f"집계 행 {agg_excluded}개")
    if na_excluded > 0:
        reason_parts.append(f"결측치 {na_excluded}개")
    reason_str = ", ".join(reason_parts) + "를 제외했습니다." if reason_parts else "제외된 행이 없습니다."

    return {
        "success": True,
        "tool": "describe_numeric",
        "title": f"'{target_column}' 기초 기술통계 분석",
        "summary": f"'{target_column}' 지표의 평균은 {stats['mean']:,}, 중앙값은 {stats['median']:,} (최솟값: {stats['min']:,}, 최댓값: {stats['max']:,})이며, 총 {stats['count']:,}개 개체가 집계되었습니다.",
        "data": {
            "target_column": target_column,
            "statistics": stats
        },
        "reference_period": ref_period,
        "used_rows": int(len(series)),
        "excluded_rows": total_excluded,
        "exclusion_reason": reason_str,
        "used_columns": [target_column],
        "unit": "수치 (원 지표 단위)",
        "cautions": "평균값과 중앙값의 차이가 클 경우, 소수의 극단값에 의한 왜곡이 발생하므로 중앙값을 함께 고려해야 합니다."
    }


# -----------------------------------------------------------------------------
# 도구 6: trend_line (선택 항목들의 연도별 추이 선 차트)
# -----------------------------------------------------------------------------
def trend_line(df, items=None, label_column=None, year_columns=None, exclude_aggregates=True, **kwargs):
    """
    선택된 개체(국가 등)의 연도별 시계열 변화 추이를 선 차트(Line Chart) 데이터로 추출
    """
    if label_column is None or label_column not in df.columns:
        cat_cols = [str(c) for c in df.select_dtypes(include=["object", "string", "category"]).columns]
        label_column = cat_cols[0] if cat_cols else str(df.columns[0])

    year_pattern = re.compile(r"^(19|20)\d{2}$")
    if year_columns is None:
        year_columns = [str(c) for c in df.columns if year_pattern.match(str(c).strip())]

    if not year_columns:
        return {"success": False, "error": "시계열 추이를 도출할 4자리 연도 열을 찾을 수 없습니다."}

    resolved_items = []
    if items:
        if isinstance(items, str):
            items = [items]
        for it in items:
            matched = find_matching_entity(df, label_column, it)
            if matched and matched not in resolved_items:
                resolved_items.append(matched)

    fallback_notice = ""
    if not resolved_items:
        # 매칭 실패 시: 한국, 미국 등 대표 국가 우선 탐색 후 없으면 상위 4개 선택
        for candidate in ["Korea, Rep.", "United States", "Japan", "Germany", "United Kingdom"]:
            matched = find_matching_entity(df, label_column, candidate)
            if matched and matched not in resolved_items:
                resolved_items.append(matched)
            if len(resolved_items) >= 4:
                break
        if not resolved_items:
            clean_temp, _, _ = filter_aggregates_helper(df, label_col=label_column)
            resolved_items = list(clean_temp[label_column].dropna().head(4).astype(str))
        if items:
            fallback_notice = f" (주의: 요청하신 항목 {items}을(를) 찾지 못해 대표 비교군 {resolved_items}의 추이를 대신 표시합니다.)"

    sub_df = df[df[label_column].astype(str).isin(resolved_items)].copy()
    if len(sub_df) == 0:
        return {"success": False, "error": f"비교할 유효한 개체를 데이터셋에서 찾지 못했습니다."}

    colors = ["#2563eb", "#dc2626", "#16a34a", "#ea580c", "#9333ea", "#0891b2", "#ca8a04"]
    datasets = []
    series_table = []

    for idx, (_, row) in enumerate(sub_df.iterrows()):
        item_name = str(row[label_column])
        color = colors[idx % len(colors)]
        row_vals = []
        for y in year_columns:
            val = row.get(y)
            num_val = None
            if pd.notna(val):
                try:
                    num_val = round(float(val), 2)
                except ValueError:
                    num_val = None
            row_vals.append(num_val)

        datasets.append({
            "label": item_name,
            "data": row_vals,
            "borderColor": color,
            "backgroundColor": color,
            "fill": False,
            "tension": 0.2
        })
        series_table.append({
            "item": item_name,
            "values": {y: row_vals[i] for i, y in enumerate(year_columns)}
        })

    chart_data = {
        "type": "line",
        "labels": year_columns,
        "datasets": datasets
    }

    ref_period = f"{year_columns[0]} - {year_columns[-1]}"
    used_rows = len(sub_df)
    excluded_rows = len(df) - used_rows

    return {
        "success": True,
        "tool": "trend_line",
        "title": "선택 항목 연도별 시계열 추이 (선 차트)",
        "summary": f"{ref_period} 기간 동안 {len(items)}개 항목({', '.join(items[:3])} 등)의 연도별 변화 추이를 도출했습니다.",
        "data": {
            "selected_items": items,
            "chart": chart_data,
            "series_table": sanitize_dict_list(series_table)
        },
        "reference_period": ref_period,
        "used_rows": used_rows,
        "excluded_rows": excluded_rows,
        "exclusion_reason": f"비교 대상으로 선택되지 않은 나머지 {excluded_rows:,}개 항목을 제외했습니다.",
        "used_columns": [label_column] + year_columns,
        "unit": "수치 (원 지표 단위)",
        "cautions": "특정 연도에 결측치가 포함된 항목은 시계열 선 차트에서 불연속이 발생할 수 있습니다."
    }


# -----------------------------------------------------------------------------
# 도구 7: top_bottom_n (기준연도 필수!)
# -----------------------------------------------------------------------------
def top_bottom_n(df, reference_period=None, n=10, mode="top", label_column=None, exclude_aggregates=True, include_item=None):
    """
    기준 시점(reference_period) 기준 상위 또는 하위 N개 항목을 추출하여 수평 막대 차트 데이터 구성
    (include_item 지정 시 특정 개체(예: 대한민국)를 함께 나란히 비교 하이라이트)
    """
    if not reference_period:
        return {"success": False, "error": "top_bottom_n 도구는 'reference_period'(기준 시점 연도)가 필수입니다."}

    ref_col = str(reference_period)
    year_notice = ""
    year_pattern = re.compile(r"^(19|20)\d{2}$")
    valid_year_cols = [str(c) for c in df.columns if year_pattern.match(str(c).strip())]

    if ref_col not in df.columns:
        if valid_year_cols:
            best_year = max(valid_year_cols, key=lambda y: df[y].notna().sum())
            year_notice = f" (주의: '{ref_col}년' 열이 없어 충실도가 가장 높은 '{best_year}년'으로 자동 대체되었습니다.)"
            ref_col = best_year
        else:
            return {"success": False, "error": f"데이터셋에 기준 시점 열 '{ref_col}'이(가) 존재하지 않습니다."}

    if label_column is None or label_column not in df.columns:
        cat_cols = [str(c) for c in df.select_dtypes(include=["object", "string", "category"]).columns]
        label_column = cat_cols[0] if cat_cols else str(df.columns[0])

    n = int(n)
    total_rows = len(df)

    # 1) 집계 행 제외
    clean_df, agg_excluded, _ = filter_aggregates_helper(df, label_col=label_column, exclude=exclude_aggregates)

    # 2) 기준 시점 결측치 제외
    clean_df[ref_col] = pd.to_numeric(clean_df[ref_col], errors="coerce")
    valid_df = clean_df.dropna(subset=[ref_col])
    na_excluded = len(clean_df) - len(valid_df)
    total_excluded = agg_excluded + na_excluded

    if len(valid_df) == 0:
        if valid_year_cols:
            best_year = max(valid_year_cols, key=lambda y: df[y].notna().sum())
            if df[best_year].notna().sum() > 0:
                year_notice = f" (주의: '{ref_col}년'은 유효 데이터가 없어 '{best_year}년'으로 자동 대체되었습니다.)"
                ref_col = best_year
                clean_df[ref_col] = pd.to_numeric(clean_df[ref_col], errors="coerce")
                valid_df = clean_df.dropna(subset=[ref_col])
        if len(valid_df) == 0:
            return {"success": False, "error": f"기준 시점 '{ref_col}'에 유효한 값이 있는 행이 없습니다."}

    sorted_df = valid_df.sort_values(by=ref_col, ascending=False)

    if mode == "bottom":
        target_records = sorted_df.tail(n).iloc[::-1]
        chart_title = f"{ref_col}년 하위 {len(target_records)}개 항목"
        bar_color = "#ef4444"
    elif mode == "both":
        half = max(1, n // 2)
        top_half = sorted_df.head(half)
        bot_half = sorted_df.tail(half)
        target_records = pd.concat([top_half, bot_half])
        chart_title = f"{ref_col}년 상위·하위 항목 비교"
        bar_color = "#3b82f6"
    else:  # top
        target_records = sorted_df.head(n)
        chart_title = f"{ref_col}년 상위 {len(target_records)}개 항목"
        bar_color = "#2563eb"

    labels = list(target_records[label_column].astype(str))
    values = [round(float(v), 2) for v in target_records[ref_col]]
    bar_colors = [bar_color] * len(labels)

    table_data = [
        {"rank": i + 1, "label": labels[i], "value": values[i]}
        for i in range(len(labels))
    ]

    # 특정 개체 추가 비교 (예: 한국/대한민국 포함 요청 시)
    summary_extra = ""
    entity_notice = ""
    if include_item:
        matched_label = find_matching_entity(valid_df, label_column, include_item)
        if matched_label:
            inc_row = valid_df[valid_df[label_column] == matched_label].iloc[0]
            inc_label = str(inc_row[label_column])
            inc_val = round(float(inc_row[ref_col]), 2)
            inc_rank = int((sorted_df[ref_col] > inc_val).sum() + 1)

            if inc_label not in labels:
                labels.append(f"{inc_label} (비교 대상)")
                values.append(inc_val)
                bar_colors.append("#ea580c")  # 눈에 띄는 주황색 하이라이트
                table_data.append({"rank": inc_rank, "label": f"{inc_label} (비교 대상)", "value": inc_val})
                chart_title = f"{chart_title} & {inc_label} 비교"
                summary_extra = f" 함께 비교한 '{inc_label}'는 {inc_val:,}로 전체 {inc_rank}위(상위 {round(inc_rank / len(valid_df) * 100, 1)}%)입니다."
            else:
                idx = labels.index(inc_label)
                bar_colors[idx] = "#ea580c"
                summary_extra = f" 비교 대상인 '{inc_label}'는 상위 {idx + 1}위에 이미 포함되어 있습니다."
        else:
            entity_notice = f" (주의: 요청하신 개체 '{include_item}'은(는) 데이터셋에 존재하지 않아 상위 {len(labels)}개국 순위만 비교했습니다.)"

    chart_data = {
        "type": "bar",
        "indexAxis": "y",
        "labels": labels,
        "datasets": [{
            "label": f"{ref_col}년 값",
            "data": values,
            "backgroundColor": bar_colors
        }]
    }

    extra_caution = f"{year_notice} {entity_notice}".strip()
    full_cautions = "비율(%) 지표인지 인구/경제 규모에 비례하는 총량 지표인지 구분하여 해석해야 합니다."
    if extra_caution:
        full_cautions += f" {extra_caution}"

    main_summary = f"기준연도 {ref_col}년 기준, 유효 개체 {len(valid_df):,}개 중 1위는 '{labels[0]}' ({values[0]:,})입니다.{summary_extra}"
    if extra_caution:
        main_summary += f" {extra_caution}"

    return {
        "success": True,
        "tool": "top_bottom_n",
        "title": chart_title,
        "summary": main_summary,
        "data": {
            "mode": mode,
            "n": n,
            "chart": chart_data,
            "table": sanitize_dict_list(table_data),
            "total_valid_population": len(valid_df)
        },
        "reference_period": str(reference_period),
        "used_rows": int(len(target_records)),
        "excluded_rows": int(total_rows - len(target_records)),
        "exclusion_reason": f"기준시점({ref_col}) 결측치 {na_excluded}건, 집계 행 {agg_excluded}건 및 상/하위 {n}개 범위 밖 행들을 제외했습니다.",
        "used_columns": [label_column, ref_col],
        "unit": "수치 (원 지표 단위)",
        "cautions": full_cautions
    }


# -----------------------------------------------------------------------------
# 도구 8: group_summary (그룹별 평균·합계·개수 막대, 기준연도 필수!)
# -----------------------------------------------------------------------------
def group_summary(df, reference_period=None, group_column=None, agg_func="mean", label_column=None, exclude_aggregates=True):
    """
    기준 시점(reference_period) 기준 그룹별(대륙, 소득분위 등) 요약 통계량 계산 및 막대 차트 생성
    (기준 시점 필수 입력 규칙 준수)
    """
    if not reference_period:
        return {"success": False, "error": "group_summary 도구는 'reference_period'(기준 시점 연도)가 필수입니다."}

    ref_col = str(reference_period)
    if ref_col not in df.columns:
        return {"success": False, "error": f"데이터셋에 기준 시점 열 '{ref_col}'이(가) 존재하지 않습니다."}

    total_rows = len(df)

    if group_column is None or group_column not in df.columns:
        cat_cols = [str(c) for c in df.select_dtypes(include=["object", "string", "category"]).columns]
        if len(cat_cols) > 1:
            group_column = cat_cols[1]
        elif len(cat_cols) == 1:
            group_column = cat_cols[0]
        else:
            return {"success": False, "error": "그룹화할 범주형 열(group_column)을 찾을 수 없습니다."}

    clean_df, agg_excluded, _ = filter_aggregates_helper(df, label_col=label_column, exclude=exclude_aggregates)

    clean_df[ref_col] = pd.to_numeric(clean_df[ref_col], errors="coerce")
    valid_df = clean_df.dropna(subset=[ref_col, group_column])
    na_excluded = len(clean_df) - len(valid_df)
    total_excluded = agg_excluded + na_excluded

    if len(valid_df) == 0:
        return {"success": False, "error": f"기준 시점 '{ref_col}'과 그룹 열 '{group_column}'에 유효한 데이터가 없습니다."}

    if agg_func == "sum":
        grouped = valid_df.groupby(group_column)[ref_col].sum()
        agg_name = "합계"
    elif agg_func == "count":
        grouped = valid_df.groupby(group_column)[ref_col].count()
        agg_name = "개수"
    else:
        grouped = valid_df.groupby(group_column)[ref_col].mean()
        agg_name = "평균"

    grouped = grouped.sort_values(ascending=False).head(15)
    labels = list(grouped.index.astype(str))
    values = [round(float(v), 2) for v in grouped.values]

    chart_data = {
        "type": "bar",
        "labels": labels,
        "datasets": [{
            "label": f"{ref_col}년 {group_column}별 {agg_name}",
            "data": values,
            "backgroundColor": "#0d9488"
        }]
    }

    table_data = [
        {"group": labels[i], "value": values[i], "stat": agg_name}
        for i in range(len(labels))
    ]

    return {
        "success": True,
        "tool": "group_summary",
        "title": f"{ref_col}년 '{group_column}' 그룹별 {agg_name} 분석",
        "summary": f"{ref_col}년 기준 {len(labels)}개 그룹 중 '{labels[0]}'의 {agg_name}이 {values[0]:,}로 가장 높았습니다.",
        "data": {
            "group_column": group_column,
            "agg_func": agg_func,
            "chart": chart_data,
            "table": sanitize_dict_list(table_data)
        },
        "reference_period": str(reference_period),
        "used_rows": int(len(valid_df)),
        "excluded_rows": int(total_excluded),
        "exclusion_reason": f"기준 시점({ref_col}) 결측치 {na_excluded}건 및 집계 행 {agg_excluded}건을 제외했습니다.",
        "used_columns": [group_column, ref_col],
        "unit": f"수치 ({agg_name})",
        "cautions": "그룹별로 포함된 샘플 수에 편차가 크면 평균이나 합계의 대표성이 왜곡될 수 있습니다."
    }

# -----------------------------------------------------------------------------
# 도구 9: change_rate (두 시점 사이 변화량·변화율 막대, 기준연도 필수!)
# -----------------------------------------------------------------------------
def change_rate(df, reference_period=None, base_period=None, n=10, label_column=None, exclude_aggregates=True):
    """
    두 시점(base_period -> reference_period) 사이의 변화량 및 변화율을 계산하여 상위 증가 항목 추출
    (기준 시점 필수 입력 규칙 준수)
    """
    if not reference_period:
        return {"success": False, "error": "change_rate 도구는 'reference_period'(종료 기준 연도)가 필수입니다."}

    ref_col = str(reference_period)
    if ref_col not in df.columns:
        return {"success": False, "error": f"데이터셋에 기준 시점 열 '{ref_col}'이(가) 존재하지 않습니다."}

    # base_period 자동 결정 (미지정 시 ref_col보다 앞선 유효 연도 중 5~10년 전)
    year_pattern = re.compile(r"^(19|20)\d{2}$")
    year_cols = sorted([str(c) for c in df.columns if year_pattern.match(str(c).strip())], key=lambda x: int(x))

    if not base_period:
        if ref_col in year_cols:
            ref_idx = year_cols.index(ref_col)
            # 5년 전 또는 10년 전 시도
            target_prev_idx = max(0, ref_idx - 5)
            base_period = year_cols[target_prev_idx]
            if base_period == ref_col and len(year_cols) > 1:
                base_period = year_cols[0]
        else:
            return {"success": False, "error": "비교할 시작 시점(base_period)을 지정해 주세요."}

    base_col = str(base_period)
    if base_col not in df.columns:
        return {"success": False, "error": f"데이터셋에 시작 시점 열 '{base_col}'이(가) 존재하지 않습니다."}

    if label_column is None or label_column not in df.columns:
        cat_cols = [str(c) for c in df.select_dtypes(include=["object", "string", "category"]).columns]
        label_column = cat_cols[0] if cat_cols else str(df.columns[0])

    n = int(n)
    total_rows = len(df)

    clean_df, agg_excluded, _ = filter_aggregates_helper(df, label_col=label_column, exclude=exclude_aggregates)

    clean_df[ref_col] = pd.to_numeric(clean_df[ref_col], errors="coerce")
    clean_df[base_col] = pd.to_numeric(clean_df[base_col], errors="coerce")

    # 두 시점 모두 유효한 행만 분석
    valid_df = clean_df.dropna(subset=[ref_col, base_col]).copy()
    na_excluded = len(clean_df) - len(valid_df)
    total_excluded = agg_excluded + na_excluded

    if len(valid_df) == 0:
        return {"success": False, "error": f"두 시점({base_col}, {ref_col}) 모두에 유효한 데이터가 있는 행이 없습니다."}

    # 변화량(diff) 및 변화율(pct_change) 계산
    valid_df["diff"] = valid_df[ref_col] - valid_df[base_col]
    # base가 0이 아닌 경우 변화율 계산
    valid_df["pct_change"] = np.where(
        valid_df[base_col] != 0,
        (valid_df["diff"] / valid_df[base_col].abs()) * 100,
        np.nan
    )

    top_increase = valid_df.sort_values(by="diff", ascending=False).head(n)

    labels = list(top_increase[label_column].astype(str))
    diff_values = [round(float(v), 2) for v in top_increase["diff"]]
    pct_values = [round(float(v), 2) if pd.notna(v) else None for v in top_increase["pct_change"]]

    chart_data = {
        "type": "bar",
        "indexAxis": "y",
        "labels": labels,
        "datasets": [{
            "label": f"변화량 ({base_col} → {ref_col})",
            "data": diff_values,
            "backgroundColor": "#10b981"
        }]
    }

    table_data = []
    for i in range(len(labels)):
        table_data.append({
            "label": labels[i],
            "base_val": round(float(top_increase.iloc[i][base_col]), 2),
            "ref_val": round(float(top_increase.iloc[i][ref_col]), 2),
            "diff": diff_values[i],
            "pct_change": pct_values[i]
        })

    ref_period_str = f"{base_col} - {ref_col}"

    return {
        "success": True,
        "tool": "change_rate",
        "title": f"{base_col}년 대비 {ref_col}년 변화량 상위 {len(labels)}개 항목",
        "summary": f"{base_col}년 대비 {ref_col}년 사이 가장 큰 수치 증가를 기록한 항목은 '{labels[0]}' (+{diff_values[0]:,})입니다.",
        "data": {
            "base_period": base_col,
            "reference_period": ref_col,
            "chart": chart_data,
            "table": sanitize_dict_list(table_data),
            "total_valid_population": len(valid_df)
        },
        "reference_period": ref_period_str,
        "used_rows": int(len(valid_df)),
        "excluded_rows": int(total_excluded),
        "exclusion_reason": f"두 시점 중 하나라도 결측치인 행 {na_excluded}건 및 집계 행 {agg_excluded}건을 제외했습니다.",
        "used_columns": [label_column, base_col, ref_col],
        "unit": "수치 (원 지표 단위 변화량)",
        "cautions": "초기값(기준 시점)이 매우 작았던 항목은 작은 절대적 변화량에도 변화율(%)이 비정상적으로 높게 나타날 수 있습니다."
    }


# -----------------------------------------------------------------------------
# 도구 10: distribution (구간별 분포 히스토그램, 기준연도 필수!)
# -----------------------------------------------------------------------------
def distribution(df, reference_period=None, bins=10, label_column=None, exclude_aggregates=True):
    """
    기준 시점(reference_period)의 수치 분포를 구간화(Histogram)하여 집중 구간과 왜도 분석
    (기준 시점 필수 입력 규칙 준수)
    """
    if not reference_period:
        return {"success": False, "error": "distribution 도구는 'reference_period'(기준 시점 연도)가 필수입니다."}

    ref_col = str(reference_period)
    if ref_col not in df.columns:
        return {"success": False, "error": f"데이터셋에 기준 시점 열 '{ref_col}'이(가) 존재하지 않습니다."}

    total_rows = len(df)
    clean_df, agg_excluded, _ = filter_aggregates_helper(df, label_col=label_column, exclude=exclude_aggregates)

    series = pd.to_numeric(clean_df[ref_col], errors="coerce").dropna()
    na_excluded = len(clean_df) - len(series)
    total_excluded = agg_excluded + na_excluded

    if len(series) == 0:
        return {"success": False, "error": f"기준 시점 '{ref_col}'에 유효한 숫자 데이터가 없습니다."}

    bins = int(bins)
    counts, bin_edges = np.histogram(series, bins=bins)

    bin_labels = []
    hist_table = []
    for i in range(len(counts)):
        b_label = f"{round(float(bin_edges[i]), 1)} ~ {round(float(bin_edges[i+1]), 1)}"
        bin_labels.append(b_label)
        hist_table.append({
            "bin": b_label,
            "count": int(counts[i]),
            "ratio_pct": round(float(counts[i] / len(series) * 100), 2)
        })

    chart_data = {
        "type": "bar",
        "labels": bin_labels,
        "datasets": [{
            "label": f"{ref_col}년 데이터 분포 (개수)",
            "data": [int(c) for c in counts],
            "backgroundColor": "#6366f1"
        }]
    }

    skewness = round(float(series.skew()), 4) if len(series) > 2 else 0.0
    skew_desc = "오른쪽으로 긴 꼬리(저수치 집중)" if skewness > 0.5 else ("왼쪽으로 긴 꼬리(고수치 집중)" if skewness < -0.5 else "대칭적인 정규분포에 근접")
    max_bin_idx = int(np.argmax(counts))

    return {
        "success": True,
        "tool": "distribution",
        "title": f"{ref_col}년 데이터 구간별 분포 (히스토그램)",
        "summary": f"{ref_col}년 데이터는 '{bin_labels[max_bin_idx]}' 구간에 가장 많은 {counts[max_bin_idx]}개 항목({hist_table[max_bin_idx]['ratio_pct']}%)이 밀집해 있으며, 왜도는 {skewness} ({skew_desc})입니다.",
        "data": {
            "bins": bins,
            "chart": chart_data,
            "table": sanitize_dict_list(hist_table),
            "skewness": skewness,
            "skew_description": skew_desc,
            "total_analyzed": len(series)
        },
        "reference_period": str(reference_period),
        "used_rows": int(len(series)),
        "excluded_rows": int(total_excluded),
        "exclusion_reason": f"기준 시점({ref_col}) 결측치 {na_excluded}건 및 집계 행 {agg_excluded}건을 제외했습니다.",
        "used_columns": [ref_col],
        "unit": "개 (항목 빈도수)",
        "cautions": "구간 수(bins) 설정에 따라 시각적 분포 형태가 달라질 수 있으므로 이상치 존재 여부를 함께 확인해야 합니다."
    }


# -----------------------------------------------------------------------------
# 도구 11: correlation_scatter (두 숫자 열 상관계수 산점도, 인과관계 주의 문구 필수!)
# -----------------------------------------------------------------------------
def correlation_scatter(df, reference_period=None, compare_period=None, col1=None, col2=None, label_column=None, exclude_aggregates=True):
    """
    두 시점 또는 두 수치 열 간의 피어슨 상관계수 산출 및 산점도(Scatter Chart) 생성
    (기준 시점 필수 입력 및 '상관관계는 인과관계가 아니다' 절대 주의사항 포함)
    """
    if not reference_period and not col2:
        return {"success": False, "error": "correlation_scatter 도구는 'reference_period'(기준 시점 연도)가 필수입니다."}

    # col1, col2 결정
    if not col2:
        col2 = str(reference_period)
    if not col1:
        if compare_period:
            col1 = str(compare_period)
        else:
            # 연도 열 목록 중 col2 이전의 가장 가까운 5~10년 전 연도 자동 탐색
            year_pattern = re.compile(r"^(19|20)\d{2}$")
            year_cols = sorted([str(c) for c in df.columns if year_pattern.match(str(c).strip())], key=lambda x: int(x))
            if col2 in year_cols:
                idx = year_cols.index(col2)
                prev_idx = max(0, idx - 10)
                col1 = year_cols[prev_idx]
            else:
                num_cols = [str(c) for c in df.select_dtypes(include=["number"]).columns if str(c) != col2]
                if num_cols:
                    col1 = num_cols[0]
                else:
                    return {"success": False, "error": "비교할 첫 번째 숫자 열(col1)을 찾을 수 없습니다."}

    if col1 not in df.columns or col2 not in df.columns:
        return {"success": False, "error": f"데이터셋에 지정된 열('{col1}', '{col2}')이 존재하지 않습니다."}

    if label_column is None or label_column not in df.columns:
        cat_cols = [str(c) for c in df.select_dtypes(include=["object", "string", "category"]).columns]
        label_column = cat_cols[0] if cat_cols else str(df.columns[0])

    total_rows = len(df)
    clean_df, agg_excluded, _ = filter_aggregates_helper(df, label_col=label_column, exclude=exclude_aggregates)

    clean_df[col1] = pd.to_numeric(clean_df[col1], errors="coerce")
    clean_df[col2] = pd.to_numeric(clean_df[col2], errors="coerce")

    valid_df = clean_df.dropna(subset=[col1, col2]).copy()
    na_excluded = len(clean_df) - len(valid_df)
    total_excluded = agg_excluded + na_excluded

    if len(valid_df) < 3:
        return {"success": False, "error": f"상관계수를 계산하기 위한 유효 데이터 쌍이 부족합니다 (최소 3개 이상 필요)."}

    # 피어슨 상관계수
    corr_coef = round(float(valid_df[col1].corr(valid_df[col2])), 4)

    # 상관 강도 해석
    abs_corr = abs(corr_coef)
    if abs_corr >= 0.7:
        strength = "매우 강한 양의 상관관계" if corr_coef > 0 else "매우 강한 음의 상관관계"
    elif abs_corr >= 0.4:
        strength = "유의미한 양의 상관관계" if corr_coef > 0 else "유의미한 음의 상관관계"
    elif abs_corr >= 0.2:
        strength = "약한 양의 상관관계" if corr_coef > 0 else "약한 음의 상관관계"
    else:
        strength = "상관관계가 거의 없음"

    scatter_points = []
    for _, row in valid_df.iterrows():
        scatter_points.append({
            "x": round(float(row[col1]), 2),
            "y": round(float(row[col2]), 2),
            "label": str(row[label_column])
        })

    chart_data = {
        "type": "scatter",
        "datasets": [{
            "label": f"{col1} vs {col2}",
            "data": scatter_points,
            "backgroundColor": "#8b5cf6"
        }]
    }

    ref_period_str = f"{col1} vs {col2}" if reference_period is None else str(reference_period)

    return {
        "success": True,
        "tool": "correlation_scatter",
        "title": f"'{col1}' vs '{col2}' 상관관계 및 산점도",
        "summary": f"두 지표 간 피어슨 상관계수는 r = {corr_coef} 로, {strength}를 보입니다 (유효 데이터 {len(valid_df):,}개 쌍).",
        "data": {
            "col1": col1,
            "col2": col2,
            "correlation_coefficient": corr_coef,
            "relationship_strength": strength,
            "chart": chart_data,
            "total_pairs": len(valid_df)
        },
        "reference_period": ref_period_str,
        "used_rows": int(len(valid_df)),
        "excluded_rows": int(total_excluded),
        "exclusion_reason": f"두 지표 중 하나라도 결측치인 행 {na_excluded}건 및 집계 행 {agg_excluded}건을 제외했습니다.",
        "used_columns": [label_column, col1, col2],
        "unit": "피어슨 상관계수 (r)",
        # [절대 규칙] 반드시 "상관관계는 인과관계가 아니다" 포함
        "cautions": "상관관계는 인과관계가 아닙니다 (Correlation does not imply causation). 두 변수 간에 높은 상관성이 관찰되더라도, 한 변수가 다른 변수의 직접적인 원인이라고 단정할 수 없으며 제3의 공통 변수(교란 변수)가 존재할 수 있습니다."
    }


# -----------------------------------------------------------------------------
# 도구 12: compare_one_vs_all (특정 항목 vs 전체 평균·중앙값 강조 막대, 기준연도 필수!)
# -----------------------------------------------------------------------------
def compare_one_vs_all(df, reference_period=None, target_item=None, label_column=None, exclude_aggregates=True):
    """
    특정 개체(예: 대한민국)의 지표 수치를 전체 집단의 평균 및 중앙값과 비교하고 백분위 순위 산출
    (기준 시점 필수 입력 규칙 준수)
    """
    if not reference_period:
        return {"success": False, "error": "compare_one_vs_all 도구는 'reference_period'(기준 시점 연도)가 필수입니다."}

    ref_col = str(reference_period)
    year_notice = ""
    year_pattern = re.compile(r"^(19|20)\d{2}$")
    valid_year_cols = [str(c) for c in df.columns if year_pattern.match(str(c).strip())]

    if ref_col not in df.columns:
        if valid_year_cols:
            best_year = max(valid_year_cols, key=lambda y: df[y].notna().sum())
            year_notice = f" (주의: '{ref_col}년' 열이 없어 충실도가 가장 높은 '{best_year}년'으로 자동 대체되었습니다.)"
            ref_col = best_year
        else:
            return {"success": False, "error": f"데이터셋에 기준 시점 열 '{ref_col}'이(가) 존재하지 않습니다."}

    if label_column is None or label_column not in df.columns:
        cat_cols = [str(c) for c in df.select_dtypes(include=["object", "string", "category"]).columns]
        label_column = cat_cols[0] if cat_cols else str(df.columns[0])

    total_rows = len(df)
    clean_df, agg_excluded, _ = filter_aggregates_helper(df, label_col=label_column, exclude=exclude_aggregates)

    clean_df[ref_col] = pd.to_numeric(clean_df[ref_col], errors="coerce")
    valid_df = clean_df.dropna(subset=[ref_col, label_column]).copy()
    na_excluded = len(clean_df) - len(valid_df)
    total_excluded = agg_excluded + na_excluded

    if len(valid_df) == 0:
        if valid_year_cols:
            best_year = max(valid_year_cols, key=lambda y: df[y].notna().sum())
            if df[best_year].notna().sum() > 0:
                year_notice = f" (주의: '{ref_col}년'은 데이터가 없어 '{best_year}년'으로 자동 대체되었습니다.)"
                ref_col = best_year
                clean_df[ref_col] = pd.to_numeric(clean_df[ref_col], errors="coerce")
                valid_df = clean_df.dropna(subset=[ref_col, label_column]).copy()
        if len(valid_df) == 0:
            return {"success": False, "error": f"기준 시점 '{ref_col}'에 유효한 데이터가 없습니다."}

    # target_item 지능형 매칭 및 fallback
    target_notice = ""
    orig_target = target_item
    matched_target = find_matching_entity(valid_df, label_column, target_item) if target_item else None

    if matched_target:
        target_item = matched_target
    else:
        korea_matches = valid_df[valid_df[label_column].astype(str).str.contains("Korea", case=False, na=False)]
        if len(korea_matches) > 0:
            target_item = str(korea_matches.iloc[0][label_column])
        else:
            target_item = str(valid_df.sort_values(by=ref_col, ascending=False).iloc[0][label_column])
        if orig_target:
            target_notice = f" (주의: 요청하신 '{orig_target}'을(를) 찾지 못해 대표 대상인 '{target_item}'을(를) 기준으로 비교했습니다.)"

    matched_row = valid_df[valid_df[label_column].astype(str) == str(target_item)]
    item_val = round(float(matched_row.iloc[0][ref_col]), 2)
    series = valid_df[ref_col]
    mean_val = round(float(series.mean()), 2)
    median_val = round(float(series.median()), 2)

    # 순위 및 백분위수
    rank = int((series > item_val).sum() + 1)
    percentile = round(float((series <= item_val).mean() * 100), 1)

    chart_data = {
        "type": "bar",
        "labels": [f"{target_item} (선택 대상)", "전체 집단 평균", "전체 집단 중앙값"],
        "datasets": [{
            "label": f"{ref_col}년 비교",
            "data": [item_val, mean_val, median_val],
            "backgroundColor": ["#2563eb", "#94a3b8", "#64748b"]
        }]
    }

    comparison_table = [
        {"entity": f"{target_item} (선택 대상)", "value": item_val, "is_target": True},
        {"entity": "전체 평균", "value": mean_val, "is_target": False},
        {"entity": "전체 중앙값", "value": median_val, "is_target": False}
    ]

    extra_caution = f"{year_notice} {target_notice}".strip()
    full_cautions = "개별 개체의 순위는 결측치로 인해 제외된 개체들의 영향을 받으므로 전체 표본의 커버리지를 함께 확인해야 합니다."
    if extra_caution:
        full_cautions += f" {extra_caution}"

    main_summary = f"{ref_col}년 {target_item}의 수치는 {item_val:,}로, 전체 평균({mean_val:,}) 및 중앙값({median_val:,}) 대비 분석되었으며, 상위 {rank}위 (상위 {round(100 - percentile, 1)}% 수준)에 해당합니다."
    if extra_caution:
        main_summary += f" {extra_caution}"

    return {
        "success": True,
        "tool": "compare_one_vs_all",
        "title": f"{ref_col}년 {target_item} vs 전체 집단 비교",
        "summary": main_summary,
        "data": {
            "target_item": target_item,
            "target_value": item_val,
            "mean_value": mean_val,
            "median_value": median_val,
            "rank": rank,
            "total_population": len(valid_df),
            "percentile": percentile,
            "chart": chart_data,
            "table": sanitize_dict_list(comparison_table)
        },
        "reference_period": str(reference_period),
        "used_rows": int(len(valid_df)),
        "excluded_rows": int(total_excluded),
        "exclusion_reason": f"기준 시점({ref_col}) 결측치 {na_excluded}건 및 집계 행 {agg_excluded}건을 제외했습니다.",
        "used_columns": [label_column, ref_col],
        "unit": "수치 (원 지표 단위)",
        "cautions": full_cautions
    }


# -----------------------------------------------------------------------------
# 12대 도구 카탈로그 정의 (Step 17 suggest 및 Step 18 run 연동용)
# -----------------------------------------------------------------------------
TOOL_CATALOG = {
    "reshape_wide_to_long": {
        "func": reshape_wide_to_long,
        "name": "연도 열 행 변환 (Wide to Long)",
        "description": "여러 연도 열을 하나의 행(Year, Value)으로 재구조화하여 시계열 데이터셋 생성",
        "requires_ref_period": False
    },
    "quality_report": {
        "func": quality_report,
        "name": "데이터 품질 감사 보고서",
        "description": "결측치 수/비율, 중복 행, 열별 데이터 타입 및 비정상 열 이름 진단",
        "requires_ref_period": False
    },
    "year_coverage": {
        "func": year_coverage,
        "name": "연도별 데이터 충실도 분석",
        "description": "연도별 비결측 데이터 개수를 계산하고 분석에 가장 적합한 최신 권장 기준연도 산출",
        "requires_ref_period": False
    },
    "detect_aggregates": {
        "func": detect_aggregates,
        "name": "집계 및 요약 행 후보 탐지",
        "description": "World, OECD members, Area 등 중복 통계를 유발하는 광역 집계 행 분류",
        "requires_ref_period": False
    },
    "describe_numeric": {
        "func": describe_numeric,
        "name": "기초 기술통계 분석",
        "description": "평균, 중앙값, 최솟값, 최댓값, 표준편차, 사분위수 산출",
        "requires_ref_period": False
    },
    "trend_line": {
        "func": trend_line,
        "name": "시계열 추이 분석 (선 차트)",
        "description": "선택한 국가/항목들의 연도별 변화 추이를 선 차트로 시각화",
        "requires_ref_period": False
    },
    "top_bottom_n": {
        "func": top_bottom_n,
        "name": "상위/하위 N개 순위 분석 (수평 막대)",
        "description": "기준연도 기준 상위 또는 하위 N개 항목 추출 및 수평 막대 차트 생성",
        "requires_ref_period": True
    },
    "group_summary": {
        "func": group_summary,
        "name": "그룹별 요약 통계 (막대 차트)",
        "description": "대륙, 소득 그룹 등 범주별 평균, 합계, 개수 집계",
        "requires_ref_period": True
    },
    "change_rate": {
        "func": change_rate,
        "name": "두 시점 간 변화량/변화율 분석 (막대 차트)",
        "description": "시작 시점 대비 기준 시점의 절대 변화량 및 상대 변화율 계산",
        "requires_ref_period": True
    },
    "distribution": {
        "func": distribution,
        "name": "데이터 분포 분석 (히스토그램)",
        "description": "구간별 빈도 분포 계산 및 왜도(Skewness), 최빈 구간 도출",
        "requires_ref_period": True
    },
    "correlation_scatter": {
        "func": correlation_scatter,
        "name": "상관관계 분석 및 산점도",
        "description": "두 수치 열 간 피어슨 상관계수 계산 및 산점도 시각화 (상관관계 != 인과관계)",
        "requires_ref_period": True
    },
    "compare_one_vs_all": {
        "func": compare_one_vs_all,
        "name": "단일 항목 vs 전체 집단 비교 (강조 막대)",
        "description": "특정 국가/항목의 수치를 전체 평균 및 중앙값과 비교하고 상대적 순위/백분위수 산출",
        "requires_ref_period": True
    }
}
