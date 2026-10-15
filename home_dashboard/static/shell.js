/* Home dashboard shell: clock, time-of-day phase, tab bar, and a small helper for tabs to call the API.
 *
 * A tab registers itself with HomeShell.register({id, title, mount(panel), show(), hide()}).
 * mount() runs once; show()/hide() run when the tab is selected or left.
 */
(function () {
  "use strict";

  const tabs = [];
  let active = null;

  // Night dims the whole page so the screen doesn't light up the bedroom.
  const PHASES = [
    [5.5, "dawn"], [7.5, "day"], [17, "dusk"], [21.5, "night"],
  ];

  function phaseAt(d) {
    const h = d.getHours() + d.getMinutes() / 60;
    let phase = "night";
    for (const [start, name] of PHASES) if (h >= start) phase = name;
    return phase;
  }

  const timeFmt = new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  const dateFmt = new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "long" });

  let lastMinute = -1;
  function tick() {
    const now = new Date();
    const minute = Math.floor(now.getTime() / 60000);
    if (minute === lastMinute) return;
    lastMinute = minute;

    document.getElementById("clock-time").textContent = timeFmt.format(now);
    document.getElementById("clock-date").textContent = dateFmt.format(now).replace("星期", " 星期");

    const phase = phaseAt(now);
    const root = document.documentElement;
    root.dataset.phase = phase;
    if (phase === "night") root.dataset.night = ""; else delete root.dataset.night;

    // Move everything by a few pixels each minute so an always-on screen never shows the same image for hours.
    const step = minute % 9;
    root.style.setProperty("--shift-x", ((step % 3) - 1) * 3 + "px");
    root.style.setProperty("--shift-y", (Math.floor(step / 3) - 1) * 3 + "px");

    // Reload once a night to pick up changes to the dashboard itself.
    if (now.getHours() === 4 && now.getMinutes() === 0) location.reload();
  }

  function select(id) {
    const tab = tabs.find(t => t.id === id) || tabs[0];
    if (!tab || tab === active) return;
    if (active) { active.hide && active.hide(); active.el.hidden = true; }
    active = tab;
    tab.el.hidden = false;
    tab.show && tab.show();
    for (const b of document.querySelectorAll("#tabs button")) {
      b.setAttribute("aria-selected", String(b.dataset.tab === tab.id));
    }
    try { localStorage.setItem("home.tab", tab.id); } catch (e) { /* private mode: fine */ }
  }

  window.HomeShell = {
    register(tab) { tabs.push(tab); },

    /** Call a JSON API path (GET unless `method` says otherwise), rejecting after `timeoutMs`. */
    async api(path, timeoutMs = 8000, method = "GET") {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), timeoutMs);
      try {
        const res = await fetch(path, { method, signal: ctl.signal, cache: "no-store" });
        if (!res.ok) throw new Error(path + " → HTTP " + res.status);
        return await res.json();
      } finally {
        clearTimeout(timer);
      }
    },

    async start() {
      tick();
      setInterval(tick, 1000);

      // The server lists the tabs it has data for (e.g. 体重 only when a scale is configured), in order.
      let enabled = null;
      try {
        enabled = (await this.api("/api/home")).tabs.map(t => t.id);
      } catch (e) { /* server not reachable yet: show every tab; each one reports the problem */ }
      if (enabled) {
        tabs.splice(0, tabs.length, ...enabled.map(id => tabs.find(t => t.id === id)).filter(Boolean));
      }

      const panel = document.getElementById("tab-panel");
      const nav = document.getElementById("tabs");
      for (const tab of tabs) {
        tab.el = document.createElement("section");
        tab.el.className = "tab tab-" + tab.id;
        tab.el.hidden = true;
        tab.el.setAttribute("aria-label", tab.title);
        panel.appendChild(tab.el);
        tab.mount(tab.el);

        const b = document.createElement("button");
        b.type = "button";
        b.textContent = tab.title;
        b.dataset.tab = tab.id;
        b.setAttribute("role", "tab");
        b.addEventListener("click", () => select(tab.id));
        nav.appendChild(b);
      }
      // A link like /#weight opens that tab; otherwise the one used last.
      let saved = null;
      try { saved = localStorage.getItem("home.tab"); } catch (e) { /* ignore */ }
      select(location.hash.slice(1) || saved);
      addEventListener("hashchange", () => select(location.hash.slice(1)));
    },
  };
})();
