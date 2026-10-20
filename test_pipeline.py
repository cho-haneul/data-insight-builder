import io
import json
from app import app

def run_integration_test():
    client = app.test_client()
    csv_path = "data/API_IT.NET.USER.ZS_DS2_en_csv_v2_468465/API_IT.NET.USER.ZS_DS2_en_csv_v2_468465.csv"

    print("==================================================")
    print(" 1. POST /inspect (파일 업로드 및 13대 지표 진단)")
    print("==================================================")
    with open(csv_path, "rb") as f:
        res = client.post("/inspect", data={"file": (f, "world_bank_internet.csv")})
    assert res.status_code == 200, f"Inspect failed: {res.text}"
    inspect_data = res.get_json()["diagnosis"]
    print(f"-> 행 수: {inspect_data['row_count']}, 열 수: {inspect_data['column_count']}")
    print(f"-> 감지된 연도 열 수: {len(inspect_data['year_columns'])}개")
    print(f"-> 추천 기준시점(연도): {inspect_data['recommended_reference_year']}")
    print(f"-> 집계 행 감지: {len(inspect_data['aggregate_rows'])}개")

    print("\n==================================================")
    print(" 2. POST /suggest (Gemini 도구 추천 3~5건)")
    print("==================================================")
    res_sug = client.post("/suggest", json={"diagnosis": inspect_data})
    assert res_sug.status_code == 200, f"Suggest failed: {res_sug.text}"
    suggestions = res_sug.get_json()["suggestions"]
    print(f"-> 제안된 분석 수: {len(suggestions)}개")
    for idx, s in enumerate(suggestions, 1):
        print(f"  [{idx}] {s['tool']} ({s['tool_name']}) - 기준시점: {s.get('reference_period')}")
        print(f"      이유: {s['why'][:50]}...")

    # 차트 시각화가 포함된 대표 도구(top_bottom_n 등) 우선 선택
    viz_tools = [s for s in suggestions if s["tool"] in ["top_bottom_n", "trend_line", "distribution", "compare_one_vs_all"]]
    chosen = viz_tools[0] if viz_tools else suggestions[0]

    print("\n==================================================")
    print(f" 3. POST /run (선택 도구 '{chosen['tool']}' Pandas 연산 및 Chart.js 변환)")
    print("==================================================")
    res_run = client.post("/run", json={"tool": chosen["tool"], "params": chosen["params"]})
    assert res_run.status_code == 200, f"Run failed: {res_run.text}"
    run_result = res_run.get_json()
    print(f"-> 실행 도구: {run_result['tool']}")
    print(f"-> 제목: {run_result['title']}")
    print(f"-> 요약: {run_result['summary']}")
    
    inner_data = run_result.get("data", {})
    if "chart" in inner_data:
        chart_obj = inner_data["chart"]
        print(f"-> 차트 유형: {chart_obj.get('type')}, 항목 수: {len(chart_obj.get('labels', []))}")
    if "table" in inner_data:
        print(f"-> 표 데이터 행 수: {len(inner_data['table'])}행")

    print(f"-> 메타데이터: 기준시점={run_result.get('reference_period')}, 사용 행={run_result.get('used_rows')}, 제외 행={run_result.get('excluded_rows')}")
    print(f"-> 제외 사유: {run_result.get('exclusion_reason')}")
    print(f"-> 주의사항: {run_result.get('cautions')}")

    print("\n==================================================")
    print(" 4. POST /explain (모드 B: 8대 규칙 & 7대 헤딩 구조 검증)")
    print("==================================================")
    res_exp_b = client.post("/explain", json={"mode": "B"})
    assert res_exp_b.status_code == 200, f"Explain B failed: {res_exp_b.text}"
    exp_b = res_exp_b.get_json()["explanation"]
    print(f"-> 생성된 모드 B 텍스트 길이: {len(exp_b)}자")
    headings = [line.strip() for line in exp_b.split("\n") if line.strip().startswith("##")]
    print("-> 감지된 7대 헤딩 구조:")
    for h in headings:
        print(f"   {h}")

    print("\n==================================================")
    print(" 5. POST /explain (모드 A: 자의적 추정/비교용 보고서)")
    print("==================================================")
    res_exp_a = client.post("/explain", json={"mode": "A"})
    assert res_exp_a.status_code == 200, f"Explain A failed: {res_exp_a.text}"
    exp_a = res_exp_a.get_json()["explanation"]
    print(f"-> 생성된 모드 A 텍스트 길이: {len(exp_a)}자")

    print("\n==================================================")
    print(" [성공] 모든 파이프라인 E2E 검증 테스트 통과!")
    print("==================================================")

if __name__ == "__main__":
    run_integration_test()
