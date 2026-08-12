const STAGES = [
  { id: "planning", label: "情节规划" },
  { id: "drafting", label: "正文编撰(含改稿)" },
  { id: "review", label: "审核" },
  { id: "meta", label: "标题/简介/标签" },
  { id: "cover", label: "封面文案" },
];

// 默认模型/Base URL 的兜底值:input 只用 placeholder 展示(灰色、不占实际
// value,用户一开始输入就会消失),真正提交时如果用户没填就退回这两个值,
// 不需要用户手动填一遍。API Key 没有默认值(不能替用户填密钥),仍然必填。
const DEFAULT_MODEL = "gpt-5.6-luna";
const DEFAULT_BASE_URL = "https://openrouter.ai/api/v1";

// 与 scenarios/essay/schemas/state.py 的 TAG_DIMENSIONS 保持一致(标签维度
// 及展示顺序:主分类/情节/角色/情绪/背景)。
const TAG_DIMENSIONS = ["category", "plot", "character", "emotion", "setting"];

// 与 site/server.py 的 TERMINAL_STATUSES 保持一致。interrupted 是服务器
// 重启时从磁盘重新挂载出来、没跑完的历史任务专用状态(见 server.py 的
// _rebuild_run_from_disk)。
const TERMINAL_STATUSES = new Set(["success", "failed", "terminated_rejected", "interrupted"]);

const PHASE_LABELS = { planning: "情节规划", drafting: "正文编撰", review: "审核", meta: "标题/标签", cover: "封面" };

const form = document.getElementById("run-form");
const createErrorEl = document.getElementById("create-error");
const viewCreateEl = document.getElementById("view-create");
const viewTaskEl = document.getElementById("view-task");
const taskTitleEl = document.getElementById("task-title");
const taskConfigEl = document.getElementById("task-config");
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
const newBallEl = document.getElementById("task-rail-new");
const taskRailScrollEl = document.getElementById("task-rail-scroll");
const taskRailListEl = document.getElementById("task-rail-list");

let currentRunId = null;
let currentEvents = [];
let storyMode = "synopsis"; // "synopsis" | "trend" —— 两个页签只切换"故事来源"这一块,
// 模型配置、字数上下限等其余字段两种模式共用同一份表单,不受切换影响。

// ===========================================================================
// 左侧任务栏:一个纵向的"轮盘"任务列表
// ---------------------------------------------------------------------------
// - 每个任务是一个小圆球,颜色随运行状态变化(进行中/成功/失败)。
// - 球下面串一排更小的圆点,表示这个任务当前跑到哪个阶段(pending/active/
//   done/error),数据来自 GET /api/runs 的 phase_order + phases。
// - 任务栏本身是一个原生可滚动容器(鼠标滚轮/拖动都是浏览器免费给的),球的
//   透明度/缩放按"离容器竖直中心多远"实时计算,离中心越远越淡——这就是
//   "居中的高亮、往上往下淡出"的效果,不需要手写虚拟滚动。
// - 距离容器中心最近的球会被打上 .centered(描边高亮);这与"点击选中"是两
//   件事——.selected(整球蓝底 + 右侧标签)只由点击驱动,与滚动位置无关。
// - 最上方固定一个"+"球(不参与滚动),用来切回"新建任务"表单。
// ===========================================================================

let tasksById = {};
let selectedRunId = "new"; // "new" | 具体 run_id
let hoveredRunId = null; // 当前鼠标悬停在哪个球上;没有悬停时为 null
let hasAutoCentered = false;
let activeEventSource = null;

function closeActiveStream() {
  if (activeEventSource) {
    activeEventSource.close();
    activeEventSource = null;
  }
}

function renderPhaseDots(phaseOrder, phases) {
  return (phaseOrder || [])
    .map((phase) => {
      const state = (phases && phases[phase]) || "pending";
      const label = PHASE_LABELS[phase] || phase;
      return `<span class="phase-dot phase-${state}" title="${label}:${state}"></span>`;
    })
    .join("");
}

function renderTaskRail(runs) {
  tasksById = {};
  const previousScrollTop = taskRailScrollEl.scrollTop;
  taskRailListEl.innerHTML = "";
  // runs 已经是服务端按创建时间升序排好的(见 site/server.py 的
  // _list_runs_payload),球里标的序号就是它在这个列表里的位置(从 1 开始)。
  runs.forEach((run, index) => {
    tasksById[run.run_id] = run;
    const ball = document.createElement("div");
    ball.className = `task-ball status-${run.status}`;
    ball.dataset.runId = run.run_id;
    ball.classList.toggle("selected", run.run_id === selectedRunId);
    ball.title = run.title || "未命名任务";
    ball.innerHTML = `
      <div class="ball-row"><div class="ball-circle"></div></div>
      <div class="phase-dots">${renderPhaseDots(run.phase_order, run.phases)}</div>
    `;
    ball.querySelector(".ball-circle").textContent = String(index + 1);
    ball.addEventListener("click", () => selectTask(run.run_id));
    // 悬停任意一个球(不管选没选中)都临时展开显示它的完整名称,松开鼠标
    // 后收回;跟"点击选中"是两件独立的事,见 updateFloatingLabel。
    ball.addEventListener("mouseenter", () => {
      hoveredRunId = run.run_id;
      updateFloatingLabel();
    });
    ball.addEventListener("mouseleave", () => {
      if (hoveredRunId === run.run_id) hoveredRunId = null;
      updateFloatingLabel();
    });
    taskRailListEl.appendChild(ball);
  });
  newBallEl.classList.toggle("selected", selectedRunId === "new");
  layoutTaskRailPadding();
  taskRailScrollEl.scrollTop = previousScrollTop; // 重建 DOM 不应该打断用户已有的滚动位置
  updateWheelEffect();
  updateFloatingLabel();

  if (!hasAutoCentered && runs.length > 0) {
    hasAutoCentered = true;
    const running = runs.find((r) => r.status === "running" || r.status === "awaiting_checkpoint");
    const target = running || runs[runs.length - 1];
    requestAnimationFrame(() => centerBall(target.run_id));
  }
}

// 让第一个/最后一个球也能被拉到容器竖直中心:上下各留半个容器高度的空白。
function layoutTaskRailPadding() {
  const half = Math.max(taskRailScrollEl.clientHeight / 2, 0);
  taskRailListEl.style.paddingTop = `${half}px`;
  taskRailListEl.style.paddingBottom = `${half}px`;
}

function updateWheelEffect() {
  const containerRect = taskRailScrollEl.getBoundingClientRect();
  const centerY = containerRect.top + containerRect.height / 2;
  const maxDist = containerRect.height / 2 || 1;
  let closestBall = null;
  let closestDist = Infinity;

  taskRailListEl.querySelectorAll(".task-ball").forEach((ball) => {
    const ballRect = ball.getBoundingClientRect();
    const ballCenterY = ballRect.top + ballRect.height / 2;
    const dist = Math.abs(ballCenterY - centerY);
    const t = Math.min(dist / maxDist, 1);
    ball.style.opacity = String(Math.max(1 - t * 0.85, 0.15));
    ball.style.transform = `scale(${Math.max(1 - t * 0.3, 0.7)})`;
    ball.classList.remove("centered");
    if (dist < closestDist) {
      closestDist = dist;
      closestBall = ball;
    }
  });
  if (closestBall) closestBall.classList.add("centered");
}

// 任务名称标签是页面上唯一一个、position:fixed 的浮层(见 index.html 里
// #floating-ball-label 的注释:放在球体内部会被任务栏的纵向滚动裁掉横向
// 溢出的部分)。两种触发方式,悬停优先于选中:
// - 悬停某个球(不管是不是当前选中的那个):展开显示这个球的完整名称。
// - 没有悬停、但有球被选中:退回显示选中球的名称,默认只露出前几个字、
//   剩下的用 mask 渐隐淡出(CSS 的 .expanded 类控制展开/收起)。
// - 两者都没有:完全不显示。
// 每次任务栏重绘、每次滚动、每次窗口缩放都要重新算一次该出现在屏幕的什么
// 位置;球滚出可视区域时就隐藏。
const floatingLabelEl = document.getElementById("floating-ball-label");

function updateFloatingLabel() {
  const targetRunId = hoveredRunId || (selectedRunId !== "new" ? selectedRunId : null);
  const targetBall = targetRunId
    ? taskRailListEl.querySelector(`.task-ball[data-run-id="${CSS.escape(targetRunId)}"]`)
    : null;
  if (!targetBall) {
    floatingLabelEl.style.display = "none";
    return;
  }
  const circleRect = targetBall.querySelector(".ball-circle").getBoundingClientRect();
  const containerRect = taskRailScrollEl.getBoundingClientRect();
  const visible = circleRect.bottom > containerRect.top && circleRect.top < containerRect.bottom;
  if (!visible) {
    floatingLabelEl.style.display = "none";
    return;
  }
  const info = tasksById[targetRunId];
  floatingLabelEl.textContent = (info && info.title) || "未命名任务";
  floatingLabelEl.classList.toggle("expanded", targetRunId === hoveredRunId);
  floatingLabelEl.style.display = "block";
  floatingLabelEl.style.top = `${circleRect.top + circleRect.height / 2}px`;
  floatingLabelEl.style.left = `${circleRect.right + 8}px`;
}

let wheelEffectScheduled = false;
function scheduleWheelEffect() {
  if (wheelEffectScheduled) return;
  wheelEffectScheduled = true;
  requestAnimationFrame(() => {
    wheelEffectScheduled = false;
    updateWheelEffect();
    updateFloatingLabel();
  });
}

taskRailScrollEl.addEventListener("scroll", scheduleWheelEffect);
window.addEventListener("resize", () => {
  layoutTaskRailPadding();
  scheduleWheelEffect();
});

function centerBall(runId) {
  const ball = taskRailListEl.querySelector(`.task-ball[data-run-id="${CSS.escape(runId)}"]`);
  if (!ball) return;
  // 用 getBoundingClientRect() 算视口坐标差,再加到当前 scrollTop 上——不用
  // offsetTop:#task-rail 是 position:sticky,可能被浏览器当成 .task-ball 的
  // offsetParent,offsetTop 就不再是"相对 #task-rail-list 顶部"这么直观了,
  // rect 差值法不依赖 offsetParent 链,总是准的。
  const ballRect = ball.getBoundingClientRect();
  const containerRect = taskRailScrollEl.getBoundingClientRect();
  const ballCenterY = ballRect.top + ballRect.height / 2;
  const containerCenterY = containerRect.top + containerRect.height / 2;
  taskRailScrollEl.scrollTop += ballCenterY - containerCenterY;
  scheduleWheelEffect();
}

async function refreshTaskList() {
  try {
    const resp = await fetch("/api/runs");
    const data = await resp.json();
    renderTaskRail((data && data.runs) || []);
  } catch (err) {
    // 轮询失败不弹错,下一轮 2s 后自然重试;任务栏保留上一次拿到的数据即可。
  }
}

refreshTaskList();
setInterval(refreshTaskList, 2000);

// -- 选中一个球:切主区域视图 + (对运行中任务)接上实时事件流 ----------------

function selectTask(runId) {
  selectedRunId = runId;
  taskRailListEl.querySelectorAll(".task-ball").forEach((ball) => {
    ball.classList.toggle("selected", ball.dataset.runId === runId);
  });
  newBallEl.classList.toggle("selected", runId === "new");
  updateFloatingLabel();

  if (runId === "new") {
    closeActiveStream();
    viewTaskEl.hidden = true;
    viewCreateEl.hidden = false;
    return;
  }
  viewCreateEl.hidden = true;
  viewTaskEl.hidden = false;
  showTaskView(runId);
}

newBallEl.addEventListener("click", () => selectTask("new"));

function renderTaskConfig(brief) {
  if (!brief) return "";
  const rows = [
    ["简介", brief.synopsis],
    ["字数范围", `${brief.min_words} ~ ${brief.max_words} 字`],
    ["类别", brief.category || "(未填,由 AI 判断)"],
    ["受众", brief.audience || "(未填,由 AI 推断)"],
    ["人工审核", brief.human_review ? "已开启" : "未开启"],
    ["生成封面", brief.generate_cover ? "已开启" : "未开启"],
  ];
  if (brief.generate_cover && brief.cover_prompt) {
    rows.push(["封面要求", brief.cover_prompt]);
  }
  return rows.map(([label, value]) => `<p><strong>${label}:</strong>${value}</p>`).join("");
}

async function showTaskView(runId) {
  closeActiveStream();
  currentRunId = runId;
  currentEvents = [];
  logEl.textContent = "";
  resultEl.innerHTML = "";
  checkpointEl.style.display = "none";
  taskTitleEl.textContent = "加载中…";
  taskConfigEl.innerHTML = "";

  const resp = await fetch(`/api/runs/${runId}/status`);
  if (!resp.ok || currentRunId !== runId) {
    // 请求飞回来之前用户可能已经点了别的任务;这时不该用过期数据覆盖当前视图。
    if (currentRunId === runId) taskTitleEl.textContent = "任务不存在或已被清理";
    return;
  }
  const info = await resp.json();
  if (currentRunId !== runId) return; // 同上,防止竞态覆盖

  taskTitleEl.textContent = info.title || "未命名任务";
  taskConfigEl.innerHTML = renderTaskConfig(info.brief);

  if (TERMINAL_STATUSES.has(info.status)) {
    loadResult(runId, info.status);
  } else {
    // 还在跑(或在等人工确认):SSE 每次新连接都会从头重放这个 run 的完整
    // 事件历史(见 site/server.py 的 _serve_events),所以不管什么时候点进来
    // 都能看到从头到现在的完整日志,不会漏看之前发生的事。
    streamEvents(runId);
  }
}

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
      showCreateError("请先在「月度热点」页签选择一个方向");
      return null;
    }
    const label = checked.closest(".trend-option");
    const title = label.querySelector(".trend-title").textContent;
    const desc = label.querySelector(".trend-desc").textContent;
    return `${title}\n\n${desc}`;
  }
  const synopsis = document.getElementById("synopsis").value.trim();
  if (!synopsis) {
    showCreateError("请先在「自定义梗概」页签填写简介");
    return null;
  }
  return synopsis;
}

function showCreateError(message) {
  createErrorEl.textContent = message ? `[错误] ${message}` : "";
  createErrorEl.style.display = message ? "block" : "none";
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
  showCreateError("");

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
      model: document.getElementById("default_model").value || DEFAULT_MODEL,
      base_url: document.getElementById("default_base_url").value || DEFAULT_BASE_URL,
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
    showCreateError(data.error || resp.statusText);
    return;
  }

  // 新任务提交成功:刷新任务栏拿到它的球,自动选中 + 滚到居中,主区域立刻
  // 切到这个任务的实时视图——不需要用户再手动去任务栏里找它。
  await refreshTaskList();
  selectTask(data.run_id);
  requestAnimationFrame(() => centerBall(data.run_id));
});

function streamEvents(runId) {
  closeActiveStream();
  const source = new EventSource(`/api/runs/${runId}/events`);
  activeEventSource = source;
  source.onmessage = (msg) => {
    const evt = JSON.parse(msg.data);
    currentEvents.push(evt);
    log(describeEvent(evt));
    if (evt.event === "checkpoint") {
      showCheckpoint(evt);
    }
    if (evt.event === "done") {
      source.close();
      if (activeEventSource === source) activeEventSource = null;
      loadResult(runId, evt.status);
      refreshTaskList(); // 立刻拉一次任务栏,不用等 2s 的轮询周期才看到球变色
    }
  };
  source.onerror = () => {
    log("[连接] 事件流断开");
    source.close();
    if (activeEventSource === source) activeEventSource = null;
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
  if (currentRunId !== runId) return; // 用户已经切到别的任务,不要用过期数据覆盖

  if (status === "terminated_rejected") {
    resultEl.innerHTML = `<p class="terminated">任务已终止:${data.error || "情节规划连续被驳回超过允许次数"}</p>`;
    return;
  }
  if (status === "interrupted") {
    resultEl.innerHTML = `<p class="terminated">${data.error || "服务器重启导致该任务被中断,无法继续。"}</p>`;
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
  if (data.meta && data.meta.preview_ratio) {
    html += `<p>建议试读比例:${(data.meta.preview_ratio * 100).toFixed(0)}%(超过此比例需看广告解锁)</p>`;
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
