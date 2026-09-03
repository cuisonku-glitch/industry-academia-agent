const state = {
  page: 1,
  pageSize: 18,
  query: "",
  teacher: "",
  status: "",
  selected: null,
  detailTab: "local",
  readingFocus: false,
};

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function inlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function renderMarkdown(markdown) {
  const lines = String(markdown || "").replaceAll("\r\n", "\n").split("\n");
  const html = [];
  let listType = "";
  const closeList = () => {
    if (listType) html.push(`</${listType}>`);
    listType = "";
  };
  for (let index = 0; index < lines.length; index += 1) {
    const raw = lines[index];
    const line = raw.trim();
    if (!line) { closeList(); continue; }
    const image = line.match(/^!\[([^\]]*)\]\((\/api\/papers\/[a-f0-9]{64}\/figures\/[A-Z0-9_-]+\/image)\)$/);
    if (image) {
      closeList();
      html.push(`<figure class="paper-figure"><img src="${image[2]}" alt="${escapeHtml(image[1])}" loading="lazy"><figcaption>${escapeHtml(image[1])}</figcaption></figure>`);
      continue;
    }
    const tableNext = lines[index + 1] || "";
    if (line.includes("|") && /^\s*\|?\s*:?-+/.test(tableNext)) {
      closeList();
      const header = line.replace(/^\||\|$/g, "").split("|");
      const rows = [];
      index += 2;
      while (index < lines.length && lines[index].includes("|")) {
        rows.push(lines[index].trim().replace(/^\||\|$/g, "").split("|"));
        index += 1;
      }
      index -= 1;
      html.push("<table><thead><tr>" + header.map(cell => `<th>${inlineMarkdown(cell.trim())}</th>`).join("") + "</tr></thead><tbody>");
      rows.forEach(row => html.push("<tr>" + row.map(cell => `<td>${inlineMarkdown(cell.trim())}</td>`).join("") + "</tr>"));
      html.push("</tbody></table>");
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) { closeList(); const level = heading[1].length; html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`); continue; }
    if (line.startsWith(">")) { closeList(); html.push(`<blockquote>${inlineMarkdown(line.slice(1).trim())}</blockquote>`); continue; }
    const unordered = line.match(/^[-*]\s+(.+)$/);
    if (unordered) {
      if (listType !== "ul") { closeList(); listType = "ul"; html.push("<ul>"); }
      html.push(`<li>${inlineMarkdown(unordered[1])}</li>`);
      continue;
    }
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    if (ordered) {
      if (listType !== "ol") { closeList(); listType = "ol"; html.push("<ol>"); }
      html.push(`<li>${inlineMarkdown(ordered[1])}</li>`);
      continue;
    }
    closeList();
    html.push(`<p>${inlineMarkdown(line)}</p>`);
  }
  closeList();
  return html.join("");
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof body === "object" ? body.detail : body;
    throw new Error(message || `请求失败 (${response.status})`);
  }
  return body;
}

function toast(message, isError = false) {
  const element = $("#toast");
  element.textContent = message;
  element.className = `toast show${isError ? " error" : ""}`;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => { element.className = "toast"; }, 3600);
}

function metadataLine(paper) {
  const values = [];
  if (paper.authors?.length) values.push(paper.authors.join("、"));
  if (paper.year) values.push(String(paper.year));
  if (paper.page_count) values.push(`${paper.page_count} 页`);
  return values.join(" · ") || "作者、年份等元数据待自动补全";
}

function cardHtml(paper) {
  const tags = paper.tags.length
    ? paper.tags.map((tag, index) => `<span class="tag${index === 0 ? " primary" : ""}" title="${escapeHtml(tag.category_label)}">${escapeHtml(tag.value)}</span>`).join("")
    : '<span class="tag">正文解析后自动生成标签</span>';
  return `
    <article class="paper-card">
      <div class="card-top">
        <span class="teacher-badge">${escapeHtml(paper.teacher)}</span>
        <span class="status-badge ${escapeHtml(paper.status.tone)}">${escapeHtml(paper.status.label)}</span>
      </div>
      <h3 title="${escapeHtml(paper.title)}">${escapeHtml(paper.title)}</h3>
      <div class="card-meta">${escapeHtml(metadataLine(paper))}</div>
      <div class="card-tags">${tags}</div>
      <div class="card-footer">
        <span class="report-state">${paper.has_deep_report ? "已有 Kimi 精读" : (paper.has_local_report ? "已有本地底稿" : "尚未生成精读")}</span>
        <button class="open-button" type="button" data-paper-id="${escapeHtml(paper.paper_id)}">打开论文 →</button>
      </div>
    </article>`;
}

async function loadStats() {
  const stats = await api("/api/stats");
  $("#paper-total").textContent = `${stats.papers} 篇`;
  $("#all-count").textContent = stats.papers;
  $("#hero-stats").innerHTML = [
    [stats.papers, "论文卡片"],
    [stats.teachers, "导师"],
    [stats.indexed, "已建立索引"],
    [stats.reports, "本地底稿"],
    [stats.deep_reports, "Kimi 精读"],
  ].map(([value, label]) => `<div class="stat-chip"><b>${value}</b><span>${label}</span></div>`).join("");
}

async function loadTeachers() {
  const params = new URLSearchParams();
  if (state.query) params.set("query", state.query);
  if (state.status) params.set("status", state.status);
  const data = await api(`/api/teachers?${params}`);
  $("#teacher-list").innerHTML = data.items.map(item => `
    <button class="teacher-item${state.teacher === item.teacher ? " active" : ""}" type="button" data-teacher="${escapeHtml(item.teacher)}">
      <span>${escapeHtml(item.teacher)}</span><b>${item.paper_count}</b>
    </button>`).join("");
  $("#all-teachers").classList.toggle("active", !state.teacher);
  $("#teacher-list").querySelectorAll("[data-teacher]").forEach(button => {
    button.addEventListener("click", () => {
      state.teacher = button.dataset.teacher;
      state.page = 1;
      loadPapers();
      loadTeachers();
    });
  });
}

function paginationHtml(data) {
  if (data.page_count <= 1) return "";
  const pages = new Set([1, data.page_count, data.page - 1, data.page, data.page + 1]);
  const sequence = [...pages].filter(page => page >= 1 && page <= data.page_count).sort((a, b) => a - b);
  const buttons = [`<button class="page-button" data-page="${data.page - 1}" ${data.page === 1 ? "disabled" : ""}>‹</button>`];
  let previous = 0;
  sequence.forEach(page => {
    if (page - previous > 1) buttons.push("<span class=\"page-button\" style=\"display:grid;place-items:center;border:0;background:transparent\">…</span>");
    buttons.push(`<button class="page-button${page === data.page ? " active" : ""}" data-page="${page}">${page}</button>`);
    previous = page;
  });
  buttons.push(`<button class="page-button" data-page="${data.page + 1}" ${data.page === data.page_count ? "disabled" : ""}>›</button>`);
  return buttons.join("");
}

async function loadPapers() {
  $("#paper-grid").innerHTML = '<div class="loading-state">正在整理论文卡片……</div>';
  const params = new URLSearchParams({ page: state.page, page_size: state.pageSize });
  if (state.query) params.set("query", state.query);
  if (state.teacher) params.set("teacher", state.teacher);
  if (state.status) params.set("status", state.status);
  try {
    const data = await api(`/api/papers?${params}`);
    state.page = data.page;
    $("#result-title").textContent = state.teacher || (state.query ? "搜索结果" : "全部论文");
    $("#result-meta").textContent = `匹配 ${data.total} 篇 · 第 ${data.page}/${data.page_count} 页`;
    $("#paper-grid").innerHTML = data.items.length
      ? data.items.map(cardHtml).join("")
      : '<div class="empty-state">没有找到匹配的论文，请调整搜索条件。</div>';
    $("#paper-grid").querySelectorAll("[data-paper-id]").forEach(button => {
      button.addEventListener("click", () => openPaper(button.dataset.paperId));
    });
    $("#pagination").innerHTML = paginationHtml(data);
    $("#pagination").querySelectorAll("[data-page]").forEach(button => {
      button.addEventListener("click", () => {
        if (button.disabled) return;
        state.page = Number(button.dataset.page);
        loadPapers();
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
    });
  } catch (error) {
    $("#paper-grid").innerHTML = `<div class="empty-state">读取失败：${escapeHtml(error.message)}</div>`;
  }
}

function detailData(paper) {
  const rows = [
    ["导师", paper.teacher],
    ["作者", paper.authors.length ? paper.authors.join("、") : "待识别"],
    ["院校 / 学院", [paper.institution, paper.college].filter(Boolean).join(" / ") || "待识别"],
    ["年份", paper.year || "待识别"],
    ["研究方向", paper.direction],
    ["页数 / 文件", `${paper.page_count || "—"} 页 / ${paper.file_size_mb || "—"} MB`],
    ["解析版本", paper.parser_version || "待解析"],
    ["数据来源", paper.source_type],
  ];
  return rows.map(([label, value]) => `<div class="data-row"><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>`).join("");
}

function detailHtml(paper) {
  const tags = paper.tags.map(tag => `<span class="detail-chip">${escapeHtml(tag.category_label)} · ${escapeHtml(tag.value)}</span>`).join("");
  return `
    <section class="detail-header">
      <span class="eyebrow">${escapeHtml(paper.teacher)} · 论文技术卡片</span>
      <h1>${escapeHtml(paper.title)}</h1>
      <div class="detail-chips">
        <span class="status-badge ${escapeHtml(paper.status.tone)}">${escapeHtml(paper.status.label)}</span>
        ${tags || '<span class="detail-chip">标签将在正文解析后自动补充</span>'}
      </div>
    </section>
    <div class="detail-columns">
      <div>
        <section class="detail-panel">
          <div class="section-head"><h2>论文分析任务</h2><p>本地步骤不联网；Kimi 将精读、图版和公式解读合并为一份报告。</p></div>
          <div class="action-grid">
            <button id="local-reading-button" class="action-button primary" type="button">
              <strong>${paper.has_local_report ? "重新生成证据底稿" : "生成本地证据底稿"}</strong><small>按摘要、方法、结果和结论定位页码级原文证据</small>
            </button>
            <button id="figure-button" class="action-button" type="button">
              <strong>${paper.has_figures ? `重新提取论文图像（${paper.figure_count}）` : "提取原图与图注"}</strong><small>仅在本机裁切并保留图号、图注、页码，不调用外部 API</small>
            </button>
            <button id="kimi-reading-button" class="action-button kimi" type="button">
              <strong>${paper.has_deep_report ? "重新生成 Kimi 结构化精读" : "生成 Kimi 结构化精读"}</strong><small>正文总结、图版、公式和可转化技术资产合并为一份报告</small>
            </button>
            ${paper.has_drawio_route
              ? `<a class="action-button route-link" href="/api/papers/${paper.paper_id}/technical-route.drawio"><strong>下载技术路线 draw.io</strong><small>原生可编辑节点与连线，证据标签已写入节点</small></a>`
              : '<button class="action-button" type="button" disabled><strong>技术路线 draw.io</strong><small>完成一次 Kimi 结构化精读后自动生成</small></button>'}
          </div>
          <div class="consent-box">
            <label><input id="kimi-consent" type="checkbox"> 我同意本次将这篇论文的选定原文片段、公式候选及最多 4 张提取图像发送到 <code>.env</code> 配置的 Moonshot API。</label>
            <p id="kimi-scope">正在核对本次发送范围……</p>
          </div>
          <div class="section-head"><h2>论文基础信息</h2><p>来自本地 SQLite 目录；未识别字段不会自动编造。</p></div>
          <div class="detail-data">${detailData(paper)}</div>
        </section>
      </div>
      <section class="detail-panel">
        <div class="section-head"><h2>论文与报告</h2><p>在完整页面中切换报告和 PDF 原文。</p></div>
        <div class="tab-row">
          <button class="tab-button" data-detail-tab="local" type="button">本地证据底稿</button>
          <button class="tab-button" data-detail-tab="kimi" type="button">Kimi 结构化精读</button>
          <button class="tab-button" data-detail-tab="pdf" type="button" ${paper.has_pdf ? "" : "disabled"}>PDF 原文</button>
          <button class="tab-button" data-detail-tab="figures" type="button">论文图片 ${paper.figure_count ? `(${paper.figure_count})` : ""}</button>
          <button id="reading-mode-button" class="reading-mode-button" type="button">⛶ 放大阅读</button>
        </div>
        <div id="detail-content"></div>
      </section>
    </div>`;
}

async function showLocalReport(paper) {
  const content = $("#detail-content");
  if (!paper.has_local_report) {
    content.innerHTML = '<div class="report-empty">尚未生成本地证据底稿。<br>点击左侧“生成本地证据底稿”即可开始，不会调用外部 API。</div>';
    return;
  }
  content.innerHTML = '<div class="report-empty">正在读取报告……</div>';
  try {
    const report = await api(`/api/papers/${paper.paper_id}/report`);
    content.innerHTML = `<article class="report-body">${renderMarkdown(report)}</article><div class="download-row"><a class="download-button" href="/api/papers/${paper.paper_id}/report?download=true">下载 Markdown</a></div>`;
  } catch (error) {
    content.innerHTML = `<div class="report-empty">${escapeHtml(error.message)}</div>`;
  }
}

async function showKimiReport(paper) {
  const content = $("#detail-content");
  if (!paper.has_deep_report) {
    content.innerHTML = '<div class="report-empty">尚未生成 Kimi 结构化精读。<br>先核对左侧发送范围、勾选一次性同意，再点击生成。</div>';
    return;
  }
  content.innerHTML = '<div class="report-empty">正在读取 Kimi 结构化精读……</div>';
  try {
    const report = await api(`/api/papers/${paper.paper_id}/deep-report`);
    content.innerHTML = `<article class="report-body">${renderMarkdown(report)}</article><div class="download-row"><a class="download-button" href="/api/papers/${paper.paper_id}/deep-report?download=true">下载 Markdown</a><a class="download-button" href="/api/papers/${paper.paper_id}/technical-route.drawio">下载 draw.io</a></div>`;
  } catch (error) {
    content.innerHTML = `<div class="report-empty">${escapeHtml(error.message)}</div>`;
  }
}

function figureGallery(data) {
  if (!data.items.length) {
    return '<div class="report-empty">尚未提取论文图像。点击左侧“提取原图与图注”，全程只在本机处理。</div>';
  }
  return `<div class="figure-gallery">${data.items.map(item => `
    <figure class="figure-card">
      <a href="${item.image_url}" target="_blank" rel="noopener"><img src="${item.image_url}" alt="${escapeHtml(item.asset_id + ' ' + item.label)}" loading="lazy"></a>
      <figcaption><b>${escapeHtml(item.asset_id)} · ${escapeHtml(item.label)} · 第 ${item.page} 页</b><span>${escapeHtml(item.caption)}</span></figcaption>
    </figure>`).join("")}</div>`;
}

async function showFigures(paper) {
  const content = $("#detail-content");
  content.innerHTML = '<div class="report-empty">正在读取本地图像……</div>';
  try {
    const data = await api(`/api/papers/${paper.paper_id}/figures`);
    content.innerHTML = figureGallery(data);
  } catch (error) {
    content.innerHTML = `<div class="report-empty">${escapeHtml(error.message)}</div>`;
  }
}

function showPdf(paper) {
  $("#detail-content").innerHTML = paper.has_pdf
    ? `<iframe class="pdf-frame" title="${escapeHtml(paper.title)} PDF 原文" src="/api/papers/${paper.paper_id}/pdf#view=FitH"></iframe>`
    : '<div class="report-empty">本机没有找到该论文的原始 PDF。</div>';
}

function activateDetailTab(tab, paper) {
  state.detailTab = tab;
  document.querySelectorAll("[data-detail-tab]").forEach(button => button.classList.toggle("active", button.dataset.detailTab === tab));
  if (tab === "pdf") showPdf(paper);
  else if (tab === "figures") showFigures(paper);
  else if (tab === "kimi") showKimiReport(paper);
  else showLocalReport(paper);
}

function toggleReadingFocus() {
  state.readingFocus = !state.readingFocus;
  const shell = $("#detail-shell");
  shell.classList.toggle("reading-focus", state.readingFocus);
  $("#reading-mode-button").textContent = state.readingFocus ? "退出放大" : "⛶ 放大阅读";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function openPaper(paperId) {
  try {
    const paper = await api(`/api/papers/${paperId}`);
    state.selected = paper;
    state.detailTab = paper.has_deep_report ? "kimi" : "local";
    state.readingFocus = false;
    $("#library-view").classList.add("hidden");
    $("#detail-view").classList.remove("hidden");
    $("#detail-shell").innerHTML = detailHtml(paper);
    window.scrollTo({ top: 0 });
    document.querySelectorAll("[data-detail-tab]").forEach(button => {
      button.addEventListener("click", () => { if (!button.disabled) activateDetailTab(button.dataset.detailTab, state.selected); });
    });
    $("#local-reading-button").addEventListener("click", generateLocalReading);
    $("#figure-button").addEventListener("click", extractFigures);
    $("#kimi-reading-button").addEventListener("click", generateKimiReading);
    $("#reading-mode-button").addEventListener("click", toggleReadingFocus);
    activateDetailTab(state.detailTab, paper);
    await loadKimiScope(paper);
    history.replaceState(null, "", `#paper=${paper.paper_id}`);
  } catch (error) {
    toast(error.message, true);
  }
}

async function generateLocalReading() {
  const paper = state.selected;
  if (!paper) return;
  const button = $("#local-reading-button");
  button.disabled = true;
  button.querySelector("strong").textContent = "正在定位全文证据……";
  try {
    const result = await api(`/api/papers/${paper.paper_id}/local-reading`, { method: "POST" });
    paper.has_local_report = true;
    activateDetailTab("local", paper);
    toast(`已定位 ${result.evidence_count} 条页码证据，覆盖 ${result.covered_sections.length} 个栏目`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.querySelector("strong").textContent = "重新生成证据底稿";
  }
}

async function loadKimiScope(paper) {
  const target = $("#kimi-scope");
  try {
    const scope = await api(`/api/papers/${paper.paper_id}/kimi-scope`);
    target.textContent = `${scope.notice} 当前：${scope.evidence_count} 个原文片段、${scope.formula_count} 个公式候选；模型 ${scope.model}；接口 ${scope.endpoint}。${scope.configured ? "" : " API 尚未配置完整。"}`;
  } catch (error) {
    target.textContent = `暂不能生成：${error.message}`;
  }
}

async function extractFigures() {
  const paper = state.selected;
  if (!paper) return;
  const button = $("#figure-button");
  button.disabled = true;
  button.querySelector("strong").textContent = "正在本地提取图像……";
  try {
    const data = await api(`/api/papers/${paper.paper_id}/figures/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ max_assets: 8 }),
    });
    paper.has_figures = data.total > 0;
    paper.figure_count = data.total;
    activateDetailTab("figures", paper);
    toast(`识别到 ${data.caption_count} 条图注，已提取 ${data.total} 张论文图像`);
    await loadKimiScope(paper);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.querySelector("strong").textContent = paper.has_figures ? `重新提取论文图像（${paper.figure_count}）` : "提取原图与图注";
  }
}

async function generateKimiReading() {
  const paper = state.selected;
  if (!paper) return;
  const consent = $("#kimi-consent");
  if (!consent.checked) {
    toast("请先阅读发送范围并勾选本次同意", true);
    return;
  }
  const button = $("#kimi-reading-button");
  button.disabled = true;
  button.querySelector("strong").textContent = "Kimi 正在精读（含图版与公式）……";
  try {
    const result = await api(`/api/papers/${paper.paper_id}/kimi-reading`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ consent: true, include_figures: true, max_figures: 4 }),
    });
    paper.has_deep_report = true;
    paper.has_drawio_route = true;
    consent.checked = false;
    activateDetailTab("kimi", paper);
    toast(`精读完成：${result.evidence_count} 段原文、${result.figure_count} 张图、${result.formula_count} 个公式候选`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.querySelector("strong").textContent = paper.has_deep_report ? "重新生成 Kimi 结构化精读" : "生成 Kimi 结构化精读";
  }
}

function showLibrary() {
  state.selected = null;
  state.readingFocus = false;
  $("#detail-view").classList.add("hidden");
  $("#library-view").classList.remove("hidden");
  history.replaceState(null, "", location.pathname);
  loadPapers();
}

function bindEvents() {
  document.querySelectorAll('[data-action="home"]').forEach(button => button.addEventListener("click", showLibrary));
  $("#all-teachers").addEventListener("click", () => {
    state.teacher = "";
    state.page = 1;
    loadTeachers();
    loadPapers();
  });
  let searchTimer;
  $("#search-input").addEventListener("input", event => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      state.query = event.target.value.trim();
      state.teacher = "";
      state.page = 1;
      loadTeachers();
      loadPapers();
    }, 260);
  });
  $("#status-filter").addEventListener("change", event => {
    state.status = event.target.value;
    state.teacher = "";
    state.page = 1;
    loadTeachers();
    loadPapers();
  });
}

async function boot() {
  bindEvents();
  try {
    await Promise.all([loadStats(), loadTeachers(), loadPapers()]);
    const match = location.hash.match(/^#paper=([a-f0-9]{64})$/);
    if (match) await openPaper(match[1]);
  } catch (error) {
    toast(`页面初始化失败：${error.message}`, true);
  }
}

boot();
