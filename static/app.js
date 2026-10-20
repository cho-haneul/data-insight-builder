/**
 * AI Data Insight Builder - Frontend Application Logic (Vanilla JS)
 * 
 * [Frontend Console Log 표준 규격]
 * - [PAGE]    페이지 로드 완료
 * - [UPLOAD]  파일 선택 (파일명, 크기)
 * - [INSPECT] 진단 요청 시작 / 응답 수신 (행 수, 열 수, 경고 수)
 * - [SUGGEST] 제안 요청 시작 / 응답 수신 (제안 개수)
 * - [RUN]     도구 실행 시작 (도구명, 기준시점) / 결과 수신
 * - [CHART]   차트 렌더 완료 (차트 종류)
 * - [EXPLAIN] 해석 요청 시작 (모드) / 응답 수신
 * - [ERROR]   오류 발생
 */

document.addEventListener("DOMContentLoaded", () => {
  console.log("[PAGE] 페이지 로드 완료");

  // ---------------------------------------------------------------------------
  // 0. 4자리 숫자 비밀번호(PIN) 잠금 인증
  // ---------------------------------------------------------------------------
  const SITE_PIN = "0110";
  const pinModal = document.getElementById("pinLockModal");
  const pinInput = document.getElementById("pinInput");
  const pinSubmitBtn = document.getElementById("pinSubmitBtn");
  const pinErrorMsg = document.getElementById("pinErrorMsg");

  function initPinAuth() {
    if (!pinModal || !pinInput || !pinSubmitBtn) return;
    const isAuth = sessionStorage.getItem("site_authenticated");
    if (isAuth === "true") {
      pinModal.style.display = "none";
      return;
    }

    pinModal.style.display = "flex";
    setTimeout(() => pinInput.focus(), 150);

    function verifyPin() {
      const entered = pinInput.value.trim();
      if (entered === SITE_PIN) {
        sessionStorage.setItem("site_authenticated", "true");
        pinModal.style.display = "none";
        if (pinErrorMsg) pinErrorMsg.style.display = "none";
      } else {
        if (pinErrorMsg) pinErrorMsg.style.display = "block";
        pinInput.value = "";
        pinInput.focus();
      }
    }

    pinSubmitBtn.addEventListener("click", verifyPin);
    pinInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") verifyPin();
    });
  }

  initPinAuth();

  // ---------------------------------------------------------------------------
  // 0.1 PWA Service Worker 등록 및 설치 프롬프트
  // ---------------------------------------------------------------------------
  let deferredPrompt = null;
  const pwaInstallBtn = document.getElementById("pwaInstallBtn");

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/static/sw.js')
        .then((reg) => console.log('[PWA] Service Worker 등록 성공:', reg.scope))
        .catch((err) => console.log('[PWA] Service Worker 등록 실패:', err));
    });
  }

  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    if (pwaInstallBtn) {
      pwaInstallBtn.style.display = 'inline-block';
      pwaInstallBtn.addEventListener('click', async () => {
        if (!deferredPrompt) return;
        deferredPrompt.prompt();
        const { outcome } = await deferredPrompt.userChoice;
        console.log('[PWA] 설치 결과:', outcome);
        deferredPrompt = null;
        pwaInstallBtn.style.display = 'none';
      });
    }
  });

  window.addEventListener('appinstalled', () => {
    console.log('[PWA] 앱 설치 완료');
    if (pwaInstallBtn) pwaInstallBtn.style.display = 'none';
  });

  // ---------------------------------------------------------------------------
  // 1. 상태 변수 및 DOM 참조
  // ---------------------------------------------------------------------------
  let currentFile = null;
  let currentChartInstance = null;
  let currentRunResult = null;
  let explainCache = { A: null, B: null };

  // DOM 요소
  const serverStatusBadge = document.getElementById("serverStatusBadge");
  const modelBadge = document.getElementById("modelBadge");

  // Step 1 요소
  const dropArea = document.getElementById("dropArea");
  const csvFileInput = document.getElementById("csvFileInput");
  const uploadForm = document.getElementById("uploadForm");
  const fileSelectedBar = document.getElementById("fileSelectedBar");
  const selectedFileName = document.getElementById("selectedFileName");
  const selectedFileSize = document.getElementById("selectedFileSize");
  const uploadErrorAlert = document.getElementById("uploadErrorAlert");
  const btnInspect = document.getElementById("btnInspect");

  // 로딩 인디케이터
  const loadingOverlay = document.getElementById("loadingOverlay");
  const loadingText = document.getElementById("loadingText");

  // Step 2 요소
  const step2Inspect = document.getElementById("step2Inspect");
  const diagEncoding = document.getElementById("diagEncoding");
  const diagSkipRows = document.getElementById("diagSkipRows");
  const diagDimensions = document.getElementById("diagDimensions");
  const diagRecYear = document.getElementById("diagRecYear");
  const diagAggCount = document.getElementById("diagAggCount");
  const diagDupCount = document.getElementById("diagDupCount");
  const warningsBox = document.getElementById("warningsBox");
  const warningsList = document.getElementById("warningsList");
  const previewThead = document.getElementById("previewThead");
  const previewTbody = document.getElementById("previewTbody");
  const btnGetSuggestions = document.getElementById("btnGetSuggestions");

  // Step 2.5 자연어 질문 요소
  const step2Query = document.getElementById("step2Query");
  const nlQueryChips = document.getElementById("nlQueryChips");
  const nlQueryForm = document.getElementById("nlQueryForm");
  const nlQueryInput = document.getElementById("nlQueryInput");
  const btnNlQuery = document.getElementById("btnNlQuery");
  const nlResultBox = document.getElementById("nlResultBox");
  const nlMatchedToolBadge = document.getElementById("nlMatchedToolBadge");
  const nlAnswerContent = document.getElementById("nlAnswerContent");
  const nlActionReason = document.getElementById("nlActionReason");
  const btnRunNlChart = document.getElementById("btnRunNlChart");
  const btnShowCatalogSuggestions = document.getElementById("btnShowCatalogSuggestions");
  let currentNlMapping = null;

  // Step 3 요소
  const step3Suggest = document.getElementById("step3Suggest");
  const suggestionsGrid = document.getElementById("suggestionsGrid");

  // Step 4 요소
  const step4Run = document.getElementById("step4Run");
  const runResultTitle = document.getElementById("runResultTitle");
  const runRefPeriodBadge = document.getElementById("runRefPeriodBadge");
  const runUsedRowsBadge = document.getElementById("runUsedRowsBadge");
  const runExcludedRowsBadge = document.getElementById("runExcludedRowsBadge");
  const exclusionReasonText = document.getElementById("exclusionReasonText");
  const calcDataThead = document.getElementById("calcDataThead");
  const calcDataTbody = document.getElementById("calcDataTbody");
  const cautionBannerText = document.getElementById("cautionBannerText");

  // Step 5 요소
  const step5Explain = document.getElementById("step5Explain");
  const tabModeB = document.getElementById("tabModeB");
  const tabModeA = document.getElementById("tabModeA");
  const modeGuideCallout = document.getElementById("modeGuideCallout");
  const explainContent = document.getElementById("explainContent");

  // 후속 질문(Q&A) 요소
  const followupSection = document.getElementById("followupSection");
  const quickChips = document.getElementById("quickChips");
  const chatThread = document.getElementById("chatThread");
  const followupForm = document.getElementById("followupForm");
  const followupInput = document.getElementById("followupInput");
  const btnAskFollowup = document.getElementById("btnAskFollowup");
  let followupHistory = [];

  // ---------------------------------------------------------------------------
  // 2. 헬퍼 함수
  // ---------------------------------------------------------------------------
  function showLoading(msg) {
    if (loadingText) loadingText.textContent = msg;
    if (loadingOverlay) loadingOverlay.classList.remove("hidden");
  }

  function hideLoading() {
    if (loadingOverlay) loadingOverlay.classList.add("hidden");
  }

  function showError(msg) {
    console.error(`[ERROR] 오류 발생: ${msg}`);
    if (uploadErrorAlert) {
      uploadErrorAlert.textContent = `⚠️ ${msg}`;
      uploadErrorAlert.classList.remove("hidden");
    }
  }

  function clearError() {
    if (uploadErrorAlert) {
      uploadErrorAlert.textContent = "";
      uploadErrorAlert.classList.add("hidden");
    }
  }

  function formatBytes(bytes) {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  }

  // ---------------------------------------------------------------------------
  // 3. 서버 헬스체크 (GET /health)
  // ---------------------------------------------------------------------------
  async function checkServerHealth() {
    try {
      const res = await fetch("/health");
      const data = await res.json();
      if (res.ok && data.status === "ok") {
        if (serverStatusBadge) {
          serverStatusBadge.textContent = "🟢 서버 가동중";
          serverStatusBadge.className = "badge badge-success";
        }
        if (modelBadge) {
          modelBadge.textContent = `🤖 모델: ${data.model}`;
        }
      }
    } catch (err) {
      console.warn("[PAGE] 서버 헬스체크 실패 (오프라인 상태 가능성)");
      if (serverStatusBadge) {
        serverStatusBadge.textContent = "🔴 서버 연결 확인 필요";
        serverStatusBadge.className = "badge badge-warning";
      }
    }
  }
  checkServerHealth();

  // ---------------------------------------------------------------------------
  // 4. Step 1: 드래그 앤 드롭 & 파일 선택 이벤트
  // ---------------------------------------------------------------------------
  ["dragenter", "dragover"].forEach((eventName) => {
    dropArea.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropArea.classList.add("drag-over");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropArea.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropArea.classList.remove("drag-over");
    });
  });

  dropArea.addEventListener("drop", (e) => {
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      handleFileSelected(files[0]);
    }
  });

  csvFileInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFileSelected(e.target.files[0]);
    }
  });

  function handleFileSelected(file) {
    clearError();
    if (!file.name.toLowerCase().endsWith(".csv")) {
      showError("CSV (.csv) 형식의 파일만 업로드할 수 있습니다.");
      return;
    }
    currentFile = file;
    console.log(`[UPLOAD] 파일 선택 완료: name=${file.name}, size=${formatBytes(file.size)}`);

    if (selectedFileName) selectedFileName.textContent = file.name;
    if (selectedFileSize) selectedFileSize.textContent = formatBytes(file.size);
    if (fileSelectedBar) fileSelectedBar.classList.remove("hidden");
  }

  // ---------------------------------------------------------------------------
  // 5. Step 1 -> Step 2: 진단 요청 (POST /inspect)
  // ---------------------------------------------------------------------------
  uploadForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearError();

    if (!currentFile) {
      showError("업로드할 CSV 파일을 먼저 선택해 주세요.");
      return;
    }

    console.log(`[INSPECT] 진단 요청 시작: ${currentFile.name}`);
    showLoading("CSV 파일을 읽고 인코딩 및 데이터 구조를 종합 진단하는 중입니다...");

    const formData = new FormData();
    formData.append("file", currentFile);

    try {
      const res = await fetch("/inspect", {
        method: "POST",
        body: formData
      });
      const data = await res.json();

      if (!res.ok || !data.success) {
        throw new Error(data.error || "데이터 진단에 실패했습니다.");
      }

      const diag = data.diagnosis;
      console.log(`[INSPECT] 진단 응답 수신 (rows=${diag.row_count}, columns=${diag.column_count}, warnings=${diag.warnings.length})`);

      renderDiagnosisReport(data);

      hideLoading();
      step2Inspect.classList.remove("hidden");
      if (step2Query) {
        step2Query.classList.remove("hidden");
        if (nlResultBox) nlResultBox.classList.add("hidden");
        if (nlQueryInput) nlQueryInput.value = "";
        currentNlMapping = null;
      }
      step2Inspect.scrollIntoView({ behavior: "smooth" });

    } catch (err) {
      hideLoading();
      showError(err.message || "서버 통신 중 오류가 발생했습니다.");
    }
  });

  function renderDiagnosisReport(result) {
    const diag = result.diagnosis;

    // 메트릭 표시
    if (diagEncoding) diagEncoding.textContent = result.encoding.toUpperCase();
    if (diagSkipRows) diagSkipRows.textContent = `${result.skip_rows}줄 건너뜀`;
    if (diagDimensions) diagDimensions.textContent = `${diag.row_count.toLocaleString()}행 × ${diag.column_count.toLocaleString()}열`;
    if (diagRecYear) diagRecYear.textContent = diag.recommended_reference_year || "N/A";
    if (diagAggCount) diagAggCount.textContent = `${diag.aggregate_rows.length}개 감지`;
    if (diagDupCount) diagDupCount.textContent = `${diag.duplicate_rows_count}건`;

    // 경고 목록 표시
    if (warningsList) {
      warningsList.innerHTML = "";
      if (diag.warnings && diag.warnings.length > 0) {
        diag.warnings.forEach((w) => {
          const li = document.createElement("li");
          li.textContent = w;
          warningsList.appendChild(li);
        });
        warningsBox.classList.remove("hidden");
      } else {
        warningsBox.classList.add("hidden");
      }
    }

    // 미리보기 테이블 렌더링 (10행)
    renderPreviewTable(diag.preview_rows);
  }

  function renderPreviewTable(rows) {
    if (!previewThead || !previewTbody || !rows || rows.length === 0) return;

    previewThead.innerHTML = "";
    previewTbody.innerHTML = "";

    const headers = Object.keys(rows[0]);
    const trHead = document.createElement("tr");
    headers.forEach((h) => {
      const th = document.createElement("th");
      th.textContent = h;
      trHead.appendChild(th);
    });
    previewThead.appendChild(trHead);

    rows.forEach((row) => {
      const tr = document.createElement("tr");
      headers.forEach((h) => {
        const td = document.createElement("td");
        td.textContent = row[h] !== null && row[h] !== undefined ? row[h] : "-";
        tr.appendChild(td);
      });
      previewTbody.appendChild(tr);
    });
  }

  // ---------------------------------------------------------------------------
  // 5.5 Step 2.5: 자연어 질의 분석 & 맞춤 시각화 매핑 (POST /query)
  // ---------------------------------------------------------------------------
  async function submitNaturalLanguageQuery(queryText) {
    const q = (queryText || "").trim();
    if (!q) return;

    clearError();
    console.log(`[QUERY] 자연어 질의 요청 시작: "${q}"`);
    showLoading("질문을 분석하고 데이터에 근거한 해설과 맞춤 시각화를 구성하는 중입니다...");

    try {
      const res = await fetch("/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q })
      });
      const data = await res.json();

      hideLoading();

      if (!res.ok || !data.success) {
        throw new Error(data.error || "자연어 질의 분석에 실패했습니다.");
      }

      console.log(`[QUERY] 응답 수신 완료 (도구: ${data.tool}, 라벨: ${data.button_label})`);
      currentNlMapping = { tool: data.tool, params: data.params };

      if (nlAnswerContent) {
        if (typeof marked !== "undefined" && marked.parse) {
          nlAnswerContent.innerHTML = marked.parse(data.answer);
        } else {
          nlAnswerContent.innerText = data.answer;
        }
      }

      if (nlMatchedToolBadge) {
        nlMatchedToolBadge.textContent = `도구: ${data.tool_name}`;
      }
      if (nlActionReason) {
        nlActionReason.textContent = data.reason;
      }
      if (btnRunNlChart) {
        btnRunNlChart.textContent = `${data.button_label} 🚀`;
      }

      if (nlResultBox) {
        nlResultBox.classList.remove("hidden");
        nlResultBox.scrollIntoView({ behavior: "smooth" });
      }

    } catch (err) {
      hideLoading();
      showError(err.message || "자연어 질문 처리 중 오류가 발생했습니다.");
    }
  }

  // 자연어 질의 폼 제출
  if (nlQueryForm) {
    nlQueryForm.addEventListener("submit", (e) => {
      e.preventDefault();
      if (nlQueryInput) submitNaturalLanguageQuery(nlQueryInput.value);
    });
  }

  // 자연어 칩 클릭
  if (nlQueryChips) {
    nlQueryChips.addEventListener("click", (e) => {
      const btn = e.target.closest(".chip-btn");
      if (btn && btn.dataset.query) {
        if (nlQueryInput) nlQueryInput.value = btn.dataset.query;
        submitNaturalLanguageQuery(btn.dataset.query);
      }
    });
  }

  // 맞춤 시각화 그래프 보기 버튼 클릭 -> Step 4 & 5 실행
  if (btnRunNlChart) {
    btnRunNlChart.addEventListener("click", () => {
      if (currentNlMapping && currentNlMapping.tool) {
        executeAnalysisTool(currentNlMapping.tool, currentNlMapping.params || {});
      }
    });
  }

  // 12대 정형 추천 보기 버튼 클릭 -> 기존 suggest 트리거
  if (btnShowCatalogSuggestions) {
    btnShowCatalogSuggestions.addEventListener("click", () => {
      if (btnGetSuggestions) btnGetSuggestions.click();
    });
  }

  // ---------------------------------------------------------------------------
  // 6. Step 2 -> Step 3: 맞춤 제안 요청 (POST /suggest)
  // ---------------------------------------------------------------------------
  btnGetSuggestions.addEventListener("click", async () => {
    clearError();
    console.log("[SUGGEST] 제안 요청 시작");
    showLoading("Gemini가 데이터 진단 결과를 바탕으로 12대 공식 도구 중 최적의 분석을 선별하고 있습니다...");

    try {
      const res = await fetch("/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" }
      });
      const data = await res.json();

      if (!res.ok || !data.success) {
        throw new Error(data.error || "분석 제안 수신에 실패했습니다.");
      }

      const suggestions = data.suggestions || [];
      console.log(`[SUGGEST] 제안 응답 수신 (제안 개수: ${suggestions.length}개)`);

      renderSuggestionsCards(suggestions);

      hideLoading();
      step3Suggest.classList.remove("hidden");
      step3Suggest.scrollIntoView({ behavior: "smooth" });

    } catch (err) {
      hideLoading();
      showError(err.message || "Gemini 분석 제안 요청 중 오류가 발생했습니다.");
    }
  });

  function renderSuggestionsCards(suggestions) {
    if (!suggestionsGrid) return;
    suggestionsGrid.innerHTML = "";

    suggestions.forEach((item, index) => {
      const card = document.createElement("div");
      card.className = "suggestion-card";

      card.innerHTML = `
        <div class="sug-header">
          <h3 class="sug-title">#${index + 1}. ${item.tool_name}</h3>
          <span class="badge badge-info">시점: ${item.reference_period}</span>
        </div>
        <p class="sug-desc" style="font-size:0.85rem; color:#64748b;">${item.tool_description}</p>
        <div class="sug-why">
          <strong>💡 제안 이유:</strong> ${item.why}
        </div>
        <div class="sug-caution">
          <strong>⚠️ 주의:</strong> ${item.caution}
        </div>
        <button type="button" class="btn btn-primary btn-run-tool" data-tool="${item.tool}" style="margin-top:auto;">
          ⚡ 이 분석 실행하기
        </button>
      `;

      // 실행 버튼 바인딩
      const runBtn = card.querySelector(".btn-run-tool");
      runBtn.addEventListener("click", () => {
        executeAnalysisTool(item.tool, item.params);
      });

      suggestionsGrid.appendChild(card);
    });
  }

  // ---------------------------------------------------------------------------
  // 7. Step 3 -> Step 4: 분석 도구 실행 (POST /run) & Chart.js 렌더링
  // ---------------------------------------------------------------------------
  async function executeAnalysisTool(toolId, params) {
    clearError();
    const refPeriod = params.reference_period || "N/A";
    console.log(`[RUN] 도구 실행 시작 (도구명: ${toolId}, 기준시점: ${refPeriod})`);
    showLoading(`Pandas가 '${toolId}' 통계 연산 및 차트 데이터를 생성하고 있습니다...`);

    try {
      const res = await fetch("/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool: toolId, params: params })
      });
      const data = await res.json();

      if (!res.ok || !data.success) {
        throw new Error(data.error || "도구 실행 중 오류가 발생했습니다.");
      }

      console.log(`[RUN] 결과 수신 완료 (사용한 행: ${data.used_rows}, 제외한 행: ${data.excluded_rows})`);
      currentRunResult = data;
      explainCache = { A: null, B: null }; // 새 실행 시 캐시 초기화
      followupHistory = [];
      if (chatThread) {
        chatThread.innerHTML = "";
        chatThread.classList.add("hidden");
      }
      if (followupInput) followupInput.value = "";

      renderRunResult(data);

      hideLoading();
      step4Run.classList.remove("hidden");
      step4Run.scrollIntoView({ behavior: "smooth" });

      // 자동으로 Step 5 모드 B 해석 요청 연계
      requestAiExplanation("B");

    } catch (err) {
      hideLoading();
      showError(err.message || "분석 도구 실행에 실패했습니다.");
    }
  }

  function renderRunResult(data) {
    if (runResultTitle) runResultTitle.textContent = `📊 ${data.title}`;
    if (runRefPeriodBadge) runRefPeriodBadge.textContent = `기준시점: ${data.reference_period}`;
    if (runUsedRowsBadge) runUsedRowsBadge.textContent = `사용한 행: ${data.used_rows.toLocaleString()}개`;
    if (runExcludedRowsBadge) runExcludedRowsBadge.textContent = `제외한 행: ${data.excluded_rows.toLocaleString()}개`;
    if (exclusionReasonText) exclusionReasonText.textContent = data.exclusion_reason;
    if (cautionBannerText) cautionBannerText.textContent = data.cautions;

    // Chart.js 렌더링
    renderChart(data.data?.chart);

    // 계산 결과 테이블 렌더링
    renderCalcTable(data.data?.table || data.data?.coverage_table || data.data?.statistics);
  }

  function renderChart(chartConfig) {
    const canvas = document.getElementById("insightChart");
    if (!canvas) return;

    // 이전 차트 인스턴스 파괴
    if (currentChartInstance) {
      currentChartInstance.destroy();
      currentChartInstance = null;
    }

    if (!chartConfig || !chartConfig.datasets) {
      canvas.parentElement.style.display = "none";
      return;
    }

    canvas.parentElement.style.display = "block";
    const ctx = canvas.getContext("2d");

    currentChartInstance = new Chart(ctx, {
      type: chartConfig.type || "bar",
      data: {
        labels: chartConfig.labels || [],
        datasets: chartConfig.datasets || []
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: chartConfig.indexAxis || "x",
        plugins: {
          legend: { position: "top" }
        }
      }
    });

    console.log(`[CHART] 차트 렌더 완료 (차트 종류: ${chartConfig.type || "bar"})`);
  }

  function renderCalcTable(tableData) {
    if (!calcDataThead || !calcDataTbody) return;
    calcDataThead.innerHTML = "";
    calcDataTbody.innerHTML = "";

    if (!tableData) return;

    // 만약 객체(기술통계)인 경우 키-값 형태로 렌더링
    if (!Array.isArray(tableData) && typeof tableData === "object") {
      const trH = document.createElement("tr");
      trH.innerHTML = "<th>통계 지표</th><th>값</th>";
      calcDataThead.appendChild(trH);

      Object.entries(tableData).forEach(([k, v]) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td><strong>${k}</strong></td><td>${typeof v === "number" ? v.toLocaleString() : v}</td>`;
        calcDataTbody.appendChild(tr);
      });
      return;
    }

    if (Array.isArray(tableData) && tableData.length > 0) {
      const headers = Object.keys(tableData[0]);
      const trH = document.createElement("tr");
      headers.forEach((h) => {
        const th = document.createElement("th");
        th.textContent = h;
        calcDataThead.appendChild(th);
      });
      calcDataThead.appendChild(trH);

      tableData.slice(0, 20).forEach((row) => {
        const tr = document.createElement("tr");
        headers.forEach((h) => {
          const td = document.createElement("td");
          const val = row[h];
          td.textContent = typeof val === "number" ? val.toLocaleString() : (val !== null ? val : "-");
          tr.appendChild(td);
        });
        calcDataTbody.appendChild(tr);
      });
    }
  }

  // ---------------------------------------------------------------------------
  // 8. Step 4 -> Step 5: AI 해석 요청 (POST /explain) & 모드 A/B 토글
  // ---------------------------------------------------------------------------
  async function requestAiExplanation(mode) {
    console.log(`[EXPLAIN] 해석 요청 시작 (모드: ${mode})`);

    // 캐시 확인
    if (explainCache[mode]) {
      renderExplanationText(explainCache[mode], mode);
      return;
    }

    if (explainContent) {
      explainContent.innerHTML = `<p class="placeholder-text">⏳ Gemini가 ${mode === 'B' ? 'Pandas 계산 결과' : '개요 데이터'}를 바탕으로 보고서를 작성 중입니다...</p>`;
    }
    step5Explain.classList.remove("hidden");

    try {
      const res = await fetch("/explain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: mode,
          calculation_result: currentRunResult
        })
      });
      const data = await res.json();

      if (!res.ok || !data.success) {
        throw new Error(data.error || "AI 해석 생성에 실패했습니다.");
      }

      console.log(`[EXPLAIN] 해석 응답 수신 완료 (모드: ${mode})`);
      explainCache[mode] = data.explanation;
      renderExplanationText(data.explanation, mode);

    } catch (err) {
      console.error(`[ERROR] AI 해석 요청 실패: ${err.message}`);
      if (explainContent) {
        explainContent.innerHTML = `<p class="alert alert-danger">⚠️ 보고서 작성 중 오류가 발생했습니다: ${err.message}</p>`;
      }
    }
  }

  function renderExplanationText(markdownText, mode) {
    if (!explainContent) return;

    if (typeof marked !== "undefined" && marked.parse) {
      explainContent.innerHTML = marked.parse(markdownText);
    } else {
      explainContent.innerText = markdownText;
    }

    if (modeGuideCallout) {
      if (mode === "B") {
        modeGuideCallout.innerHTML = `<strong>[모드 B - 정식 보고서]</strong> 숫자는 오직 Pandas 계산값만 사용하며, 기준시점과 제외된 행 수, '확인할 수 없는 것'을 명확히 명시하는 과학적 보고서입니다.`;
        modeGuideCallout.style.borderLeft = "4px solid #10b981";
      } else {
        modeGuideCallout.innerHTML = `<strong>[모드 A - 비교용 보고서]</strong> Pandas 계산 결과를 전달하지 않아 AI가 통계 숫자를 자의적으로 추정하거나 배경지식에 의존하여 환각(Hallucination)이 발생할 수 있는 허술한 보고서입니다.`;
        modeGuideCallout.style.borderLeft = "4px solid #f59e0b";
      }
    }
  }

  // 모드 A/B 탭 이벤트 바인딩
  if (tabModeB) {
    tabModeB.addEventListener("click", () => {
      tabModeB.classList.add("active");
      tabModeA.classList.remove("active");
      requestAiExplanation("B");
    });
  }

  if (tabModeA) {
    tabModeA.addEventListener("click", () => {
      tabModeA.classList.add("active");
      tabModeB.classList.remove("active");
      requestAiExplanation("A");
    });
  }

  // ---------------------------------------------------------------------------
  // 9. 후속 질문 (Q&A 멘토링) 처리 로직
  // ---------------------------------------------------------------------------
  async function submitFollowupQuestion(questionText) {
    const q = (questionText || "").trim();
    if (!q) return;

    if (!currentRunResult) {
      showError("먼저 분석 도구를 실행(Step 4)한 후 질문해 주세요.");
      return;
    }

    console.log(`[FOLLOWUP] 후속 질문 요청 시작: "${q}"`);
    if (chatThread) chatThread.classList.remove("hidden");

    // 1) 사용자 질문 말풍선 추가
    appendChatMessage("user", q);

    // 2) 멘토 생각 중 표시기 추가
    const typingBubbleId = `typing-${Date.now()}`;
    appendTypingIndicator(typingBubbleId);

    // 입력창 초기화 및 버튼 비활성화
    if (followupInput) followupInput.value = "";
    if (btnAskFollowup) btnAskFollowup.disabled = true;

    try {
      const res = await fetch("/followup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q,
          history: followupHistory
        })
      });
      const data = await res.json();

      removeTypingIndicator(typingBubbleId);

      if (!res.ok || !data.success) {
        throw new Error(data.error || "답변을 가져오는 데 실패했습니다.");
      }

      console.log(`[FOLLOWUP] 답변 수신 완료 (길이: ${data.answer.length}자)`);

      // 3) 멘토 답변 말풍선 추가
      appendChatMessage("mentor", data.answer);

      // 4) 대화 맥락 기록
      followupHistory.push({ role: "user", text: q });
      followupHistory.push({ role: "assistant", text: data.answer });

    } catch (err) {
      removeTypingIndicator(typingBubbleId);
      console.error(`[ERROR] 후속 질문 실패: ${err.message}`);
      appendChatMessage("mentor", `⚠️ 답변을 불러오지 못했습니다: ${err.message}`);
    } finally {
      if (btnAskFollowup) btnAskFollowup.disabled = false;
      if (followupInput) followupInput.focus();
    }
  }

  function appendChatMessage(role, text) {
    if (!chatThread) return;
    const msgDiv = document.createElement("div");
    msgDiv.className = `chat-message chat-${role}`;

    const labelDiv = document.createElement("span");
    labelDiv.className = "chat-role-label";
    labelDiv.textContent = role === "user" ? "👤 나의 질문" : "🧑‍🏫 데이터 멘토 (초보자 맞춤 해설)";

    const bubbleDiv = document.createElement("div");
    bubbleDiv.className = "chat-bubble";

    if (role === "mentor") {
      if (typeof marked !== "undefined" && marked.parse) {
        bubbleDiv.innerHTML = marked.parse(text);
      } else {
        bubbleDiv.innerText = text;
      }
    } else {
      bubbleDiv.textContent = text;
    }

    msgDiv.appendChild(labelDiv);
    msgDiv.appendChild(bubbleDiv);
    chatThread.appendChild(msgDiv);
    chatThread.scrollTop = chatThread.scrollHeight;
  }

  function appendTypingIndicator(id) {
    if (!chatThread) return;
    const msgDiv = document.createElement("div");
    msgDiv.id = id;
    msgDiv.className = "chat-message chat-mentor";

    const labelDiv = document.createElement("span");
    labelDiv.className = "chat-role-label";
    labelDiv.textContent = "🧑‍🏫 데이터 멘토 생각 중...";

    const bubbleDiv = document.createElement("div");
    bubbleDiv.className = "chat-bubble";
    bubbleDiv.innerHTML = `<span class="placeholder-text">💡 통계 초보자 눈높이에 맞춰 친절하게 설명하는 중입니다...</span>`;

    msgDiv.appendChild(labelDiv);
    msgDiv.appendChild(bubbleDiv);
    chatThread.appendChild(msgDiv);
    chatThread.scrollTop = chatThread.scrollHeight;
  }

  function removeTypingIndicator(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  // 후속 질문 폼 전송 이벤트
  if (followupForm) {
    followupForm.addEventListener("submit", (e) => {
      e.preventDefault();
      if (followupInput) {
        submitFollowupQuestion(followupInput.value);
      }
    });
  }

  // 추천 질문 칩 클릭 이벤트
  if (quickChips) {
    quickChips.addEventListener("click", (e) => {
      const btn = e.target.closest(".chip-btn");
      if (btn && btn.dataset.q) {
        if (followupInput) followupInput.value = btn.dataset.q;
        submitFollowupQuestion(btn.dataset.q);
      }
    });
  }

});
