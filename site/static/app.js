const STAGES = [
  { id: "planning", label: "情节规划" },
  { id: "drafting", label: "正文编撰(含改稿)" },
  { id: "review", label: "审核" },
  { id: "meta", label: "标题/简介/标签" },
  { id: "cover", label: "封面文案" },
];

// 与 scenarios/essay/schemas/state.py 的 TAG_DIMENSIONS 保持一致(标签维度
// 及展示顺序:主分类/情节/角色/情绪/背景)。
const TAG_DIMENSIONS = ["category", "plot", "character", "emotion", "setting"];

const form = document.getElementById("run-form");
const logEl = document.getElementById("log");
const resultEl = document.getElementById("result");
const checkpointEl = document.getElementById("checkpoint");
const checkpointPromptEl = document.getElementById("checkpoint-prompt");
const checkpointContextEl = document.getElementById("checkpoint-context");
const checkpointFeedbackEl = document.getElementById("checkpoint-feedback");
const stageRowsEl = document.getElementById("stage-rows");
const downloadLogBtn = document.getElementById("download-log");
const downloadStateBtn = document.getElementById("download-state");
const modeTabs = document.querySelectorAll(".mode-tab");
const modePanels = {
  synopsis: document.getElementById("mode-panel-synopsis"),
  trend: document.getElementById("mode-panel-trend"),
};
const trendOptionsEl = document.getElementById("trend-options");
const trendEmptyHintEl = document.getElementById("trend-empty-hint");

let currentRunId = null;
let currentEvents = [];
let storyMode = "synopsis"; // "synopsis" | "trend" —— 两个页签只切换"故事来源"这一块,
// 模型配置、字数上下限等其余字段两种模式共用同一份表单,不受切换影响。

// -- 故事来源:自定义梗概 / 月度热点 两个页签 --------------------------------

modeTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    storyMode = tab.dataset.mode;
    modeTabs.forEach((t) => t.classList.toggle("active", t === tab));
    Object.entries(modePanels).forEach(([mode, panel]) => {
      panel.hidden = mode !== storyMode;
    });
  });
});

async function loadMonthlyTrends() {
  try {
    const resp = await fetch("/api/monthly-trends");
    const data = await resp.json();
    const options = (data && data.options) || [];
    if (options.length === 0) {
      trendEmptyHintEl.style.display = "block";
      return;
    }
    options.forEach((option, index) => {
      const label = document.createElement("label");
      label.className = "trend-option";
      label.innerHTML = `
        <input type="radio" name="trend_option" value="${index}" ${index === 0 ? "checked" : ""} />
        <div>
          <div class="trend-title"></div>
          <div class="trend-desc"></div>
        </div>
      `;
      label.querySelector(".trend-title").textContent = option.title || "";
      label.querySelector(".trend-desc").textContent = option.description || "";
      trendOptionsEl.appendChild(label);
    });
  } catch (err) {
    trendEmptyHintEl.textContent = "月度热点加载失败,可切换到「自定义梗概」继续。";
    trendEmptyHintEl.style.display = "block";
  }
}

loadMonthlyTrends();

// 根据当前页签解析出最终喂给 brief.synopsis 的文本;两种模式互斥,只有一种
// 会真正提供故事来源。返回 null 表示校验未通过(调用方负责提示用户)。
function resolveSynopsis() {
  if (storyMode === "trend") {
    const checked = trendOptionsEl.querySelector('input[name="trend_option"]:checked');
    if (!checked) {
      log("[错误] 请先在「月度热点」页签选择一个方向");
      return null;
    }
    const label = checked.closest(".trend-option");
    const title = label.querySelector(".trend-title").textContent;
    const desc = label.querySelector(".trend-desc").textContent;
    return `${title}\n\n${desc}`;
  }
  const synopsis = document.getElementById("synopsis").value.trim();
  if (!synopsis) {
    log("[错误] 请先在「自定义梗概」页签填写简介");
    return null;
  }
  return synopsis;
}

// API Key 字段:type=password 本身就会遮成圆点显示;这里再挡掉复制/右键,
// 降低被人从背后瞄一眼截屏/复制走的风险——注意这只是 UI 层面的防护,不是
// 安全边界,粘贴进来的 key 最终还是要以明文形式随请求体发给这个本地服务。
function lockKeyField(el) {
  el.addEventListener("copy", (e) => e.preventDefault());
  el.addEventListener("cut", (e) => e.preventDefault());
  el.addEventListener("contextmenu", (e) => e.preventDefault());
}

lockKeyField(document.getElementById("default_api_key"));

STAGES.forEach(({ id, label }) => {
  const row = document.createElement("div");
  row.className = "stage-row";
  row.innerHTML = `
    <div class="stage-title">${label} <span class="hint">(留空则使用默认配置)</span></div>
    <div class="row">
      <div>
        <label>模型</label>
        <input type="text" id="stage_${id}_model" />
      </div>
      <div>
        <label>Base URL</label>
        <input type="text" id="stage_${id}_base_url" />
      </div>
      <div>
        <label>API Key</label>
        <input type="password" id="stage_${id}_api_key" autocomplete="off" />
      </div>
    </div>
  `;
  stageRowsEl.appendChild(row);
  lockKeyField(row.querySelector(`#stage_${id}_api_key`));
});

function log(line) {
  logEl.textContent += line + "\n";
  logEl.scrollTop = logEl.scrollHeight;
}

function describeEvent(evt) {
  switch (evt.event) {
    case "stage_start":
      return `[开始] ${evt.name}`;
    case "stage_done":
      return `[完成] ${evt.name}`;
    case "loop_iteration":
      return `[循环] ${evt.name} 第 ${evt.iteration} 轮`;
    case "checkpoint":
      return `[人工确认] ${evt.name}: ${evt.prompt || ""}`;
    case "review_result":
      return evt.rejected ? `[审核] 打回:${evt.feedback}` : "[审核] 通过";
    case "done":
      return `[结束] status=${evt.status}${evt.message ? " - " + evt.message : ""}`;
    default:
      return JSON.stringify(evt);
  }
}

function stageCredentials(id) {
  return {
    model: document.getElementById(`stage_${id}_model`).value || null,
    base_url: document.getElementById(`stage_${id}_base_url`).value || null,
    api_key: document.getElementById(`stage_${id}_api_key`).value || null,
  };
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  resultEl.innerHTML = "";
  logEl.textContent = "";
  checkpointEl.style.display = "none";
  currentEvents = [];

  const synopsis = resolveSynopsis();
  if (synopsis === null) return;

  const stages = {};
  STAGES.forEach(({ id }) => {
    stages[id] = stageCredentials(id);
  });

  const body = {
    brief: {
      synopsis,
      min_words: Number(document.getElementById("min_words").value),
      max_words: Number(document.getElementById("max_words").value),
      category: document.getElementById("category").value,
      audience: document.getElementById("audience").value,
      human_review: document.getElementById("human_review").checked,
      cover_prompt: document.getElementById("cover_prompt").value,
      generate_cover: document.getElementById("generate_cover").checked,
    },
    default: {
      model: document.getElementById("default_model").value,
      base_url: document.getElementById("default_base_url").value,
      api_key: document.getElementById("default_api_key").value,
    },
    stages,
  };

  const resp = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  if (!resp.ok) {
    log(`[错误] ${data.error || resp.statusText}`);
    return;
  }
  currentRunId = data.run_id;
  log(`[提交] run_id=${currentRunId}`);
  streamEvents(currentRunId);
});

function streamEvents(runId) {
  const source = new EventSource(`/api/runs/${runId}/events`);
  source.onmessage = (msg) => {
    const evt = JSON.parse(msg.data);
    currentEvents.push(evt);
    log(describeEvent(evt));
    if (evt.event === "checkpoint") {
      showCheckpoint(evt);
    }
    if (evt.event === "done") {
      source.close();
      loadResult(runId, evt.status);
    }
  };
  source.onerror = () => {
    log("[连接] 事件流断开");
    source.close();
  };
}

function showCheckpoint(evt) {
  checkpointPromptEl.textContent = evt.prompt || "";
  checkpointContextEl.textContent = JSON.stringify(evt.context, null, 2);
  checkpointFeedbackEl.value = "";
  checkpointEl.style.display = "block";
}

async function answerCheckpoint(approved) {
  if (!currentRunId) return;
  await fetch(`/api/runs/${currentRunId}/checkpoint`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved, feedback: checkpointFeedbackEl.value }),
  });
  checkpointEl.style.display = "none";
}

document.getElementById("checkpoint-approve").addEventListener("click", () => answerCheckpoint(true));
document.getElementById("checkpoint-reject").addEventListener("click", () => answerCheckpoint(false));

downloadLogBtn.addEventListener("click", () => {
  if (!currentRunId || currentEvents.length === 0) return;
  const blob = new Blob([JSON.stringify(currentEvents, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${currentRunId}_events.json`;
  a.click();
  URL.revokeObjectURL(url);
});

downloadStateBtn.addEventListener("click", async () => {
  if (!currentRunId) return;
  // 直接走服务端路由:essay_state.json 是节点跑完就落一次盘的快照,不依赖
  // 浏览器这边保存的内存状态,run 卡住/失败/页面刷新过后都能单独取到。
  const resp = await fetch(`/api/runs/${currentRunId}/state`);
  if (!resp.ok) {
    log(`[错误] 状态快照获取失败: ${resp.status}`);
    return;
  }
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${currentRunId}_state.json`;
  a.click();
  URL.revokeObjectURL(url);
});

// meta 节点始终执行,标题/简介/标签理应总是有值;标题缺失时(比如中途失败、
// 还没跑到 meta 节点就中断)退回旧的占位标题,和 landing.py 的兜底逻辑一致。
function storyTitle(data) {
  const meta = data.meta || {};
  if (meta.title) return meta.title;
  const protagonist = (data.plan && data.plan.protagonist_name) || "";
  return protagonist ? `${protagonist}的故事` : "";
}

function storyTagWords(data) {
  const tags = (data.meta && data.meta.tags) || {};
  return TAG_DIMENSIONS.flatMap((dim) => tags[dim] || []);
}

// 拼出和 landing.py 的 manuscript.md 差不多的纯文本,供"复制全文"用——不
// 直接复制渲染出来的 HTML(带 <br/> 标签),复制到别处会是一堆标签垃圾。
function buildManuscriptText(data) {
  const lines = [];
  const title = storyTitle(data);
  if (title) lines.push(title, "");
  if (data.meta && data.meta.blurb) lines.push(data.meta.blurb, "");
  const tagWords = storyTagWords(data);
  if (tagWords.length > 0) lines.push(`标签:${tagWords.join(" · ")}`, "");
  (data.chapters || []).forEach((chapter) => {
    lines.push(chapter.title || "", chapter.content || "", "");
  });
  return lines.join("\n").trim();
}

async function copyToClipboard(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  // 兼容 Clipboard API 不可用的场景(非安全上下文等)。
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

async function loadResult(runId, status) {
  const resp = await fetch(`/api/runs/${runId}/result`);
  const data = await resp.json();
  if (status === "terminated_rejected") {
    resultEl.innerHTML = `<p class="terminated">任务已终止:${data.error || "情节规划连续被驳回超过允许次数"}</p>`;
    return;
  }
  if (status === "failed") {
    resultEl.innerHTML = `<p class="terminated">运行失败:${data.error || ""}</p>`;
    return;
  }

  let html = "";
  html += `<p><a class="btn" href="/api/runs/${runId}/download" download>下载正文(manuscript.md)</a> `;
  html += `<button type="button" id="copy-manuscript-btn" class="btn">复制全文</button></p>`;
  if (data.needs_manual_review) {
    html += `<p class="terminated">注意:改稿循环跑满重试次数仍未通过审核,建议人工复核。</p>`;
  }
  html += `<h3>${storyTitle(data)}</h3>`;
  if (data.meta && data.meta.blurb) {
    html += `<p class="blurb">${data.meta.blurb}</p>`;
  }
  const tagWords = storyTagWords(data);
  if (tagWords.length > 0) {
    html += `<p class="tags">${tagWords.map((tag) => `<span class="tag-pill">${tag}</span>`).join("")}</p>`;
  }
  html += `<p>全篇字数:${data.total_words}</p>`;
  if (data.cover_brief) {
    html += `<p>封面文案:${data.cover_brief}</p>`;
  }
  if (data.cover_image && data.cover_image.url) {
    html += `<img src="${data.cover_image.url}" alt="cover" />`;
  }
  (data.chapters || []).forEach((chapter) => {
    html += `<h4>${chapter.title}(${chapter.word_count} 字)</h4><p>${(chapter.content || "").replace(/\n/g, "<br/>")}</p>`;
  });
  resultEl.innerHTML = html;

  const copyBtn = document.getElementById("copy-manuscript-btn");
  copyBtn.addEventListener("click", async () => {
    try {
      await copyToClipboard(buildManuscriptText(data));
      copyBtn.textContent = "已复制";
    } catch (err) {
      copyBtn.textContent = "复制失败";
    }
    setTimeout(() => {
      copyBtn.textContent = "复制全文";
    }, 1500);
  });
}
