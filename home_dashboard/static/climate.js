/* 温湿度 tab: the bedroom's temperature and humidity at a glance, the last 24 hours, and last night. */
(function () {
  "use strict";

  const LATEST_EVERY_MS = 30 * 1000;
  const HISTORY_EVERY_MS = 5 * 60 * 1000;
  const STALE_AFTER_S = 300;   // same as the collector: older than this, the sensor is out of reach
  const GAP_S = 15 * 60;       // break the chart line across gaps longer than this

  const KINDS = [
    { key: "temp", idx: 1, field: "temp_c", unit: "°C", short: "°", range: "temp_range_c",
      words: [["偏冷", "cool"], ["舒适", "ok"], ["偏热", "warm"]] },
    { key: "hum", idx: 2, field: "humidity", unit: "%", short: "%", range: "humidity_range",
      words: [["偏干", "dry"], ["舒适", "ok"], ["偏潮", "damp"]] },
  ];

  let root, cfg = null, latest = null, points = [], offline = false;
  const timers = [];

  const one = v => (Math.round(v * 10) / 10).toFixed(1);
  const hm = d => d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });

  function nightWindow(now) {
    const start = new Date(now);
    start.setHours(22, 0, 0, 0);
    if (now.getHours() >= 22) return { label: "22:00 至今", from: start, to: now };
    start.setDate(start.getDate() - 1);
    if (now.getHours() < 7) return { label: "22:00 至今", from: start, to: now };
    const end = new Date(now);
    end.setHours(7, 0, 0, 0);
    return { label: "昨晚 22:00–7:00", from: start, to: end };
  }

  function build() {
    root.innerHTML = `
      <header class="tab-head">
        <h1 class="tab-title">卧室</h1>
        <p class="tab-fresh" data-part="fresh"></p>
      </header>
      <div class="tab-cols">
        ${KINDS.map(k => `
          <article class="tab-col" data-kind="${k.key}">
            <div class="reading"><span class="reading-value" data-part="value">--</span><span class="reading-unit">${k.unit}</span></div>
            <p class="cl-status" data-part="status"></p>
            <p class="cl-advice" data-part="advice"></p>
            <svg class="chart" data-part="chart" role="img" aria-label="过去 24 小时"></svg>
            <div class="chart-axis"><span>24 小时前</span><span>现在</span></div>
            <p class="tab-note" data-part="night"></p>
          </article>`).join("")}
      </div>
      <footer class="tab-foot">
        <a class="tab-more" href="climate-full.html">看完整记录</a>
      </footer>`;
  }

  const part = (scope, name) => scope.querySelector(`[data-part="${name}"]`);

  function renderFresh() {
    const el = part(root, "fresh");
    let text, state = "ok";
    if (offline) {
      text = "连不上 Mac mini，稍后自动重试";
      state = "offline";
    } else if (!latest || latest.status === "waiting") {
      text = "还没收到传感器信号";
      state = "waiting";
    } else {
      const age = latest.age_s;
      if (latest.status === "stale" || age > STALE_AFTER_S) {
        text = `已 ${Math.round(age / 60)} 分钟没收到传感器信号`;
        state = "stale";
      } else {
        text = age < 90 ? "刚刚更新" : `${Math.round(age / 60)} 分钟前更新`;
      }
      if (latest.battery != null && latest.battery < 20) text += `，传感器电量 ${latest.battery}%`;
    }
    el.textContent = text;
    el.dataset.state = state;
    root.toggleAttribute("data-dim", state !== "ok");
  }

  function renderReadings() {
    for (const k of KINDS) {
      const col = root.querySelector(`[data-kind="${k.key}"]`);
      const value = latest && latest[k.field] != null ? latest[k.field] : null;
      part(col, "value").textContent = value == null ? "--" : one(value);
      const status = part(col, "status");
      if (value == null || !cfg) {
        status.textContent = "";
        col.style.removeProperty("--lvl");
        continue;
      }
      const [lo, hi] = cfg[k.range];
      const [word, lvl] = value < lo ? k.words[0] : value > hi ? k.words[2] : k.words[1];
      status.textContent = word;
      col.style.setProperty("--lvl", `var(--${lvl})`);
      part(col, "advice").innerHTML = `建议 <span class="num">${one(lo)}–${one(hi)}${k.unit}</span>`;
    }
  }

  function renderHistory() {
    const now = new Date();
    const night = nightWindow(now);
    const from = night.from.getTime() / 1000, to = night.to.getTime() / 1000;
    for (const k of KINDS) {
      const col = root.querySelector(`[data-kind="${k.key}"]`);
      drawChart(part(col, "chart"), k, now.getTime() / 1000);

      const vals = points.filter(p => p[0] >= from && p[0] <= to).map(p => p[k.idx]);
      part(col, "night").innerHTML = `<span class="tab-note-label">${night.label}</span>` + (vals.length
        ? `<span>最低 <b>${one(Math.min(...vals))}${k.short}</b></span><span>最高 <b>${one(Math.max(...vals))}${k.short}</b></span>`
        : "<span>没有记录</span>");
    }
  }

  function drawChart(svg, k, nowS) {
    const W = svg.clientWidth, H = svg.clientHeight;
    const t0 = nowS - 86400;
    const pts = points.filter(p => p[0] >= t0);
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    if (!pts.length || !cfg || !W) { svg.innerHTML = ""; return; }

    const band = cfg[k.range];
    const vals = pts.map(p => p[k.idx]);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    // Keep the nearest edge of the comfortable range in view, so the line shows how far off it is.
    if (hi < band[0]) hi = band[0];
    if (lo > band[1]) lo = band[1];
    const pad = Math.max((hi - lo) * 0.15, k.key === "temp" ? 0.4 : 1.5);
    lo -= pad; hi += pad;

    const inset = 6;
    const x = t => inset + (t - t0) / 86400 * (W - 2 * inset);
    const y = v => inset + (hi - v) / (hi - lo) * (H - 2 * inset);
    const clamp = v => Math.min(hi, Math.max(lo, v));
    const bandTop = y(clamp(band[1])), bandBottom = y(clamp(band[0]));

    let d = "", prev = null;
    for (const p of pts) {
      d += (prev === null || p[0] - prev > GAP_S ? "M" : "L") + x(p[0]).toFixed(1) + " " + y(p[k.idx]).toFixed(1);
      prev = p[0];
    }
    const last = pts[pts.length - 1];
    svg.innerHTML =
      `<rect class="band" x="0" y="${bandTop.toFixed(1)}" width="${W}" height="${Math.max(0, bandBottom - bandTop).toFixed(1)}"/>` +
      `<line class="base" x1="0" x2="${W}" y1="${H - 0.5}" y2="${H - 0.5}"/>` +
      `<path class="line" d="${d}"/>` +
      `<circle class="dot" cx="${x(last[0]).toFixed(1)}" cy="${y(last[k.idx]).toFixed(1)}" r="5"/>`;
  }

  async function loadLatest() {
    try {
      if (!cfg) cfg = await HomeShell.api("/api/climate/config");
      latest = await HomeShell.api("/api/climate/latest");
      offline = false;
    } catch (e) {
      offline = true;
    }
    renderFresh();
    renderReadings();
  }

  async function loadHistory() {
    try {
      points = (await HomeShell.api("/api/climate/history?hours=24")).points;
    } catch (e) {
      offline = true;
      renderFresh();
    }
    renderHistory();
  }

  HomeShell.register({
    id: "climate",
    title: "温湿度",
    mount(el) {
      root = el;
      build();
      addEventListener("resize", renderHistory);
    },
    show() {
      loadLatest().then(loadHistory);
      timers.push(setInterval(loadLatest, LATEST_EVERY_MS));
      timers.push(setInterval(loadHistory, HISTORY_EVERY_MS));
    },
    hide() {
      while (timers.length) clearInterval(timers.pop());
    },
  });
})();
