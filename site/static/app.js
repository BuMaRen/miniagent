"use strict";

// 字段名 -> 中文标题;note 字段本身已经是中文说明,这里只补标题。
const FIELD_LABELS = {
  premise: "故事简介",
  setting: "背景设定",
  protagonist: "主角设定",
  antagonist: "对手/阻力",
  hook_types: "期待的爽点类型",
  ending: "结局走向",
  genre: "题材标签",
  pov: "叙述视角",
  tone: "语气基调",
  taboos: "禁忌内容",
  extra: "其他要求",
  target_word_count: "目标字数区间",
  section_count: "分节数量",
};

const LARGE_TEXT_FIELDS = new Set(["premise", "setting", "protagonist", "antagonist", "taboos", "extra"]);

let briefFieldsMeta = [];
let tokenValue = "";
let currentRunId = null;
let eventSource = null;

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// token:输入后锁定为 ******** 展示,禁止复制
// ---------------------------------------------------------------------------

function blockCopy(el) {
  ["copy", "cut", "contextmenu"].forEach((evt) => el.addEventListener(evt, (e) => e.preventDefault()));
}

function setupTokenField() {
  const input = $("token-input");
  const locked = $("token-locked");
  const changeBtn = $("token-change-btn");

  blockCopy(input);
  blockCopy(locked);

  input.addEventListener("input", () => {
    tokenValue = input.value;
  });

  input.addEventListener("blur", () => {
    if (!tokenValue.trim()) return;
    input.style.display = "none";
    locked.style.display = "";
    changeBtn.style.display = "";
    locked.value = "********";
  });

  changeBtn.addEventListener("click", () => {
    tokenValue = "";
    input.value = "";
    locked.style.display = "none";
    changeBtn.style.display = "none";
    input.style.display = "";
    input.focus();
  });
}

// ---------------------------------------------------------------------------
// 生成参数表单:按 /api/brief-fields 动态渲染
// ---------------------------------------------------------------------------

function renderBriefFields(fields) {
  const container = $("brief-fields");
  container.innerHTML = "";

  for (const field of fields) {
    const wrap = document.createElement("div");
    wrap.className = "field";

    const label = document.createElement("label");
    label.setAttribute("for", `brief-${field.name}`);
    label.innerHTML = (FIELD_LABELS[field.name] || field.name) + (field.required ? ' <span class="required">*</span>' : "");
    wrap.appendChild(label);

    wrap.appendChild(buildFieldInput(field));

    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = field.note;
    wrap.appendChild(hint);

    container.appendChild(wrap);
  }
}

function buildFieldInput(field) {
  const id = `brief-${field.name}`;

  if (field.kind === "range") {
    const row = document.createElement("div");
    row.className = "range-row";
    const [lo, hi] = field.default;
    const min = document.createElement("input");
    min.type = "number";
    min.id = `${id}-min`;
    min.value = lo;
    const sep = document.createElement("span");
    sep.textContent = "至";
    const max = document.createElement("input");
    max.type = "number";
    max.id = `${id}-max`;
    max.value = hi;
    row.append(min, sep, max);
    return row;
  }

  if (field.kind === "int") {
    const input = document.createElement("input");
    input.type = "number";
    input.id = id;
    input.value = field.default;
    return input;
  }

  if (field.kind === "list") {
    const input = document.createElement("input");
    input.type = "text";
    input.id = id;
    input.placeholder = "用顿号或逗号分隔,如:打脸、逆袭、身份反转";
    return input;
  }

  // text
  const textarea = document.createElement("textarea");
  textarea.id = id;
  textarea.rows = LARGE_TEXT_FIELDS.has(field.name) ? 3 : 2;
  if (field.default) textarea.value = field.default;
  return textarea;
}

function collectBrief() {
  const brief = {};
  for (const field of briefFieldsMeta) {
    const id = `brief-${field.name}`;
    if (field.kind === "range") {
      const lo = parseInt($(`${id}-min`).value, 10);
      const hi = parseInt($(`${id}-max`).value, 10);
      brief[field.name] = [lo, hi];
    } else if (field.kind === "int") {
      brief[field.name] = parseInt($(id).value || "0", 10);
    } else {
      brief[field.name] = $(id).value;
    }
  }
  return brief;
}

// ---------------------------------------------------------------------------
// 确认弹窗
// ---------------------------------------------------------------------------

function showConfirm(model, baseUrl, brief) {
  const summary = $("confirm-summary");
  const premiseSnippet = (brief.premise || "").slice(0, 60) + (brief.premise.length > 60 ? "…" : "");
  summary.innerHTML = `
    <div><strong>模型:</strong>${escapeHtml(model)}</div>
    <div><strong>Base URL:</strong>${escapeHtml(baseUrl || "(使用默认地址)")}</div>
    <div><strong>故事简介:</strong>${escapeHtml(premiseSnippet)}</div>
    <div><strong>目标字数:</strong>${brief.target_word_count[0]} - ${brief.target_word_count[1]}</div>
    <div><strong>分节数量:</strong>${brief.section_count === 0 ? "自动" : brief.section_count}</div>
  `;
  $("confirm-modal").style.display = "flex";
}

function hideConfirm() {
  $("confirm-modal").style.display = "none";
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

// ---------------------------------------------------------------------------
// 提交 / 运行 / 进度
// ---------------------------------------------------------------------------

async function submitRun(model, baseUrl, brief) {
  $("submit-error").textContent = "";
  const resp = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: tokenValue, base_url: baseUrl, model, brief }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.error || "提交失败");
  }
  return data.run_id;
}

function startProgress(runId) {
  currentRunId = runId;
  $("progress-card").style.display = "";
  $("download-card").style.display = "none";
  $("progress-log").textContent = "";
  $("progress-status").textContent = "运行中…";

  const submitBtn = $("submit-btn");
  submitBtn.disabled = true;
  submitBtn.textContent = "生成中…";

  eventSource = new EventSource(`/api/run/${runId}/events`);
  eventSource.onmessage = (e) => {
    const log = $("progress-log");
    log.textContent += e.data + "\n";
    log.scrollTop = log.scrollHeight;
  };
  eventSource.addEventListener("done", (e) => {
    const exitCode = e.data;
    eventSource.close();
    finishProgress(exitCode === "0");
  });
  eventSource.onerror = () => {
    // 连接异常(非正常 done 事件触发的关闭):回退到轮询一次状态
    fetch(`/api/run/${runId}/status`)
      .then((r) => r.json())
      .then((s) => {
        if (s.status !== "running") {
          eventSource.close();
          finishProgress(s.status === "success");
        }
      });
  };
}

function finishProgress(success) {
  $("progress-status").textContent = success ? "✅ 已完成" : "❌ 运行失败(详情见上方日志或调试日志包)";

  const submitBtn = $("submit-btn");
  submitBtn.disabled = false;
  submitBtn.textContent = "生成";

  const downloadCard = $("download-card");
  downloadCard.style.display = "";
  const productLink = $("download-product");
  const debugLink = $("download-debug");
  debugLink.href = `/api/run/${currentRunId}/download/debug`;
  debugLink.classList.remove("disabled");
  if (success) {
    productLink.href = `/api/run/${currentRunId}/download/product`;
    productLink.classList.remove("disabled");
  } else {
    productLink.href = "#";
    productLink.classList.add("disabled");
  }
}

// ---------------------------------------------------------------------------
// 初始化
// ---------------------------------------------------------------------------

async function init() {
  setupTokenField();

  const resp = await fetch("/api/brief-fields");
  briefFieldsMeta = await resp.json();
  renderBriefFields(briefFieldsMeta);

  $("run-form").addEventListener("submit", (e) => {
    e.preventDefault();
    $("submit-error").textContent = "";

    const model = $("model-input").value.trim();
    if (!tokenValue.trim()) {
      $("submit-error").textContent = "请填写 API Key";
      return;
    }
    if (!model) {
      $("submit-error").textContent = "请填写模型名称";
      return;
    }
    const brief = collectBrief();
    if (!brief.premise || !brief.premise.trim()) {
      $("submit-error").textContent = "请填写故事简介(必填)";
      return;
    }

    showConfirm(model, $("base-url-input").value.trim(), brief);
  });

  $("confirm-cancel").addEventListener("click", hideConfirm);

  $("confirm-ok").addEventListener("click", async () => {
    hideConfirm();
    const model = $("model-input").value.trim();
    const baseUrl = $("base-url-input").value.trim();
    const brief = collectBrief();
    try {
      const runId = await submitRun(model, baseUrl, brief);
      startProgress(runId);
    } catch (err) {
      $("submit-error").textContent = err.message;
    }
  });
}

init();
