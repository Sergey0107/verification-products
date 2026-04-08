const table = document.querySelector(".table");
const modal = document.querySelector("[data-comment-modal]");
const form = document.querySelector("[data-comment-form]");
const statusPill = document.querySelector("[data-comment-status]");
const saveResultsButton = document.querySelector("[data-save-user-results]");
const embeddedViewerContext = document.querySelector("[data-viewer-context-json]");

const fields = {
  characteristic: document.querySelector('[data-field="characteristic"]'),
  tzValue: document.querySelector('[data-field="tz_value"]'),
  passportValue: document.querySelector('[data-field="passport_value"]'),
};

const readerNodes = {
  title: document.querySelector("[data-reader-title]"),
  status: document.querySelector("[data-reader-status]"),
  pageIndicator: document.querySelector("[data-page-indicator]"),
  readerEmpty: document.querySelector("[data-reader-empty]"),
  pdfReader: document.querySelector("[data-pdf-reader]"),
  docxReader: document.querySelector("[data-docx-reader]"),
  docxContainer: document.querySelector("[data-docx-container]"),
  canvas: document.querySelector("[data-pdf-canvas]"),
  highlightLayer: document.querySelector("[data-pdf-highlight-layer]"),
  textLayer: document.querySelector("[data-pdf-text-layer]"),
  pdfShell: document.querySelector("[data-pdf-shell]"),
  info: document.querySelector("[data-reader-info]"),
  characteristics: document.querySelector("[data-reader-characteristics]"),
  characteristicsEmpty: document.querySelector("[data-characteristics-empty]"),
  prevButton: document.querySelector("[data-page-prev]"),
  nextButton: document.querySelector("[data-page-next]"),
  zoomInButton: document.querySelector("[data-zoom-in]"),
  zoomOutButton: document.querySelector("[data-zoom-out]"),
};

let activeRowId = null;
let activeRow = null;
const pendingUserResults = new Map();

const viewerContext = (() => {
  if (!embeddedViewerContext?.textContent) {
    return { documents: {}, rows: [] };
  }
  try {
    return JSON.parse(embeddedViewerContext.textContent);
  } catch {
    return { documents: {}, rows: [] };
  }
})();

const rowEvidence = new Map(
  (viewerContext.rows || []).map((item) => [String(item.row_id), item])
);

const viewerState = {
  activeDocKey: null,
  activeCharacteristicId: null,
  activeRowId: null,
  activeEvidence: null,
  activeHighlightContext: null,
  scale: 1.25,
  pdfByDoc: new Map(),
  binaryByDoc: new Map(),
  pageByDoc: new Map(),
  zeroBasedDocs: new Map(),
};

if (window.pdfjsLib) {
  window.pdfjsLib.GlobalWorkerOptions.workerSrc =
    "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.16.105/pdf.worker.min.js";
}

const escapeHtml = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

const normalizeText = (value) =>
  String(value ?? "")
    .toLowerCase()
    .replaceAll("ё", "е")
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();

const getDocumentMeta = (docKey) => viewerContext.documents?.[docKey] || null;

const isDocxDocument = (documentMeta) => {
  if (!documentMeta) {
    return false;
  }
  const mimeType = String(documentMeta.mime_type || "").toLowerCase();
  const fileName = String(documentMeta.file_name || "").toLowerCase();
  return (
    mimeType.includes("wordprocessingml") ||
    mimeType.includes("msword") ||
    fileName.endsWith(".docx") ||
    fileName.endsWith(".doc")
  );
};

const getEvidenceForDoc = (entry, docKey) =>
  docKey === "passport" ? entry?.passport_evidence : entry?.tz_evidence;

const parseRawPage = (value) => {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.trunc(value);
  }
  if (typeof value === "string" && /^\d+$/.test(value.trim())) {
    return Number.parseInt(value.trim(), 10);
  }
  return null;
};

const collectEvidencePages = (evidence) => {
  const pages = [];
  const sourceSpans = Array.isArray(evidence?.source_spans) ? evidence.source_spans : [];
  sourceSpans.forEach((span) => {
    const rawPage = parseRawPage(span?.page_number ?? span?.page);
    if (rawPage !== null) {
      pages.push(rawPage);
    }
  });
  const activeRawPage = parseRawPage(
    evidence?.active_span?.page_number ?? evidence?.active_span?.page ?? evidence?.page_anchor?.page_number ?? evidence?.page_anchor?.page
  );
  if (activeRawPage !== null) {
    pages.push(activeRawPage);
  }
  return pages;
};

const isDocumentZeroBased = (docKey) => {
  if (viewerState.zeroBasedDocs.has(docKey)) {
    return viewerState.zeroBasedDocs.get(docKey);
  }
  const pages = [];
  const documentMeta = getDocumentMeta(docKey);
  const characteristics = Array.isArray(documentMeta?.characteristics)
    ? documentMeta.characteristics
    : [];
  characteristics.forEach((item) => {
    pages.push(...collectEvidencePages(item?.evidence));
  });
  rowEvidence.forEach((row) => {
    pages.push(...collectEvidencePages(getEvidenceForDoc(row, docKey)));
  });
  const zeroBased = pages.some((page) => page === 0);
  viewerState.zeroBasedDocs.set(docKey, zeroBased);
  return zeroBased;
};

const normalizePageNumber = (docKey, rawPage) => {
  if (rawPage === null) {
    return null;
  }
  return isDocumentZeroBased(docKey) ? rawPage + 1 : rawPage;
};

const getSpanPage = (docKey, span) =>
  normalizePageNumber(docKey, parseRawPage(span?.page_number ?? span?.page));

const getPrimarySpan = (evidence) => {
  const spans = Array.isArray(evidence?.source_spans) ? evidence.source_spans : [];
  return (
    evidence?.exact_span ||
    evidence?.page_anchor ||
    evidence?.active_span ||
    evidence?.navigation_target ||
    spans.find((span) => parseRawPage(span?.page_number ?? span?.page) !== null) ||
    spans[0] ||
    null
  );
};

const getPageSpans = (docKey, evidence, pageNumber) => {
  const spans = Array.isArray(evidence?.source_spans) ? evidence.source_spans : [];
  return spans.filter((span) => getSpanPage(docKey, span) === pageNumber);
};

const setReaderStatus = (text) => {
  if (readerNodes.status) {
    readerNodes.status.textContent = text;
  }
};

const setReaderTitle = (text) => {
  if (readerNodes.title) {
    readerNodes.title.textContent = text;
  }
};

const setReaderInfo = (html) => {
  if (readerNodes.info) {
    readerNodes.info.innerHTML = html;
  }
};

const setReaderEmpty = (visible) => {
  if (readerNodes.pdfReader) {
    readerNodes.pdfReader.hidden = true;
  }
  if (readerNodes.docxReader) {
    readerNodes.docxReader.hidden = true;
  }
};

const setPageIndicator = (pageNumber, totalPages) => {
  if (readerNodes.pageIndicator) {
    readerNodes.pageIndicator.textContent =
      pageNumber && totalPages ? `Страница ${pageNumber} / ${totalPages}` : "Страница - / -";
  }
};

const updateToolbarState = (pdfDoc, pageNumber) => {
  const totalPages = pdfDoc?.numPages || 0;
  const enabled = Boolean(pdfDoc);
  if (readerNodes.prevButton) {
    readerNodes.prevButton.disabled = !enabled || pageNumber <= 1;
  }
  if (readerNodes.nextButton) {
    readerNodes.nextButton.disabled = !enabled || pageNumber >= totalPages;
  }
  if (readerNodes.zoomInButton) {
    readerNodes.zoomInButton.disabled = !enabled;
  }
  if (readerNodes.zoomOutButton) {
    readerNodes.zoomOutButton.disabled = !enabled;
  }
  setPageIndicator(pageNumber || null, totalPages || null);
};

const setDocxToolbarState = () => {
  if (readerNodes.prevButton) {
    readerNodes.prevButton.disabled = true;
  }
  if (readerNodes.nextButton) {
    readerNodes.nextButton.disabled = true;
  }
  if (readerNodes.zoomInButton) {
    readerNodes.zoomInButton.disabled = true;
  }
  if (readerNodes.zoomOutButton) {
    readerNodes.zoomOutButton.disabled = true;
  }
  if (readerNodes.pageIndicator) {
    readerNodes.pageIndicator.textContent = "DOCX";
  }
};

const clearRowHighlight = () => {
  document.querySelectorAll("[data-row-id].row-active").forEach((node) => {
    node.classList.remove("row-active");
  });
};

const markActiveRow = (rowId) => {
  clearRowHighlight();
  if (!rowId) {
    return;
  }
  const row = document.querySelector(`[data-row-id="${rowId}"]`);
  row?.classList.add("row-active");
};

const markActiveCharacteristic = (characteristicId) => {
  document.querySelectorAll("[data-doc-char]").forEach((node) => {
    node.classList.toggle(
      "is-active",
      node.getAttribute("data-char-id") === characteristicId
    );
  });
};

const renderCharacteristics = (docKey) => {
  const documentMeta = getDocumentMeta(docKey);
  const items = Array.isArray(documentMeta?.characteristics)
    ? documentMeta.characteristics
    : [];
  if (!readerNodes.characteristics || !readerNodes.characteristicsEmpty) {
    return;
  }
  if (!items.length) {
    readerNodes.characteristics.hidden = true;
    readerNodes.characteristicsEmpty.hidden = false;
    readerNodes.characteristicsEmpty.textContent =
      "Для выбранного документа извлеченные характеристики не найдены.";
    readerNodes.characteristics.innerHTML = "";
    return;
  }
  readerNodes.characteristics.hidden = false;
  readerNodes.characteristicsEmpty.hidden = true;
  readerNodes.characteristics.innerHTML = items
    .map(
      (item) => `
        <button
          class="doc-char-item"
          type="button"
          data-doc-char
          data-doc-key="${escapeHtml(docKey)}"
          data-char-id="${escapeHtml(item.characteristic_id)}"
        >
          <span class="doc-char-name">${escapeHtml(item.label)}</span>
          <span class="doc-char-value">${escapeHtml(item.value || "—")}</span>
        </button>
      `
    )
    .join("");
  markActiveCharacteristic(viewerState.activeCharacteristicId);
};

const buildHighlightTerms = (evidence, context = null) => {
  const raw = [];
  const pushValue = (value) => {
    if (typeof value === "string" && value.trim()) {
      raw.push(value.trim());
    }
  };
  pushValue(evidence?.display_quote);
  pushValue(evidence?.full_quote);
  const sourceSpans = Array.isArray(evidence?.source_spans) ? evidence.source_spans : [];
  sourceSpans.forEach((span) => {
    pushValue(span?.quote_text);
    pushValue(span?.anchor_text);
    pushValue(span?.locator_text);
  });
  if (!raw.length) {
    pushValue(context?.value);
  }
  if (!raw.length) {
    pushValue(context?.label);
  }
  const terms = new Set();
  for (const entry of raw) {
    const normalized = normalizeText(entry);
    if (!normalized) {
      continue;
    }
    if (normalized.length >= 6 && normalized.length <= 180) {
      terms.add(normalized);
    }
  }
  return Array.from(terms).sort((left, right) => right.length - left.length).slice(0, 4);
};

const textMatchesEvidence = (text, terms) => {
  if (!terms.length) {
    return false;
  }
  const normalized = normalizeText(text);
  if (!normalized || normalized.length < 2) {
    return false;
  }
  return terms.some((term) => normalized.includes(term) || term.includes(normalized));
};

const clearOverlayLayers = () => {
  if (readerNodes.textLayer) {
    readerNodes.textLayer.innerHTML = "";
  }
  if (readerNodes.highlightLayer) {
    readerNodes.highlightLayer.innerHTML = "";
  }
  if (readerNodes.docxContainer && window.Mark) {
    const marker = new window.Mark(readerNodes.docxContainer);
    marker.unmark();
  }
};

const getBboxRect = (bbox, viewport) => {
  if (!bbox || typeof bbox !== "object") {
    return null;
  }
  let left = bbox.left ?? bbox.x ?? bbox.x0 ?? bbox.l ?? null;
  let top = bbox.top ?? bbox.y ?? bbox.y0 ?? bbox.t ?? null;
  let width = bbox.width ?? null;
  let height = bbox.height ?? null;
  let right = bbox.right ?? bbox.x1 ?? bbox.r ?? null;
  let bottom = bbox.bottom ?? bbox.y1 ?? bbox.b ?? null;

  const allNumeric = [left, top, width, height, right, bottom]
    .filter((value) => value !== null && value !== undefined)
    .every((value) => typeof value === "number");
  if (!allNumeric) {
    return null;
  }

  const likelyNormalized = [left, top, width, height, right, bottom]
    .filter((value) => typeof value === "number")
    .every((value) => value >= 0 && value <= 1.05);

  if (width == null && right != null && left != null) {
    width = right - left;
  }
  if (height == null && bottom != null && top != null) {
    height = bottom - top;
  }
  if ([left, top, width, height].some((value) => typeof value !== "number")) {
    return null;
  }

  if (likelyNormalized) {
    return {
      left: left * viewport.width,
      top: top * viewport.height,
      width: width * viewport.width,
      height: height * viewport.height,
    };
  }

  if (right == null && width != null && left != null) {
    right = left + width;
  }
  if (bottom == null && height != null && top != null) {
    bottom = top + height;
  }
  if (
    [left, top, right, bottom].some((value) => typeof value !== "number") ||
    !window.pdfjsLib?.Util
  ) {
    return null;
  }

  const [vx0, vy0, vx1, vy1] = viewport.convertToViewportRectangle([
    left,
    top,
    right,
    bottom,
  ]);
  const rectLeft = Math.min(vx0, vx1);
  const rectTop = Math.min(vy0, vy1);
  const rectRight = Math.max(vx0, vx1);
  const rectBottom = Math.max(vy0, vy1);
  return {
    left: rectLeft,
    top: rectTop,
    width: rectRight - rectLeft,
    height: rectBottom - rectTop,
  };
};

const renderHighlightLayer = (viewport, evidence, pageNumber) => {
  if (!readerNodes.highlightLayer) {
    return;
  }
  readerNodes.highlightLayer.innerHTML = "";
  readerNodes.highlightLayer.style.width = `${viewport.width}px`;
  readerNodes.highlightLayer.style.height = `${viewport.height}px`;
  const sourceSpans = getPageSpans(viewerState.activeDocKey, evidence, pageNumber);
  sourceSpans.forEach((span) => {
    const rect = getBboxRect(span?.bbox, viewport);
    if (!rect) {
      return;
    }
    const box = document.createElement("div");
    box.className = "pdf-highlight-box";
    box.style.left = `${rect.left}px`;
    box.style.top = `${rect.top}px`;
    box.style.width = `${rect.width}px`;
    box.style.height = `${rect.height}px`;
    readerNodes.highlightLayer.appendChild(box);
  });
};

const renderTextLayer = async (page, viewport, evidence, pageNumber) => {
  if (!readerNodes.textLayer) {
    return;
  }
  readerNodes.textLayer.innerHTML = "";
  readerNodes.textLayer.style.width = `${viewport.width}px`;
  readerNodes.textLayer.style.height = `${viewport.height}px`;
  const pageSpans = getPageSpans(viewerState.activeDocKey, evidence, pageNumber);
  if (pageSpans.some((span) => span?.bbox)) {
    return;
  }
  const textContent = await page.getTextContent();
  const evidenceForPage =
    pageSpans.length > 0 ? { ...evidence, source_spans: pageSpans } : evidence;
  const terms = buildHighlightTerms(evidenceForPage, viewerState.activeHighlightContext);
  if (!terms.length) {
    return;
  }

  for (const item of textContent.items) {
    const textNode = document.createElement("span");
    const tx = window.pdfjsLib.Util.transform(viewport.transform, item.transform);
    const fontSize = Math.hypot(tx[2], tx[3]);
    const angle = Math.atan2(tx[1], tx[0]);
    textNode.className = "pdf-text-item";
    if (textMatchesEvidence(item.str, terms)) {
      textNode.classList.add("is-highlighted");
    }
    textNode.textContent = item.str;
    textNode.style.left = `${tx[4]}px`;
    textNode.style.top = `${viewport.height - tx[5]}px`;
    textNode.style.fontSize = `${fontSize}px`;
    textNode.style.transform = `translateY(-100%) rotate(${angle}rad)`;
    textNode.style.transformOrigin = "left bottom";
    readerNodes.textLayer.appendChild(textNode);
  }
};

const ensurePdfDocument = async (docKey) => {
  if (viewerState.pdfByDoc.has(docKey)) {
    return viewerState.pdfByDoc.get(docKey);
  }
  const documentMeta = getDocumentMeta(docKey);
  if (!documentMeta?.download_url) {
    throw new Error("Файл документа не найден");
  }
  setReaderStatus("Загрузка PDF...");
  const response = await fetch(documentMeta.download_url, {
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new Error(`Не удалось загрузить PDF (${response.status})`);
  }
  const bytes = await response.arrayBuffer();
  const pdfDoc = await window.pdfjsLib.getDocument({ data: bytes }).promise;
  viewerState.pdfByDoc.set(docKey, pdfDoc);
  if (!viewerState.pageByDoc.has(docKey)) {
    viewerState.pageByDoc.set(docKey, 1);
  }
  return pdfDoc;
};

const ensureDocumentBinary = async (docKey) => {
  if (viewerState.binaryByDoc.has(docKey)) {
    return viewerState.binaryByDoc.get(docKey);
  }
  const documentMeta = getDocumentMeta(docKey);
  if (!documentMeta?.download_url) {
    throw new Error("Файл документа не найден");
  }
  setReaderStatus("Загрузка документа...");
  const response = await fetch(documentMeta.download_url, {
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new Error(`Не удалось загрузить документ (${response.status})`);
  }
  const bytes = await response.arrayBuffer();
  viewerState.binaryByDoc.set(docKey, bytes);
  return bytes;
};

const renderDocxHighlights = (evidence) => {
  if (!readerNodes.docxContainer || !window.Mark) {
    return;
  }
  const terms = buildHighlightTerms(evidence, viewerState.activeHighlightContext);
  if (!terms.length) {
    return;
  }
  const marker = new window.Mark(readerNodes.docxContainer);
  marker.unmark({
    done: () => {
      marker.mark(terms, {
        separateWordSearch: false,
        accuracy: "partially",
        className: "docx-highlight",
        acrossElements: true,
        done: () => {
          readerNodes.docxContainer
            .querySelector("mark.docx-highlight")
            ?.scrollIntoView({ block: "center", behavior: "smooth" });
        },
      });
    },
  });
};

const renderDocxDocument = async (docKey) => {
  if (!readerNodes.docxReader || !readerNodes.docxContainer || !window.docx?.renderAsync) {
    throw new Error("DOCX viewer недоступен");
  }
  const bytes = await ensureDocumentBinary(docKey);
  clearOverlayLayers();
  readerNodes.docxContainer.innerHTML = "";
  await window.docx.renderAsync(bytes, readerNodes.docxContainer, null, {
    inWrapper: true,
    breakPages: true,
    ignoreWidth: false,
    ignoreHeight: false,
  });
  readerNodes.docxReader.hidden = false;
  if (viewerState.activeEvidence) {
    renderDocxHighlights(viewerState.activeEvidence);
  }
  setDocxToolbarState();
};

const renderPage = async (pageNumber) => {
  const docKey = viewerState.activeDocKey;
  if (!docKey) {
    return;
  }
  const pdfDoc = viewerState.pdfByDoc.get(docKey);
  if (!pdfDoc || !readerNodes.canvas || !readerNodes.pdfShell) {
    return;
  }
  const boundedPage = Math.max(1, Math.min(pageNumber, pdfDoc.numPages));
  const page = await pdfDoc.getPage(boundedPage);
  const viewport = page.getViewport({ scale: viewerState.scale });
  const canvas = readerNodes.canvas;
  const context = canvas.getContext("2d");
  clearOverlayLayers();
  canvas.width = Math.ceil(viewport.width);
  canvas.height = Math.ceil(viewport.height);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;
  readerNodes.pdfShell.style.width = `${viewport.width}px`;
  readerNodes.pdfShell.style.height = `${viewport.height}px`;
  await page.render({ canvasContext: context, viewport }).promise;
  renderHighlightLayer(viewport, viewerState.activeEvidence, boundedPage);
  await renderTextLayer(page, viewport, viewerState.activeEvidence, boundedPage);
  viewerState.pageByDoc.set(docKey, boundedPage);
  updateToolbarState(pdfDoc, boundedPage);
};

const buildEvidenceSummary = (docKey, label, value, evidence) => {
  const span = getPrimarySpan(evidence);
  const page = getSpanPage(docKey, span);
  return `
    <div><strong>${escapeHtml(label || "Характеристика")}</strong></div>
    <div><strong>Значение:</strong> ${escapeHtml(value || "—")}</div>
    <div><strong>Страница:</strong> ${escapeHtml(page || "не определена")}</div>
    <div><strong>Цитата:</strong> ${escapeHtml(span?.quote_text || evidence?.display_quote || "—")}</div>
    <div><strong>Режим привязки:</strong> ${escapeHtml(evidence?.position_status || "missing")}</div>
  `;
};

const openDocument = async (
  docKey,
  { evidence = null, characteristicId = null, rowId = null, infoHtml = null } = {}
) => {
  const documentMeta = getDocumentMeta(docKey);
  if (!documentMeta) {
    setReaderStatus("Документ не найден");
    return;
  }
  viewerState.activeDocKey = docKey;
  viewerState.activeCharacteristicId = characteristicId;
  viewerState.activeRowId = rowId;
  viewerState.activeEvidence = evidence;
  viewerState.activeHighlightContext = null;
  renderCharacteristics(docKey);
  markActiveCharacteristic(characteristicId);
  markActiveRow(rowId);
  setReaderTitle(`${docKey === "tz" ? "ТЗ" : "Паспорт"}: ${documentMeta.file_name || "Файл"}`);

  try {
    if (isDocxDocument(documentMeta)) {
      setReaderEmpty(false);
      await renderDocxDocument(docKey);
      setReaderStatus(evidence ? "Открыт DOCX с подсветкой" : "Открыт DOCX документ");
    } else {
      const pdfDoc = await ensurePdfDocument(docKey);
      setReaderEmpty(false);
      readerNodes.pdfReader.hidden = false;
      const targetPage =
        getSpanPage(docKey, getPrimarySpan(evidence)) ||
        viewerState.pageByDoc.get(docKey) ||
        1;
      await renderPage(targetPage);
      const pageText = targetPage ? `Открыта страница ${targetPage}` : "Открыт документ";
      setReaderStatus(pageText);
      updateToolbarState(pdfDoc, viewerState.pageByDoc.get(docKey) || 1);
    }
    setReaderInfo(
      infoHtml ||
        (evidence
          ? buildEvidenceSummary(docKey, "Фрагмент документа", "", evidence)
          : "Документ открыт. Выберите характеристику слева или переход из таблицы сравнения.")
    );
  } catch (error) {
    setReaderEmpty(true);
    setReaderStatus(error.message || "Не удалось открыть PDF");
    setReaderInfo("Произошла ошибка при загрузке PDF документа.");
  }
};

const openDocumentCharacteristic = async (docKey, characteristicId) => {
  const documentMeta = getDocumentMeta(docKey);
  const item = (documentMeta?.characteristics || []).find(
    (entry) => entry.characteristic_id === characteristicId
  );
  if (!item) {
    setReaderStatus("Характеристика не найдена");
    return;
  }
  await openDocument(docKey, {
    characteristicId,
    evidence: item.evidence || null,
    infoHtml: buildEvidenceSummary(docKey, item.label, item.value, item.evidence || {}),
  });
  viewerState.activeHighlightContext = {
    label: item.label,
    value: item.value,
  };
  if (isDocxDocument(documentMeta)) {
    await renderDocxDocument(docKey);
  } else {
    await renderPage(viewerState.pageByDoc.get(docKey) || 1);
  }
};

window.openComparisonEvidence = async (rowId, docKey) => {
  const row = rowEvidence.get(String(rowId));
  if (!row) {
    setReaderStatus("Не найдены данные для перехода");
    return false;
  }
  const evidence = getEvidenceForDoc(row, docKey);
  await openDocument(docKey, {
    rowId: String(rowId),
    evidence,
    infoHtml: buildEvidenceSummary(
      docKey,
      row.characteristic,
      docKey === "passport" ? row.passport_value : row.tz_value,
      evidence || {}
    ),
  });
  viewerState.activeHighlightContext = {
    label: row.characteristic,
    value: docKey === "passport" ? row.passport_value : row.tz_value,
  };
  if (isDocxDocument(getDocumentMeta(docKey))) {
    await renderDocxDocument(docKey);
  } else {
    await renderPage(viewerState.pageByDoc.get(docKey) || 1);
  }
  return false;
};

const openModal = (row) => {
  activeRowId = row.getAttribute("data-row-id");
  activeRow = row;
  if (fields.characteristic) {
    fields.characteristic.textContent = row.getAttribute("data-characteristic") || "";
  }
  if (fields.tzValue) {
    fields.tzValue.textContent = row.getAttribute("data-tz-value") || "";
  }
  if (fields.passportValue) {
    fields.passportValue.textContent = row.getAttribute("data-passport-value") || "";
  }
  if (form) {
    const comment = row.getAttribute("data-comment") || "";
    const textarea = form.querySelector("textarea");
    if (textarea) {
      textarea.value = comment;
    }
  }
  if (statusPill) {
    statusPill.hidden = true;
  }
  if (modal) {
    modal.hidden = false;
    document.body.style.overflow = "hidden";
  }
};

const closeModal = () => {
  if (modal) {
    modal.hidden = true;
    document.body.style.overflow = "";
  }
  activeRowId = null;
  activeRow = null;
};

if (modal) {
  const closeTargets = modal.querySelectorAll("[data-close]");
  closeTargets.forEach((target) => target.addEventListener("click", closeModal));
}

document.querySelectorAll("[data-open-document]").forEach((button) => {
  button.addEventListener("click", () => {
    const docKey = button.getAttribute("data-open-document");
    if (docKey) {
      openDocument(docKey);
    }
  });
});

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-doc-char]");
  if (!button) {
    return;
  }
  const docKey = button.getAttribute("data-doc-key");
  const characteristicId = button.getAttribute("data-char-id");
  if (docKey && characteristicId) {
    openDocumentCharacteristic(docKey, characteristicId);
  }
});

if (readerNodes.prevButton) {
  readerNodes.prevButton.addEventListener("click", async () => {
    const currentPage = viewerState.pageByDoc.get(viewerState.activeDocKey) || 1;
    await renderPage(currentPage - 1);
    setReaderStatus(`Открыта страница ${viewerState.pageByDoc.get(viewerState.activeDocKey)}`);
  });
}

if (readerNodes.nextButton) {
  readerNodes.nextButton.addEventListener("click", async () => {
    const currentPage = viewerState.pageByDoc.get(viewerState.activeDocKey) || 1;
    await renderPage(currentPage + 1);
    setReaderStatus(`Открыта страница ${viewerState.pageByDoc.get(viewerState.activeDocKey)}`);
  });
}

if (readerNodes.zoomInButton) {
  readerNodes.zoomInButton.addEventListener("click", async () => {
    if (!viewerState.activeDocKey) {
      return;
    }
    viewerState.scale = Math.min(viewerState.scale + 0.2, 2.4);
    await renderPage(viewerState.pageByDoc.get(viewerState.activeDocKey) || 1);
  });
}

if (readerNodes.zoomOutButton) {
  readerNodes.zoomOutButton.addEventListener("click", async () => {
    if (!viewerState.activeDocKey) {
      return;
    }
    viewerState.scale = Math.max(viewerState.scale - 0.2, 0.8);
    await renderPage(viewerState.pageByDoc.get(viewerState.activeDocKey) || 1);
  });
}

if (table) {
  table.addEventListener("click", (event) => {
    const button = event.target.closest("[data-open-comment]");
    if (!button) return;
    const row = button.closest("[data-row-id]");
    if (!row) return;
    openModal(row);
  });

  table.addEventListener("change", async (event) => {
    const checkbox = event.target.closest("[data-user-result]");
    if (!checkbox) return;
    const row = checkbox.closest("[data-row-id]");
    if (!row) return;
    const rowId = row.getAttribute("data-row-id");
    if (!rowId) return;
    pendingUserResults.set(rowId, checkbox.checked);
    if (saveResultsButton) {
      saveResultsButton.disabled = pendingUserResults.size === 0;
    }
  });
}

if (form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!activeRowId) return;
    const formData = new FormData(form);
    const comment = formData.get("comment");
    if (!comment) return;
    const response = await fetch(`/api/comparison-rows/${activeRowId}/comment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ comment }),
    });
    if (response.ok) {
      if (activeRow) {
        activeRow.setAttribute("data-comment", comment);
      }
      if (statusPill) {
        statusPill.hidden = false;
        setTimeout(() => {
          if (statusPill) statusPill.hidden = true;
        }, 1200);
      }
      setTimeout(closeModal, 200);
    }
  });
}

if (saveResultsButton) {
  saveResultsButton.addEventListener("click", async () => {
    if (pendingUserResults.size === 0) return;
    const entries = Array.from(pendingUserResults.entries());
    await Promise.all(
      entries.map(([rowId, value]) =>
        fetch(`/api/comparison-rows/${rowId}/user-result`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ user_result: value }),
        })
      )
    );
    pendingUserResults.clear();
    saveResultsButton.disabled = true;
  });
}

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeModal();
  }
});

setReaderEmpty(true);
setReaderStatus("Выберите ТЗ или Паспорт");
setReaderTitle("Документ не открыт");
updateToolbarState(null, null);
