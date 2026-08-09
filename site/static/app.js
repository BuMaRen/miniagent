const STAGES = [
  { id: "planning", label: "情节规划" },
  { id: "drafting", label: "正文编撰(含改稿)" },
  { id: "review", label: "审核" },
  { id: "cover", label: "封面文案" },
];

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

let currentRunId = null;
let currentEvents = [];

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

  const stages = {};
  STAGES.forEach(({ id }) => {
    stages[id] = stageCredentials(id);
  });

  const body = {
    brief: {
      synopsis: document.getElementById("synopsis").value,
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
  html += `<p><a class="btn" href="/api/runs/${runId}/download" download>下载正文(manuscript.md)</a></p>`;
  if (data.needs_manual_review) {
    html += `<p class="terminated">注意:改稿循环跑满重试次数仍未通过审核,建议人工复核。</p>`;
  }
  html += `<h3>${(data.plan && data.plan.protagonist_name) || ""}的故事</h3>`;
  html += `<p>全篇字数:${data.total_words}</p>`;
  if (data.review && data.review.audience_feedback) {
    html += `<p>受众评价:${data.review.audience_feedback}</p>`;
  }
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
}
