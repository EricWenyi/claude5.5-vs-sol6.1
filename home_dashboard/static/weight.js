/* 体重 tab: the latest weigh-in, body-fat estimate, 90-day trends, and the list of weigh-ins. */
(function () {
  "use strict";

  const LATEST_EVERY_MS = 20 * 1000;   // weigh-ins are rare, but you look right after stepping off
  const HISTORY_DAYS = 90;
  const DAY = 86400;

  // Shown under "更多指标", in this order. VeSync's opaque 0-100 "scores" are left out.
  const METRICS = [
    ["body_fat_percentage", "体脂率", "%"],
    ["body_mass_index", "BMI", ""],
    ["muscle_mass", "肌肉量", "kg"],
    ["skeletal_muscle_percentage", "骨骼肌率", "%"],
    ["fat_free_weight", "去脂体重", "kg"],
    ["subcutaneous_fat_percentage", "皮下脂肪率", "%"],
    ["visceral_fat_value", "内脏脂肪等级", ""],
    ["body_water_percentage", "体水分", "%"],
    ["protein_percentage", "蛋白质", "%"],
    ["bone_mass", "骨量", "kg"],
    ["basal_metabolic_rate", "基础代谢", "kcal"],
    ["metabolic_age", "代谢年龄", "岁"],
  ];

  let root, latest = null, points = [], offline = false;
  const timers = [];

  const one = v => (Math.round(v * 10) / 10).toFixed(1);
  const signed = v => (v > 0 ? "+" : v < 0 ? "−" : "±") + one(Math.abs(v));

  function when(ts) {
    const d = new Date(ts * 1000), now = new Date();
    const hm = d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
    const days = Math.round((new Date(now.toDateString()) - new Date(d.toDateString())) / DAY / 1000);
    if (days === 0) return `今天 ${hm}`;
    if (days === 1) return `昨天 ${hm}`;
    return `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`;
  }

  function build() {
    root.innerHTML = `
      <header class="tab-head">
        <h1 class="tab-title">体重</h1>
        <p class="tab-fresh" data-part="fresh"></p>
      </header>
      <div class="tab-cols">
        <article class="tab-col" data-kind="weight">
          <div class="reading"><span class="reading-value" data-part="weight">--</span><span class="reading-unit">kg</span></div>
          <p class="wt-change" data-part="change"></p>
          <svg class="chart" data-part="weight-chart" role="img" aria-label="最近 90 天体重"></svg>
          <div class="chart-axis"><span>90 天前</span><span>今天</span></div>
          <p class="tab-note wt-legend">点是每次称重，线是 7 天平均</p>
        </article>
        <article class="tab-col" data-kind="fat">
          <div class="reading"><span class="reading-value" data-part="fat">--</span><span class="reading-unit">%</span></div>
          <p class="wt-change" data-part="fat-sub"></p>
          <svg class="chart" data-part="fat-chart" role="img" aria-label="最近 90 天体脂率"></svg>
          <div class="chart-axis"><span>90 天前</span><span>今天</span></div>
          <p class="tab-note wt-legend" data-part="fat-legend">体脂率（估算）</p>
        </article>
      </div>
      <footer class="tab-foot">
        <button type="button" class="tab-more wt-open" data-part="open">称重记录和更多指标</button>
      </footer>
      <div class="wt-sheet" data-part="sheet" hidden>
        <div class="wt-sheet-body">
          <header class="wt-sheet-head">
            <h2>称重记录</h2>
            <button type="button" class="wt-done" data-part="close">完成</button>
          </header>
          <div class="wt-sheet-cols">
            <section>
              <ol class="wt-list" data-part="list"></ol>
            </section>
            <section>
              <h3 data-part="metrics-title">最近一次的全部指标</h3>
              <dl class="wt-metrics" data-part="metrics"></dl>
              <p class="wt-note" data-part="note"></p>
            </section>
          </div>
        </div>
      </div>`;
    part("open").addEventListener("click", openSheet);
    part("close").addEventListener("click", () => { part("sheet").hidden = true; });
  }

  const part = name => root.querySelector(`[data-part="${name}"]`);

  function renderLatest() {
    const fresh = part("fresh");
    fresh.dataset.state = offline ? "offline" : "ok";
    if (offline) {
      fresh.textContent = "连不上 Mac mini，稍后自动重试";
    } else if (!latest || latest.status === "waiting") {
      fresh.textContent = "还没有称重记录。站上秤，几秒后这里就会更新";
    } else {
      fresh.textContent = `${when(latest.ts)} 称重`;
    }
    root.toggleAttribute("data-dim", offline);
    if (!latest || latest.status !== "ok") return;

    part("weight").textContent = one(latest.weight_kg);
    const c = latest.change;
    const parts = [];
    if (c.week != null) parts.push(`<span>比上周 <b>${signed(c.week)}</b> kg</span>`);
    if (c.month != null) parts.push(`<span>比上月 <b>${signed(c.month)}</b> kg</span>`);
    part("change").innerHTML = parts.length ? parts.join("") : "记录满一周后显示变化";

    const m = latest.metrics || {};
    part("fat").textContent = m.body_fat_percentage != null ? one(m.body_fat_percentage) : "--";
    const sub = [];
    if (m.body_mass_index != null) sub.push(`<span>BMI <b>${one(m.body_mass_index)}</b></span>`);
    if (m.muscle_mass != null) sub.push(`<span>肌肉量 <b>${one(m.muscle_mass)}</b> kg</span>`);
    const offset = latest.body_fat_offset || 0;
    part("fat-legend").textContent = offset ? `体脂率（已校准 ${signed(offset)}）` : "体脂率（估算）";
    part("note").textContent = "体脂等数值是用体重、阻抗和身高、年龄、性别估算的，适合看趋势，不是医学测量。" +
      (offset ? `体脂已按参考测量（如 DEXA）校准：在秤的估算上加 ${one(offset)} 个百分点，肌肉量等随之调整。` : "");
    part("fat-sub").innerHTML = m.body_fat_percentage != null
      ? sub.join("")
      : latest.metrics ? "这次没测到阻抗（光脚站上去才能测体脂）" : "设置身高、年龄和性别后显示体脂";
  }

  function renderCharts() {
    const nowS = Date.now() / 1000;
    // Weight: a dot per weigh-in, a line for the 7-day average.
    drawChart(part("weight-chart"), nowS, points.map(p => [p[1], p[2]]), points.map(p => [p[1], p[4]]), 0.6);
    const fat = points.filter(p => p[3] != null);
    drawChart(part("fat-chart"), nowS, fat.map(p => [p[1], p[3]]), fat.map(p => [p[1], p[3]]), 0.8);
  }

  function drawChart(svg, nowS, dots, line, minPad) {
    const W = svg.clientWidth, H = svg.clientHeight;
    const t0 = nowS - HISTORY_DAYS * DAY;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    if (!dots.length || !W) { svg.innerHTML = ""; return; }
    const vals = dots.map(d => d[1]).concat(line.map(d => d[1]));
    let lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = Math.max((hi - lo) * 0.15, minPad);
    lo -= pad; hi += pad;
    const inset = 6;
    const x = t => inset + (t - t0) / (nowS - t0) * (W - 2 * inset);
    const y = v => inset + (hi - v) / (hi - lo) * (H - 2 * inset);
    const d = line.map((p, i) => (i ? "L" : "M") + x(p[0]).toFixed(1) + " " + y(p[1]).toFixed(1)).join("");
    svg.innerHTML =
      `<line class="base" x1="0" x2="${W}" y1="${H - 0.5}" y2="${H - 0.5}"/>` +
      dots.map(p => `<circle class="wt-dot" cx="${x(p[0]).toFixed(1)}" cy="${y(p[1]).toFixed(1)}" r="3"/>`).join("") +
      `<path class="line" d="${d}"/>`;
  }

  function renderSheet() {
    const list = part("list");
    const recent = points.slice(-30).reverse();
    list.innerHTML = recent.length ? "" : "<li class=\"wt-empty\">还没有称重记录</li>";
    for (const p of recent) {
      const li = document.createElement("li");
      li.innerHTML = `<span class="wt-when">${when(p[1])}</span>` +
        `<span class="wt-kg">${one(p[2])} kg</span>` +
        `<span class="wt-fat">${p[3] != null ? one(p[3]) + "%" : ""}</span>` +
        `<button type="button" class="wt-delete">删除</button>`;
      li.querySelector("button").addEventListener("click", e => confirmDelete(e.currentTarget, p[0]));
      list.appendChild(li);
    }

    const dl = part("metrics");
    const m = (latest && latest.metrics) || {};
    dl.innerHTML = METRICS.filter(([key]) => m[key] != null)
      .map(([key, label, unit]) => `<dt>${label}</dt><dd>${Number.isInteger(m[key]) ? m[key] : one(m[key])} ${unit}</dd>`)
      .join("") || "<dt>暂无</dt><dd></dd>";
    part("metrics-title").textContent = latest && latest.ts ? `${when(latest.ts)} 的全部指标` : "全部指标";
  }

  // Two taps to delete: the first arms the button for a few seconds, the second deletes.
  function confirmDelete(button, id) {
    if (button.dataset.armed) {
      HomeShell.api(`/api/weight/readings/${id}`, 8000, "DELETE").then(refresh, () => {
        button.textContent = "删除失败";
      });
      return;
    }
    button.dataset.armed = "1";
    button.textContent = "确认删除";
    setTimeout(() => { delete button.dataset.armed; button.textContent = "删除"; }, 4000);
  }

  function openSheet() {
    renderSheet();
    part("sheet").hidden = false;
  }

  async function loadLatest() {
    const before = latest && latest.id;
    try {
      latest = await HomeShell.api("/api/weight/latest");
      offline = false;
    } catch (e) {
      offline = true;
    }
    renderLatest();
    if (latest && latest.id !== before) await loadHistory();
  }

  async function loadHistory() {
    try {
      points = (await HomeShell.api(`/api/weight/history?days=${HISTORY_DAYS}`)).points;
    } catch (e) {
      offline = true;
      renderLatest();
    }
    renderCharts();
    if (!part("sheet").hidden) renderSheet();
  }

  async function refresh() {
    await loadLatest();
    await loadHistory();
  }

  HomeShell.register({
    id: "weight",
    title: "体重",
    mount(el) {
      root = el;
      build();
      addEventListener("resize", renderCharts);
    },
    show() {
      refresh();
      timers.push(setInterval(loadLatest, LATEST_EVERY_MS));
    },
    hide() {
      while (timers.length) clearInterval(timers.pop());
      part("sheet").hidden = true;
    },
  });
})();
