/* Grafik çizimi: API'nin döndüğü { columns, rows, encoding } verisini
   seçilen grafik tipine göre ECharts, tablo veya KPI olarak çizer. */
(function () {
  "use strict";

  const CHART_LABELS = {
    hbar: "Yatay çubuk", bar: "Sütun", hstack: "Yatay yığılmış", stack: "Yığılmış sütun", line: "Çizgi", pie: "Halka", treemap: "Ağaç haritası",
    heatmap: "Isı haritası", table: "Tablo", kpi: "Sayı kutuları",
  };

  // ---------------------------------------------------------------- tokenlar
  function tokens() {
    const s = getComputedStyle(document.documentElement);
    const v = (n) => s.getPropertyValue(n).trim();
    return {
      surface: v("--surface"), text: v("--text-primary"), text2: v("--text-secondary"),
      muted: v("--text-muted"), grid: v("--grid"), axis: v("--axis"), border: v("--border-strong"),
      series: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--series-${i}`)),
      seq: [1, 2, 3, 4, 5, 6, 7].map((i) => v(`--seq-${i}`)),
    };
  }

  // ---------------------------------------------------------------- biçimlendirme
  const nf = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 1 });
  const nfc = new Intl.NumberFormat("tr-TR", { notation: "compact", maximumFractionDigits: 1 });
  const df = new Intl.DateTimeFormat("tr-TR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  const dfl = new Intl.DateTimeFormat("tr-TR", { dateStyle: "medium", timeStyle: "short" });

  function fmt(value, format, compact) {
    if (value === null || value === undefined || value === "") return "—";
    if (format === "datetime") return dfl.format(new Date(value));
    if (format === "text") return String(value);
    const n = Number(value);
    if (!Number.isFinite(n)) return String(value);
    switch (format) {
      case "percent": return "%" + nf.format(n);
      case "hours": return (compact ? nfc.format(n) : nf.format(Math.round(n))) + " sa";
      case "duration": {
        const m = Math.floor(n / 60), sec = Math.round(n % 60);
        return `${m}:${String(sec).padStart(2, "0")}`;
      }
      default: return compact && Math.abs(n) >= 1000 ? nfc.format(n) : nf.format(n);
    }
  }

  const isIsoDate = (v) => typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v);
  const fmtLabel = (v) => (isIsoDate(v) ? df.format(new Date(v)) : v === null ? "—" : String(v));
  // Eksen etiketleri için kısaltma (tam metin tooltip ve tabloda görünür)
  const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ---------------------------------------------------------------- veri şekilleri
  function colIndex(data, name) {
    const i = data.columns.indexOf(name);
    return i < 0 ? null : i;
  }

  /* Uzun formattaki veriyi (x, seri, değer) kategoriler ve seri dizilerine çevirir. */
  const FIXED_ORDER = ["Yurt içi", "Yurt dışı"];
  const fixedRank = (name) => { const i = FIXED_ORDER.indexOf(name); return i < 0 ? FIXED_ORDER.length : i; };

  /* Geniş formattaki veriyi (her ölçü ayrı bir sütunda) seri dizilerine çevirir. */
  function pivotWide(data, cols, format) {
    const e = data.encoding || {};
    const xi = colIndex(data, e.x) ?? 0;
    const idx = cols.map((c) => colIndex(data, c)).filter((i) => i !== null);
    const cats = data.rows.map((r) => r[xi]);
    const names = idx.map((i) => data.columns[i]);
    const values = idx.map((i) => data.rows.map((r) => (r[i] === null ? null : Number(r[i]))));
    return { cats, names, values, multi: names.length > 1, format: format || e.format || "number" };
  }

  function pivot(data) {
    const e = data.encoding || {};
    if (!e.series && Array.isArray(e.y_cols) && e.y_cols.length > 1) return pivotWide(data, e.y_cols);
    const xi = colIndex(data, e.x) ?? 0;
    const yi = colIndex(data, e.y) ?? data.columns.length - 1;
    const si = e.series ? colIndex(data, e.series) : null;
    const cats = [], catIdx = new Map();
    const names = [], nameIdx = new Map();
    for (const r of data.rows) {
      const x = r[xi];
      if (!catIdx.has(x)) { catIdx.set(x, cats.length); cats.push(x); }
      const s = si === null ? (e.y_label || data.columns[yi]) : r[si];
      if (!nameIdx.has(s)) { nameIdx.set(s, names.length); names.push(s); }
    }
    // Bilinen kavramlar her grafikte aynı renkte kalsın (renk varlığı izler, sırayı değil)
    names.sort((a, b) => fixedRank(a) - fixedRank(b));
    names.forEach((n, i) => nameIdx.set(n, i));
    const values = names.map(() => cats.map(() => null));
    for (const r of data.rows) {
      const s = si === null ? (e.y_label || data.columns[yi]) : r[si];
      values[nameIdx.get(s)][catIdx.get(r[xi])] = r[yi] === null ? null : Number(r[yi]);
    }
    return { cats, names, values, multi: si !== null, format: e.format || "number" };
  }

  // ---------------------------------------------------------------- ortak ECharts ayarları
  function baseOption(t) {
    return {
      animationDuration: 300,
      textStyle: { fontFamily: getComputedStyle(document.body).fontFamily, color: t.text2 },
      tooltip: {
        confine: true, backgroundColor: t.surface, borderColor: t.border, borderWidth: 1,
        padding: [8, 10], textStyle: { color: t.text, fontSize: 12 },
        extraCssText: "box-shadow:0 4px 16px rgba(0,0,0,.12);border-radius:8px;",
      },
    };
  }

  function axisStyle(t) {
    return {
      axisLine: { lineStyle: { color: t.axis } }, axisTick: { show: false },
      axisLabel: { color: t.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: t.grid, width: 1, type: "solid" } },
    };
  }

  function legend(t, show) {
    return show ? { top: 0, left: 0, type: "scroll", icon: "roundRect", itemWidth: 12, itemHeight: 8,
      textStyle: { color: t.text2, fontSize: 12 } } : { show: false };
  }

  // Değer önde, etiket arkada; seri anahtarı kısa bir çizgi
  function tipRow(color, name, value) {
    const key = color ? `<span style="display:inline-block;width:10px;height:2px;background:${color};vertical-align:middle;margin-right:6px"></span>` : "";
    return `<div style="display:flex;align-items:center;gap:8px;justify-content:space-between">
      <span style="font-weight:600">${esc(value)}</span><span style="opacity:.75">${key}${esc(name)}</span></div>`;
  }

  function axisTooltip(p, format, withTotal) {
    return (params) => {
      const list = (Array.isArray(params) ? params : [params]).filter((it) => it.value !== null && it.value !== undefined);
      if (!list.length) return "";
      const head = `<div style="margin-bottom:4px;opacity:.75">${esc(fmtLabel(p.cats[list[0].dataIndex]))}</div>`;
      let body = list.map((it) => tipRow(p.multi ? it.color : null, it.seriesName, fmt(it.value, format))).join("");
      if (withTotal && list.length > 1) {
        const total = list.reduce((sum, it) => sum + Number(it.value || 0), 0);
        body += `<div style="border-top:1px solid rgba(127,127,127,.25);margin-top:4px;padding-top:4px">${tipRow(null, "Toplam", fmt(total, format))}</div>`;
      }
      return head + body;
    };
  }

  // ---------------------------------------------------------------- grafik tipleri
  function barOption(data, t, horizontal, stackType, highlight) {
    const e = data.encoding || {};
    // Yığılmış grafik: şablonun önerdiği sütunlar (stack_cols) ya da uzun formattaki seriler
    const p = stackType && Array.isArray(e.stack_cols) && e.stack_cols.length > 1
      ? pivotWide(data, e.stack_cols, "number") : pivot(data);
    const stacked = (stackType || e.stacked) && p.multi;
    const many = p.cats.length > 18;
    const labels = !p.multi && !many;
    // Filtrede seçili değer (ör. sanatçı) grafikte varsa onu vurgula, diğerlerini soldur
    const hl = new Set((highlight || []).map((v) => String(v).toLocaleLowerCase("tr")));
    const isHl = (c) => hl.has(String(c).toLocaleLowerCase("tr"));
    const anyHl = hl.size > 0 && p.cats.some(isHl);
    const catAxis = {
      type: "category", data: p.cats.map(fmtLabel), ...axisStyle(t),
      splitLine: { show: false }, inverse: horizontal,
      axisLabel: {
        color: t.muted, fontSize: 11, interval: 0,
        formatter: (v) => (anyHl && isHl(v) ? `{hl|${clip(v, horizontal ? 24 : 14)}}` : clip(v, horizontal ? 24 : 14)),
        rich: { hl: { color: t.text, fontWeight: 700, fontSize: 11 } },
        rotate: !horizontal && p.cats.length > 6 ? 35 : 0,
      },
    };
    const shade = (values) => (anyHl
      ? values.map((v, j) => (isHl(p.cats[j]) ? v : { value: v, itemStyle: { opacity: 0.3 } })) : values);
    const valAxis = { type: "value", ...axisStyle(t), axisLabel: { color: t.muted, fontSize: 11,
      formatter: (v) => fmt(v, p.format, true) } };
    const radius = horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0];
    return {
      ...baseOption(t),
      color: t.series,
      legend: legend(t, p.multi),
      grid: { left: 14, right: labels && horizontal ? 56 : 16, top: p.multi ? 32 : 8, bottom: 4, containLabel: true },
      tooltip: { ...baseOption(t).tooltip, trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: "rgba(127,127,127,.08)" } },
        formatter: axisTooltip(p, p.format, stacked && p.format !== "percent") },
      xAxis: horizontal ? valAxis : catAxis,
      yAxis: horizontal ? catAxis : valAxis,
      series: p.names.map((name, i) => ({
        name, type: "bar", data: shade(p.values[i]), barMaxWidth: 24, barGap: "8%", barCategoryGap: "30%",
        stack: stacked ? "all" : undefined,
        // Yığında parçalar arasında 2px yüzey boşluğu; köşe yuvarlama yalnızca tekil çubuklarda
        itemStyle: stacked
          ? { color: t.series[i % 8], borderColor: t.surface, borderWidth: 1 }
          : { borderRadius: radius, color: t.series[i % 8] },
        emphasis: { itemStyle: { opacity: 0.85 } },
        label: { show: labels, position: horizontal ? "right" : "top", color: t.text2, fontSize: 11,
          formatter: (it) => fmt(it.value, p.format, true) },
      })),
    };
  }

  function lineOption(data, t) {
    const p = pivot(data);
    return {
      ...baseOption(t),
      color: t.series,
      legend: legend(t, p.multi),
      grid: { left: 14, right: 24, top: p.multi ? 32 : 12, bottom: 4, containLabel: true },
      tooltip: { ...baseOption(t).tooltip, trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: t.axis, width: 1 } }, formatter: axisTooltip(p, p.format) },
      xAxis: { type: "category", data: p.cats.map(fmtLabel), boundaryGap: false, ...axisStyle(t), splitLine: { show: false } },
      yAxis: { type: "value", scale: true, ...axisStyle(t),
        axisLabel: { color: t.muted, fontSize: 11, formatter: (v) => fmt(v, p.format, true) } },
      series: p.names.map((name, i) => ({
        name, type: "line", data: p.values[i], connectNulls: true, symbol: "circle", symbolSize: 8,
        lineStyle: { width: 2, cap: "round", join: "round" }, color: t.series[i % 8],
        itemStyle: { borderColor: t.surface, borderWidth: 2 },
        areaStyle: p.multi ? undefined : { opacity: 0.1 },
        endLabel: { show: !p.multi || p.names.length <= 4, color: t.text2, fontSize: 11,
          formatter: (it) => fmt(it.value, p.format, true) },
      })),
    };
  }

  function pieOption(data, t) {
    const p = pivot(data);
    let items = p.cats.map((c, i) => ({ name: fmtLabel(c), value: p.values[0][i] ?? 0 }))
      .sort((a, b) => b.value - a.value);
    if (items.length > 6) {   // en fazla 6 dilim: kalanlar "Diğer"
      const rest = items.slice(5).reduce((s, x) => s + x.value, 0);
      items = [...items.slice(0, 5), { name: "Diğer", value: rest, other: true }];
    }
    const total = items.reduce((s, x) => s + x.value, 0) || 1;
    return {
      ...baseOption(t),
      legend: { ...legend(t, true), orient: "vertical", left: 0, top: "middle",
        formatter: (name) => { const it = items.find((x) => x.name === name); return `${name}  %${nf.format(100 * it.value / total)}`; } },
      tooltip: { ...baseOption(t).tooltip, trigger: "item",
        formatter: (it) => tipRow(it.color, it.name, `${fmt(it.value, p.format)} · %${nf.format(it.percent)}`) },
      series: [{
        type: "pie", radius: ["52%", "78%"], center: ["68%", "50%"], avoidLabelOverlap: true,
        label: { show: false }, labelLine: { show: false },
        itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 4 },
        data: items.map((it, i) => ({ ...it, itemStyle: { color: it.other ? t.muted : t.series[i] } })),
      }],
    };
  }

  function treemapOption(data, t) {
    const p = pivot(data);
    return {
      ...baseOption(t),
      tooltip: { ...baseOption(t).tooltip, formatter: (it) => tipRow(null, it.name, fmt(it.value, p.format)) },
      series: [{
        type: "treemap", roam: false, nodeClick: false, breadcrumb: { show: false },
        top: 0, left: 0, right: 0, bottom: 0,
        itemStyle: { borderColor: t.surface, borderWidth: 2, gapWidth: 2, borderRadius: 4, color: t.series[0] },
        label: { show: true, color: "#ffffff", fontSize: 12, overflow: "truncate",
          formatter: (it) => `${it.name}\n${fmt(it.value, p.format, true)}` },
        emphasis: { itemStyle: { opacity: 0.85 } },
        data: p.cats.map((c, i) => ({ name: fmtLabel(c), value: p.values[0][i] ?? 0 })),
      }],
    };
  }

  function heatmapOption(data, t) {
    const e = data.encoding || {};
    const xi = colIndex(data, e.x) ?? 0, si = colIndex(data, e.series) ?? 1, yi = colIndex(data, e.y) ?? 2;
    const xs = [...new Set(data.rows.map((r) => r[xi]))];
    const ys = [...new Set(data.rows.map((r) => r[si]))];
    // Sütunları toplam değere göre sırala (en yaygın tür solda)
    const colSum = new Map(xs.map((x) => [x, 0]));
    data.rows.forEach((r) => colSum.set(r[xi], colSum.get(r[xi]) + Number(r[yi] || 0)));
    xs.sort((a, b) => colSum.get(b) - colSum.get(a));
    const xIdx = new Map(xs.map((x, i) => [x, i])), yIdx = new Map(ys.map((y, i) => [y, i]));
    const pts = data.rows.map((r) => [xIdx.get(r[xi]), yIdx.get(r[si]), r[yi] === null ? null : Number(r[yi])]);
    const vals = pts.map((p) => p[2]).filter((v) => v !== null);
    const format = e.format || "number";
    return {
      ...baseOption(t),
      grid: { left: 14, right: 8, top: 8, bottom: 52, containLabel: true },
      tooltip: { ...baseOption(t).tooltip, formatter: (it) =>
        `<div style="margin-bottom:4px;opacity:.75">${esc(fmtLabel(ys[it.value[1]]))}</div>` +
        tipRow(null, fmtLabel(xs[it.value[0]]), fmt(it.value[2], format)) },
      xAxis: { type: "category", data: xs.map(fmtLabel), ...axisStyle(t), splitLine: { show: false },
        axisLabel: { color: t.muted, fontSize: 11, interval: 0, rotate: xs.length > 8 ? 35 : 0, formatter: (v) => clip(v, 14) } },
      yAxis: { type: "category", data: ys.map(fmtLabel), ...axisStyle(t), splitLine: { show: false }, inverse: true,
        axisLabel: { color: t.muted, fontSize: 11, formatter: (v) => clip(v, 20) } },
      visualMap: {
        min: Math.min(0, ...vals), max: Math.max(1, ...vals), calculable: false, orient: "horizontal",
        left: "center", bottom: 0, itemWidth: 10, itemHeight: 160, inRange: { color: t.seq },
        text: [fmt(Math.max(1, ...vals), format, true), fmt(Math.min(0, ...vals), format, true)], textGap: 8,
        textStyle: { color: t.muted, fontSize: 11 }, formatter: (v) => fmt(v, format, true),
      },
      series: [{ type: "heatmap", data: pts,
        itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 2 },
        emphasis: { itemStyle: { borderColor: t.text, borderWidth: 1 } } }],
    };
  }

  // ---------------------------------------------------------------- HTML görünümler
  function renderTable(el, data, opts = {}) {
    const e = data.encoding || {};
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    const table = document.createElement("table");
    table.className = "data";
    const numeric = data.columns.map((_, i) => data.rows.length > 0 && data.rows.every((r) => r[i] === null || typeof r[i] === "number"));
    const colFormat = (c, i) => (c === e.y ? e.format : numeric[i] ? "number" : null);
    let sortCol = null, sortDir = 1;

    const thead = table.createTHead().insertRow();
    data.columns.forEach((c, i) => {
      if (c === "format") return;
      const th = document.createElement("th");
      th.textContent = c;
      th.tabIndex = 0;
      if (numeric[i]) th.className = "num";
      const sort = () => {
        sortDir = sortCol === i ? -sortDir : numeric[i] ? -1 : 1;
        sortCol = i;
        thead.querySelectorAll("th").forEach((h) => h.removeAttribute("aria-sort"));
        th.setAttribute("aria-sort", sortDir > 0 ? "ascending" : "descending");
        fill();
      };
      th.addEventListener("click", sort);
      th.addEventListener("keydown", (ev) => { if (ev.key === "Enter") sort(); });
      thead.appendChild(th);
    });
    const tbody = table.createTBody();
    function fill() {
      tbody.textContent = "";
      const rows = [...data.rows];
      if (sortCol !== null) rows.sort((a, b) => {
        const x = a[sortCol], y = b[sortCol];
        if (x === y) return 0;
        if (x === null) return 1;
        if (y === null) return -1;
        return (x > y ? 1 : -1) * sortDir;
      });
      const xi = colIndex(data, e.x);
      const pick = typeof opts.onPick === "function" && xi !== null;
      if (pick) table.classList.add("pickable");
      for (const r of rows) {
        const tr = tbody.insertRow();
        if (pick) tr.addEventListener("click", () => opts.onPick(r[xi]));
        data.columns.forEach((c, i) => {
          if (c === "format") return;
          const td = tr.insertCell();
          const f = data.columns[2] === "format" && i === 1 ? r[2] : colFormat(c, i);
          td.textContent = f ? fmt(r[i], f) : fmtLabel(r[i]);
          if (numeric[i]) td.className = "num";
        });
      }
    }
    fill();
    wrap.appendChild(table);
    el.appendChild(wrap);
    return { resize() {}, dispose() { wrap.remove(); } };
  }

  function renderKpi(el, data) {
    const box = document.createElement("div");
    box.className = "kpis";
    const isKpiShape = data.columns[2] === "format";
    const items = isKpiShape ? data.rows : data.rows.slice(0, 8).map((r) => [fmtLabel(r[0]), r[r.length - 1], "number"]);
    for (const [label, value, format] of items) {
      const k = document.createElement("div");
      k.className = "kpi";
      const l = document.createElement("div");
      l.className = "kpi-label";
      l.textContent = label;
      const v = document.createElement("div");
      v.className = "kpi-value" + (format === "datetime" ? " small" : "");
      v.textContent = fmt(value, format, true);
      v.title = fmt(value, format);
      k.append(l, v);
      box.appendChild(k);
    }
    el.appendChild(box);
    return { resize() {}, dispose() { box.remove(); } };
  }

  // ---------------------------------------------------------------- giriş noktası
  /* opts.onPick(value): grafikte bir çubuğa / dilime / tablo satırına tıklanınca X değeriyle çağrılır */
  function render(el, type, data, opts = {}) {
    el.textContent = "";
    if (!data.rows || data.rows.length === 0) {
      const m = document.createElement("div");
      m.className = "w-message";
      m.textContent = "Bu seçim için veri yok.";
      el.appendChild(m);
      return { resize() {}, dispose() { m.remove(); } };
    }
    if (type === "table") return renderTable(el, data, opts);
    if (type === "kpi") return renderKpi(el, data);

    const t = tokens();
    const hl = opts.highlight;
    const option = type === "hbar" ? barOption(data, t, true, false, hl)
      : type === "bar" ? barOption(data, t, false, false, hl)
      : type === "hstack" ? barOption(data, t, true, true, hl)
      : type === "stack" ? barOption(data, t, false, true, hl)
      : type === "line" ? lineOption(data, t)
      : type === "pie" ? pieOption(data, t)
      : type === "treemap" ? treemapOption(data, t)
      : type === "heatmap" ? heatmapOption(data, t)
      : barOption(data, t, true);

    const box = document.createElement("div");
    box.className = "chart";
    el.appendChild(box);
    const chart = echarts.init(box, null, { renderer: "svg" });
    const pickable = typeof opts.onPick === "function" && ["hbar", "bar", "hstack", "stack", "pie", "treemap"].includes(type);
    (option.series || []).forEach((s) => { s.cursor = pickable ? "pointer" : "default"; });
    chart.setOption(option);
    if (pickable) {
      const e = data.encoding || {};
      const xi = colIndex(data, e.x) ?? 0;
      const raw = new Map(data.rows.map((r) => [fmtLabel(r[xi]), r[xi]]));
      chart.on("click", (params) => {
        if (params.name && raw.has(params.name) && params.name !== "Diğer") opts.onPick(raw.get(params.name));
      });
    }
    return { resize: () => chart.resize(), dispose: () => { chart.dispose(); box.remove(); } };
  }

  window.Charts = { render, fmt, CHART_LABELS };
})();
