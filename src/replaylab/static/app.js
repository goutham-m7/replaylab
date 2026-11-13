"use strict";
const $ = (id) => document.getElementById(id);
const state = { runs: [], detail: null, step: null, busy: false };
const json = (value) => JSON.stringify(value, null, 2);
const short = (id) => id.slice(0, 8);
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function notice(text) {
  $("notice").textContent = text;
  $("notice").hidden = !text;
}
async function api(path, body) {
  const response = await fetch(
    path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: json(body),
        },
  );
  const value = await response.json();
  if (!response.ok)
    throw new Error(
      typeof value.detail === "string" ? value.detail : json(value.detail),
    );
  return value;
}
async function action(fn) {
  if (state.busy) return;
  state.busy = true;
  notice("");
  document.querySelectorAll("button").forEach((b) => (b.disabled = true));
  try {
    await fn();
  } catch (error) {
    notice(error.message);
  } finally {
    state.busy = false;
    document.querySelectorAll("button").forEach((b) => (b.disabled = false));
  }
}
function badge(text) {
  return node("span", text, `badge ${text}`);
}
async function refresh() {
  state.runs = await api("/api/runs");
  renderRuns();
  for (const id of ["left-run", "right-run"]) {
    const old = $(id).value;
    $(id).replaceChildren(
      ...state.runs.map((run) => {
        const option = node(
          "option",
          `${short(run.id)} · ${run.workflow} · ${run.status}`,
        );
        option.value = run.id;
        return option;
      }),
    );
    if (state.runs.some((run) => run.id === old)) $(id).value = old;
  }
}
function renderRuns() {
  $("run-list").replaceChildren();
  if (!state.runs.length)
    $("run-list").append(
      node("p", "No traces yet. Run the offline demo.", "hint"),
    );
  for (const run of state.runs) {
    const button = node("button", undefined, "run-button");
    button.classList.toggle("selected", state.detail?.run.id === run.id);
    button.setAttribute(
      "aria-label",
      `${run.workflow} ${run.status} ${short(run.id)}`,
    );
    button.append(
      node("strong", run.workflow),
      badge(run.status),
      node("span", `${run.mode} / ${short(run.id)}`, "mono"),
    );
    button.addEventListener("click", () => action(() => selectRun(run.id)));
    $("run-list").append(button);
  }
}
async function selectRun(id) {
  state.detail = await api(`/api/runs/${id}`);
  state.step = null;
  const url = new URL(location.href);
  url.searchParams.set("run", id);
  history.replaceState({}, "", url);
  renderRuns();
  const { run, steps } = state.detail;
  $("step-count").textContent = `${steps.length} boundaries`;
  $("run-info").replaceChildren(
    badge(run.status),
    node("p", `${run.mode} / ${run.id}`, "mono"),
  );
  if (run.source)
    $("run-info").append(
      node(
        "p",
        `↗ From ${short(run.source)}${run.fork ? ` at step ${run.fork.position}` : " · replay"}`,
      ),
    );
  if (run.error)
    $("run-info").append(
      node("p", `${run.error.type}: ${run.error.message}`, "error-text"),
    );
  $("replay").hidden = !steps.length || run.status === "running";
  renderTimeline();
  if (steps.length) selectStep(steps.find((s) => s.error) || steps[0]);
  else {
    $("step-detail").replaceChildren(
      node("p", "No recorded boundaries in this run.", "empty"),
    );
    $("fork-form").hidden = true;
  }
}
function renderTimeline() {
  $("timeline").replaceChildren();
  for (const step of state.detail.steps) {
    const button = node("button", undefined, "step");
    button.classList.toggle("error", Boolean(step.error));
    button.classList.toggle("selected", state.step?.position === step.position);
    button.classList.toggle(
      "fork-seam",
      state.detail.run.fork?.position === step.position,
    );
    button.setAttribute("aria-label", `Step ${step.position}: ${step.name}`);
    const meta = node("div", undefined, "step-meta");
    meta.append(
      badge(step.error ? "failed" : step.origin),
      node("span", `${step.duration_ms.toFixed(2)} ms`, "mono"),
    );
    button.append(
      node(
        "span",
        `${String(step.position).padStart(2, "0")} / ${step.kind.toUpperCase()}`,
        "mono",
      ),
      node("span", step.name, "step-name"),
      meta,
    );
    button.addEventListener("click", () => {
      if (!state.busy) selectStep(step);
    });
    $("timeline").append(button);
  }
}
function detailBlock(title, value, open = false) {
  const details = node("details");
  details.open = open;
  details.append(node("summary", title), node("pre", json(value)));
  return details;
}
function selectStep(step) {
  state.step = step;
  renderTimeline();
  $("step-label").textContent = `STEP ${step.position}`;
  const blocks = [
    detailBlock("Request", step.request.payload, true),
    detailBlock("Output", step.output, true),
    detailBlock("State before → after", {
      before: step.state_before,
      after: step.state_after,
    }),
  ];
  if (step.error)
    blocks.unshift(detailBlock("Recorded error", step.error, true));
  blocks.push(
    detailBlock("Cache identity & provenance", {
      key: step.key,
      origin: step.origin,
      intervention: step.request.intervention || null,
    }),
  );
  $("step-detail").replaceChildren(...blocks);
  const isLLM = step.kind === "llm";
  $("llm-fields").hidden = !isLLM;
  $("tool-fields").hidden = isLLM;
  $("fork-form").hidden = state.detail.run.status === "running";
  if (isLLM) {
    const { model, messages, ...params } = step.request.payload;
    $("prompt").value =
      [...messages].reverse().find((m) => m.role === "user")?.content || "";
    $("model").value = model;
    $("params").value = json(params);
  } else {
    $("tool-result").value = json(step.output);
    $("after-state").value = json(step.state_after);
  }
}
async function showDiff(left, right) {
  const comparison = await api(
    `/api/diff?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`,
  );
  $("left-run").value = left;
  $("right-run").value = right;
  $("diff-count").textContent =
    `${comparison.changed} changed / ${comparison.steps.length} positions`;
  $("diff").replaceChildren();
  for (const row of comparison.steps) {
    if (row.status === "unchanged") {
      $("diff").append(
        node(
          "div",
          `${String(row.position).padStart(2, "0")} · ${row.left.name} · unchanged`,
          "unchanged-row",
        ),
      );
      continue;
    }
    const section = node("section", undefined, "diff-row");
    const heading = node("div", undefined, "diff-title");
    heading.append(
      node(
        "strong",
        `Step ${row.position} · ${row.right?.name || row.left.name}`,
      ),
      badge(row.status),
    );
    const panes = node("div", undefined, "diff-panes");
    for (const [label, step] of [
      ["ORIGINAL", row.left],
      ["FORK", row.right],
    ]) {
      const pane = node("div", undefined, "diff-pane");
      const result = step?.error
        ? `${step.error.type}: ${step.error.message}`
        : (step?.output?.choices?.[0]?.message?.content ??
          (step ? json(step.output) : "Not reached"));
      pane.append(
        node("span", label),
        node(
          "p",
          result,
          `comparison-result${step?.error ? " error-text" : ""}`,
        ),
        node(
          "pre",
          step
            ? json({
                request: step.request.payload,
                output: step.output,
                error: step.error,
                state: step.state_after,
              })
            : "Not reached",
        ),
      );
      panes.append(pane);
    }
    section.append(heading, panes);
    $("diff").append(section);
  }
}
$("demo").addEventListener("click", () =>
  action(async () => {
    const demo = await api("/api/demo", {});
    await refresh();
    await selectRun(demo.original);
    await showDiff(demo.original, demo.fork);
  }),
);
$("refresh").addEventListener("click", () => action(refresh));
$("fork-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const source = state.detail.run.id;
    const position = state.step.position;
    const changes =
      state.step.kind === "llm"
        ? {
            prompt: $("prompt").value,
            model: $("model").value,
            params: JSON.parse($("params").value),
          }
        : {
            tool_result: JSON.parse($("tool-result").value),
            state_after: JSON.parse($("after-state").value),
          };
    const run = await api(`/api/runs/${source}/fork`, {
      position,
      changes,
    });
    await refresh();
    await selectRun(run.id);
    const editedStep = state.detail.steps.find(
      (step) => step.position === position,
    );
    if (editedStep) selectStep(editedStep);
    await showDiff(source, run.id);
    if (run.status === "failed")
      notice(
        `Fork failed: ${run.error.message}. Inspect its trace to continue.`,
      );
  });
});
$("replay").addEventListener("click", () =>
  action(async () => {
    const source = state.detail.run.id;
    const run = await api(`/api/runs/${source}/replay`, {});
    await refresh();
    await selectRun(run.id);
    await showDiff(source, run.id);
  }),
);
$("compare-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(() => showDiff($("left-run").value, $("right-run").value));
});
action(async () => {
  await refresh();
  const requested = new URL(location.href).searchParams.get("run");
  if (requested) await selectRun(requested);
  else if (state.runs.length) await selectRun(state.runs[0].id);
});
