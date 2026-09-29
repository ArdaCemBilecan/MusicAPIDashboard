/* Music Dashboard arayüzü: sürükle-bırak pano, widget kütüphanesi,
   widget ayar penceresi ve dashboard kayıt işlemleri. */
(function () {
  "use strict";

  const $ = (s, root = document) => root.querySelector(s);
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* yok say */ } },
  };

  const state = {
    meta: null,
    dashboards: [],
    current: null,        // { id, name, widgets }
    views: new Map(),     // widget id -> { el, body, view, data, tableMode }
    editing: false,
    grid: null,
    loadingDashboard: false,
  };

  // ------------------------------------------------------------------ API
  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" }, ...opts,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    if (res.status === 204) return null;
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(json.detail || `İstek başarısız (${res.status})`);
    return json;
  }

  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => t.classList.remove("show"), 2600);
  }

  const uid = () => "w" + Math.random().toString(36).slice(2, 9);
  const templateOf = (w) => (w.source.type === "template" ? state.meta.templates.find((t) => t.id === w.source.template) : null);

  // ------------------------------------------------------------------ tema
  function applyTheme(theme) {
    if (theme) document.documentElement.setAttribute("data-theme", theme);
    else document.documentElement.removeAttribute("data-theme");
  }
  function currentTheme() {
    const attr = document.documentElement.getAttribute("data-theme");
    if (attr) return attr;
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function toggleTheme() {
    const next = currentTheme() === "dark" ? "light" : "dark";
    applyTheme(next);
    store.set("md-theme", next);
    rerenderAll();
  }

  // ------------------------------------------------------------------ kütüphane
  function buildLibrary() {
    const body = $("#libraryBody");
    body.textContent = "";
    const groups = [{ key: "custom", title: "Kendi grafiğini oluştur", items: [
      { id: "__custom__", title: "Özel sorgu", description: "Veri kaynağı, eksen, ölçü, oran ve filtreleri kendin seç.",
        size: { w: 6, h: 5 }, custom: true },
      { id: "__sql__", title: "SQL sorgusu", description: "Kendi SELECT sorgunu yaz, sonucu grafiğe çevir (salt okunur).",
        size: { w: 6, h: 5 }, custom: true },
    ] }];
    for (const [key, title] of Object.entries(state.meta.categories)) {
      groups.push({ key, title, items: state.meta.templates.filter((t) => t.category === key) });
    }
    for (const g of groups) {
      if (!g.items.length) continue;
      const sec = document.createElement("section");
      sec.className = "lib-group";
      const h = document.createElement("h3");
      h.textContent = g.title;
      sec.appendChild(h);
      for (const t of g.items) {
        const item = document.createElement("div");
        item.className = "lib-item grid-stack-item" + (t.custom ? " custom" : "");
        item.tabIndex = 0;
        item.dataset.template = t.id;
        item.setAttribute("gs-w", t.size.w);
        item.setAttribute("gs-h", t.size.h);
        item.setAttribute("role", "button");
        item.innerHTML = `<svg class="grip"><use href="#i-grip"/></svg><div class="grid-stack-item-content"><strong></strong><span></span></div>`;
        item.querySelector("strong").textContent = t.title;
        item.querySelector("span").textContent = t.description;
        item.dataset.search = `${t.title} ${t.description}`.toLocaleLowerCase("tr");
        const add = () => openWidgetDialog({ templateId: t.id });
        item.addEventListener("click", add);
        item.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); add(); } });
        sec.appendChild(item);
      }
      body.appendChild(sec);
    }
    GridStack.setupDragIn("#libraryBody .lib-item", { appendTo: "body", helper: "clone" });
  }

  $("#libSearch").addEventListener("input", (e) => {
    const q = e.target.value.toLocaleLowerCase("tr").trim();
    document.querySelectorAll("#libraryBody .lib-item").forEach((el) => { el.hidden = q && !el.dataset.search.includes(q); });
    document.querySelectorAll("#libraryBody .lib-group").forEach((g) => { g.hidden = ![...g.querySelectorAll(".lib-item")].some((i) => !i.hidden); });
  });

  // ------------------------------------------------------------------ pano (grid)
  function initGrid() {
    state.grid = GridStack.init({
      column: 12, cellHeight: 80, margin: 4, float: false, animate: true,
      acceptWidgets: ".lib-item", staticGrid: true,
      draggable: { handle: ".w-head" }, resizable: { handles: "e, se, s, sw, w" },
      columnOpts: { breakpoints: [{ w: 760, c: 1 }] },
    }, "#grid");

    state.grid.on("dropped", (_e, _prev, node) => {
      const templateId = node.el.dataset.template;
      const pos = { x: node.x, y: node.y, w: node.w, h: node.h };
      state.grid.removeWidget(node.el, true, false);
      openWidgetDialog({ templateId, pos });
    });
    state.grid.on("change", () => { if (!state.loadingDashboard) syncLayout(); });
  }

  function syncLayout() {
    if (!state.current) return;
    for (const w of state.current.widgets) {
      const node = state.views.get(w.id)?.el.gridstackNode;
      if (node) Object.assign(w, { x: node.x, y: node.y, w: node.w, h: node.h });
    }
    scheduleSave();
  }

  function subtitleOf(w) {
    const t = templateOf(w);
    if (t) {
      const parts = [];
      for (const p of t.params) {
        let v = w.source.params?.[p.name];
        if (isRef(v)) v = varById(v.$var) ? displayValue(varById(v.$var)) : "?";
        if (v === undefined || v === "" || p.type === "bool") continue;
        if (p.type === "int" && p.name === "top_n") parts.push(`Top ${v}`);
        else if (p.type === "int") { if (Number(v) > 0) parts.push(`${p.label}: ${Charts.fmt(v)}`); }
        else if (p.type === "select") parts.push(p.options.find((o) => o.value === v)?.label || v);
        else if (v === "__global__") parts.push("Global");
        else parts.push(v);
      }
      return parts.join(" · ") || t.description;
    }
    const s = w.source.spec || {};
    if (w.source.type === "sql") return "SQL sorgusu";
    const ds = state.meta.builder.datasets[s.dataset];
    if (!ds) return "Özel sorgu";
    const bits = [ds.label];
    if (s.x) bits.push(ds.dims[s.x]);
    if (s.series) bits.push(ds.dims[s.series]);
    if (s.measure === "ratio") bits.push("oran");
    else if (s.value_mode && s.value_mode !== "raw") bits.push(state.meta.builder.value_modes[s.value_mode]);
    const nf = (s.filters || []).filter((f) => f.value !== "" && f.value != null).length;
    if (nf) bits.push(`${nf} filtre`);
    return bits.join(" · ");
  }

  function createWidgetEl(w) {
    const el = document.createElement("div");
    el.className = "grid-stack-item";
    el.setAttribute("gs-id", w.id);
    for (const k of ["x", "y", "w", "h"]) if (w[k] !== undefined && w[k] !== null) el.setAttribute(`gs-${k}`, w[k]);
    // Konumu olmayan (tıklayarak eklenen) widget ilk boş yere yerleşsin
    if (w.x === undefined || w.x === null || w.y === undefined || w.y === null) el.setAttribute("gs-auto-position", "true");
    el.innerHTML = `
      <div class="grid-stack-item-content">
        <article class="card">
          <header class="w-head">
            <div class="w-titles"><div class="w-title"></div><div class="w-sub"></div></div>
            <div class="w-actions">
              <button class="icon-btn" data-act="table" title="Tablo / grafik görünümü"><svg><use href="#i-table"/></svg></button>
              <button class="icon-btn" data-act="refresh" title="Yenile"><svg><use href="#i-refresh"/></svg></button>
              <button class="icon-btn edit-only" data-act="edit" title="Ayarlar"><svg><use href="#i-gear"/></svg></button>
              <button class="icon-btn edit-only danger" data-act="remove" title="Kaldır"><svg><use href="#i-x"/></svg></button>
            </div>
          </header>
          <div class="w-body"></div>
        </article>
      </div>`;
    el.querySelector(".w-actions").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-act]");
      if (!btn) return;
      e.stopPropagation();
      const act = btn.dataset.act;
      if (act === "refresh") loadWidget(w.id);
      if (act === "edit") openWidgetDialog({ widget: w });
      if (act === "remove") removeWidget(w.id);
      if (act === "table") {
        const v = state.views.get(w.id);
        v.tableMode = !v.tableMode;
        drawWidget(w.id);
      }
    });
    // Başlık çubuğundaki butonlar sürüklemeyi başlatmasın
    el.querySelectorAll(".w-actions button").forEach((b) => b.addEventListener("mousedown", (e) => e.stopPropagation()));
    return el;
  }

  function mountWidget(w) {
    const el = createWidgetEl(w);
    $("#grid").appendChild(el);
    state.grid.makeWidget(el);
    // Gridstack'in verdiği konumu (otomatik yerleşim dahil) widget'a yaz
    const n = el.gridstackNode;
    if (n) Object.assign(w, { x: n.x, y: n.y, w: n.w, h: n.h });
    const body = el.querySelector(".w-body");
    state.views.set(w.id, { el, body, view: null, data: null, tableMode: false });
    new ResizeObserver(() => state.views.get(w.id)?.view?.resize()).observe(body);
    paintHeader(w);
    loadWidget(w.id);
  }

  function paintHeader(w) {
    const v = state.views.get(w.id);
    if (!v) return;
    v.el.querySelector(".w-title").textContent = fillTitle(w.title || templateOf(w)?.title || "Widget");
    const sub = subtitleOf(w);
    v.el.querySelector(".w-sub").textContent = sub;
    v.el.querySelector(".w-sub").title = sub;
  }

  async function loadWidget(id) {
    const w = state.current.widgets.find((x) => x.id === id);
    const v = state.views.get(id);
    if (!w || !v) return;
    v.body.classList.add("loading");
    try {
      v.data = await api("/api/widget-data", { method: "POST", body: { source: w.source, vars: varValues() } });
      v.error = null;
    } catch (err) {
      v.data = null;
      v.error = err.message;
    }
    v.body.classList.remove("loading");
    drawWidget(id);
  }

  function drawWidget(id) {
    const w = state.current.widgets.find((x) => x.id === id);
    const v = state.views.get(id);
    if (!w || !v) return;
    v.view?.dispose();
    v.view = null;
    v.body.textContent = "";
    if (v.error) {
      const m = document.createElement("div");
      m.className = "w-message error";
      m.innerHTML = `<div><div class="msg"></div><button class="btn">Tekrar dene</button></div>`;
      m.querySelector(".msg").textContent = v.error;
      m.querySelector("button").addEventListener("click", () => loadWidget(id));
      v.body.appendChild(m);
      return;
    }
    if (!v.data) return;
    const type = v.tableMode && w.chart !== "table" ? "table" : w.chart;
    // Grafikte bir değere tıklanınca aynı türdeki filtreyi güncelle (widget'ın kendi bağlı olduğu filtre hariç)
    const xt = v.data.encoding?.x_type;
    const target = xt && vars().find((x) => x.type === xt && x.pick !== false && !sourceUsesVar(w, x.id));
    // Aynı türdeki filtrede seçili değerler grafikte vurgulanır (ör. seçili sanatçının çubuğu)
    const highlight = xt ? vars().filter((x) => x.type === xt && !sourceUsesVar(w, x.id)).flatMap(valueList) : [];
    v.body.classList.toggle("pickable", !!target);
    const opts = { highlight };
    if (target) {
      opts.onPick = (val) => {
        if (val === null || val === undefined) return;
        setVarValue(target, target.multi ? [String(val)] : String(val));
        toast(`${target.label}: ${val}`);
      };
    }
    v.view = Charts.render(v.body, type, v.data, opts);
  }

  function rerenderAll() {
    for (const id of state.views.keys()) drawWidget(id);
    preview.redraw();
  }

  function removeWidget(id) {
    const v = state.views.get(id);
    if (!v) return;
    v.view?.dispose();
    state.grid.removeWidget(v.el, true, false);
    state.views.delete(id);
    state.current.widgets = state.current.widgets.filter((w) => w.id !== id);
    updateEmpty();
    scheduleSave();
  }

  function updateEmpty() {
    $("#emptyState").hidden = state.current.widgets.length > 0;
  }

  // ------------------------------------------------------------------ düzenleme modu
  function setEditing(on) {
    state.editing = on;
    document.body.classList.toggle("editing", on);
    state.grid.setStatic(!on);
    const btn = $("#btnEdit");
    btn.textContent = on ? "Bitti" : "Düzenle";
    btn.setAttribute("aria-pressed", String(on));
    store.set("md-editing", on ? "1" : "0");
    if (state.current) renderFilterBar();
    // Kütüphane açılıp kapanınca panonun genişliği değişir
    setTimeout(() => state.views.forEach((v) => v.view?.resize()), 50);
  }

  // ------------------------------------------------------------------ kaydetme
  let saveTimer = null;
  function scheduleSave() {
    if (!state.current) return;
    setSaveStatus("Kaydediliyor…");
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 600);
  }
  async function save() {
    const d = state.current;
    try {
      await api(`/api/dashboards/${d.id}`, { method: "PUT", body: { widgets: d.widgets, variables: d.variables } });
      setSaveStatus("Kaydedildi");
    } catch (err) {
      setSaveStatus("Kaydedilemedi", true);
      toast(err.message);
    }
  }
  function setSaveStatus(text, error) {
    const s = $("#saveStatus");
    s.textContent = text;
    s.classList.toggle("error", !!error);
  }

  // ------------------------------------------------------------------ dashboard işlemleri
  async function refreshDashboardList(selectId) {
    state.dashboards = await api("/api/dashboards");
    const sel = $("#dashSelect");
    sel.textContent = "";
    for (const d of state.dashboards) {
      const o = document.createElement("option");
      o.value = d.id;
      o.textContent = d.name;
      sel.appendChild(o);
    }
    if (selectId) sel.value = String(selectId);
  }

  async function openDashboard(id) {
    const d = await api(`/api/dashboards/${id}`);
    state.loadingDashboard = true;
    state.views.forEach((v) => v.view?.dispose());
    state.views.clear();
    state.grid.removeAll(true, false);
    state.current = { id: d.id, name: d.name, widgets: d.widgets || [], variables: d.variables || [] };
    closePicker();
    renderFilterBar();
    state.grid.batchUpdate();
    state.current.widgets.forEach(mountWidget);
    state.grid.batchUpdate(false);
    state.loadingDashboard = false;
    $("#dashSelect").value = String(d.id);
    store.set("md-dashboard", String(d.id));
    setSaveStatus("");
    updateEmpty();
    if (!state.current.widgets.length) setEditing(true);
  }

  async function newDashboard(name, widgets = [], variables = []) {
    const d = await api("/api/dashboards", { method: "POST", body: { name, widgets, variables } });
    await refreshDashboardList(d.id);
    await openDashboard(d.id);
    return d;
  }

  $("#dashSelect").addEventListener("change", (e) => openDashboard(e.target.value));

  $("#btnNew").addEventListener("click", async () => {
    const name = await ask({ title: "Yeni dashboard", text: "Dashboard'a bir ad verin.", value: "Yeni dashboard", ok: "Oluştur" });
    if (name === null) return;
    await newDashboard(name);
    setEditing(true);
  });

  $("#btnRename").addEventListener("click", async () => {
    const name = await ask({ title: "Yeniden adlandır", value: state.current.name, ok: "Kaydet" });
    if (!name) return;
    await api(`/api/dashboards/${state.current.id}`, { method: "PUT", body: { name } });
    state.current.name = name;
    await refreshDashboardList(state.current.id);
    toast("Ad güncellendi");
  });

  $("#btnDelete").addEventListener("click", async () => {
    const ok = await ask({ title: "Dashboard silinsin mi?", text: `"${state.current.name}" kalıcı olarak silinecek.`, input: false, ok: "Sil" });
    if (ok === null) return;
    await api(`/api/dashboards/${state.current.id}`, { method: "DELETE" });
    await refreshDashboardList();
    if (state.dashboards.length) await openDashboard(state.dashboards[0].id);
    else await newDashboard("Yeni dashboard");
    toast("Dashboard silindi");
  });

  $("#btnExport").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify({ version: 2, name: state.current.name, variables: vars(), widgets: state.current.widgets }, null, 2)],
      { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${state.current.name.replace(/[^\p{L}\p{N}_-]+/gu, "_")}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });

  $("#btnImport").addEventListener("click", () => $("#importFile").click());
  $("#importFile").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    try {
      const json = JSON.parse(await file.text());
      if (!Array.isArray(json.widgets)) throw new Error("Dosyada 'widgets' listesi yok");
      const widgets = json.widgets.map((w) => ({ ...w, id: uid() }));
      await newDashboard(`${json.name || "Dashboard"} (içe aktarılan)`, widgets, Array.isArray(json.variables) ? json.variables : []);
      toast("Dashboard içe aktarıldı");
    } catch (err) {
      toast("İçe aktarılamadı: " + err.message);
    }
  });

  $("#btnRefreshAll").addEventListener("click", () => state.current.widgets.forEach((w) => loadWidget(w.id)));
  $("#btnEdit").addEventListener("click", () => setEditing(!state.editing));
  $("#btnTheme").addEventListener("click", toggleTheme);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (!store.get("md-theme")) rerenderAll(); });

  // ------------------------------------------------------------------ soru penceresi
  function ask({ title, text = "", value = "", input = true, ok = "Tamam" }) {
    const dlg = $("#askDialog");
    $("#askTitle").textContent = title;
    $("#askText").textContent = text;
    $("#askText").hidden = !text;
    const inp = $("#askInput");
    inp.hidden = !input;
    inp.value = value;
    $("#askOk").textContent = ok;
    return new Promise((resolve) => {
      const done = (v) => { dlg.close(); cleanup(); resolve(v); };
      const onSubmit = (e) => { e.preventDefault(); done(input ? inp.value.trim() : true); };
      const onCancel = () => done(null);
      const closeBtn = dlg.querySelector("[data-close]");
      const cleanup = () => {
        $("#askForm").removeEventListener("submit", onSubmit);
        closeBtn.removeEventListener("click", onCancel);
        dlg.removeEventListener("cancel", onCancel);
      };
      $("#askForm").addEventListener("submit", onSubmit);
      closeBtn.addEventListener("click", onCancel);
      dlg.addEventListener("cancel", onCancel);
      dlg.showModal();
      if (input) { inp.focus(); inp.select(); }
    });
  }

  // ------------------------------------------------------------------ widget ayar penceresi
  const preview = {
    view: null, data: null, chart: null, timer: null, seq: 0, onData: null, onError: null,
    body() { return $("#wdPreview"); },
    clear() { this.view?.dispose(); this.view = null; this.data = null; this.body().textContent = ""; },
    redraw() {
      if (!$("#widgetDialog").open || !this.data) return;
      this.view?.dispose();
      const b = document.createElement("div");
      b.className = "w-body";
      this.body().textContent = "";
      this.body().appendChild(b);
      this.view = Charts.render(b, this.chart, this.data);
    },
    schedule(draft) {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.load(draft), 350);
    },
    async load(draft) {
      const seq = ++this.seq;
      this.body().classList.add("loading");
      $("#wdError").textContent = "";
      try {
        const data = await api("/api/widget-data", { method: "POST", body: { source: draft.source, vars: varValues() } });
        if (seq !== this.seq) return;
        this.data = data;
        this.chart = draft.chart;
        this.redraw();
        this.onData?.(data);
      } catch (err) {
        if (seq !== this.seq) return;
        this.clear();
        this.onError?.(err);
        const m = document.createElement("div");
        m.className = "w-message error";
        m.textContent = err.message;
        this.body().appendChild(m);
      } finally {
        if (seq === this.seq) this.body().classList.remove("loading");
      }
    },
  };

  function el(tag, attrs = {}, children = []) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "text") e.textContent = v;
      else if (k === "class") e.className = v;
      else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? "" : v);
    }
    children.forEach((c) => c && e.appendChild(c));
    return e;
  }

  function field(label, control, hint) {
    const id = "f" + Math.random().toString(36).slice(2, 8);
    control.id = control.id || id;
    return el("div", { class: "field" }, [el("label", { for: control.id, text: label }), control, hint ? el("div", { class: "hint", text: hint }) : null]);
  }

  function selectEl(options, value, attrs = {}) {
    const s = el("select", attrs);
    for (const o of options) {
      const opt = el("option", { value: o.value, text: o.label });
      if (String(o.value) === String(value ?? "")) opt.selected = true;
      s.appendChild(opt);
    }
    return s;
  }

  function datalistInput(listItems, value, attrs) {
    const listId = "dl" + Math.random().toString(36).slice(2, 8);
    const input = el("input", { type: "text", list: listId, value: value ?? "", autocomplete: "off", ...attrs });
    const dl = el("datalist", { id: listId });
    listItems.forEach((v) => dl.appendChild(el("option", { value: v })));
    const wrap = el("div", {}, [input, dl]);
    wrap.input = input;
    return wrap;
  }

  function chartPicker(allowed, value, onChange) {
    const wrap = el("div", { class: "seg", role: "radiogroup", "aria-label": "Grafik tipi" });
    const name = "chart" + Math.random().toString(36).slice(2, 6);
    for (const c of allowed) {
      const input = el("input", { type: "radio", name, value: c });
      input.checked = c === value;
      input.addEventListener("change", () => onChange(c));
      wrap.appendChild(el("label", {}, [input, el("span", { text: Charts.CHART_LABELS[c] || c })]));
    }
    return el("div", { class: "field" }, [el("div", { class: "label", text: "Grafik tipi" }), wrap]);
  }

  /* Ayar penceresi: yeni widget (templateId + pos) veya mevcut widget (widget) */
  function openWidgetDialog({ templateId, pos, widget }) {
    const isNew = !widget;
    const draft = widget ? structuredClone(widget) : {
      id: uid(), title: "", chart: null,
      source: templateId === "__custom__"
        ? { type: "custom", spec: { dataset: "geo_artists", x: "artist_name", metric: "listeners", agg: "sum",
            measure: "simple", value_mode: "raw", snapshot: "latest", sort: "value_desc", limit: 10, filters: [] } }
        : templateId === "__sql__"
        ? { type: "sql", spec: { sql: DEFAULT_SQL, x: "sanatci", ys: ["yurtdisi_payi"], series: null, format: "percent" } }
        : { type: "template", template: templateId, params: {} },
      w: 6, h: 5,
      ...(pos || {}),
    };
    const tpl = draft.source.type === "template" ? state.meta.templates.find((t) => t.id === draft.source.template) : null;
    if (tpl && isNew) {
      for (const p of tpl.params) {
        const vt = PARAM_VAR_TYPE[p.type];
        const match = vt && vars().find((v) => v.type === vt);
        draft.source.params[p.name] = match ? { $var: match.id } : p.default;
      }
      if (!pos) { draft.w = tpl.size.w; draft.h = tpl.size.h; }
    }

    $("#wdTitle").textContent = isNew ? "Widget ekle" : "Widget ayarları";
    const isSql = draft.source.type === "sql";
    $("#wdDesc").textContent = tpl ? `${tpl.title} — ${tpl.description}`
      : isSql ? "SQL sorgusu: veritabanındaki tablo ve view'lardan istediğin sonucu çek. Sorgular yalnızca okuma yapabilir; 5 sn zaman aşımı ve 1000 satır sınırı var."
      : "Özel sorgu: kendi grafiğini oluştur.";
    $("#widgetDialog").classList.toggle("sql-mode", isSql);
    preview.onData = null;
    preview.onError = null;
    $("#wdSubmit").textContent = isNew ? "Panoya ekle" : "Kaydet";
    $("#wdError").textContent = "";
    preview.clear();

    const fields = $("#wdFields");
    fields.textContent = "";
    const titleInput = el("input", { type: "text", value: draft.title, placeholder: tpl ? tpl.title : isSql ? "SQL grafiği" : "Başlık", maxlength: 80 });
    titleInput.addEventListener("input", () => { draft.title = titleInput.value; });
    fields.appendChild(field("Başlık", titleInput));

    const chartSlot = el("div");
    // update(true): yalnızca grafik tipi listesini yenile, sorguyu tekrar çalıştırma
    const update = (skipPreview) => {
      renderChartPicker();
      if (!skipPreview) preview.schedule(draft);
    };
    const renderChartPicker = () => {
      const allowed = tpl ? tpl.charts : isSql ? sqlCharts(draft.source.spec) : customCharts(draft.source.spec);
      if (!allowed.includes(draft.chart)) {
        draft.chart = allowed[0];
        if (preview.data) { preview.chart = draft.chart; preview.redraw(); }
      }
      chartSlot.textContent = "";
      chartSlot.appendChild(chartPicker(allowed, draft.chart, (c) => { draft.chart = c; preview.chart = c; preview.redraw(); }));
    };

    if (tpl) buildTemplateFields(fields, tpl, draft, update);
    else if (isSql) buildSqlFields(fields, draft, update);
    else buildCustomFields(fields, draft, update);
    fields.appendChild(chartSlot);
    update();

    const dlg = $("#widgetDialog");
    const form = $("#widgetForm");
    const close = () => { dlg.close(); };
    const onSubmit = (e) => {
      e.preventDefault();
      if (!draft.title.trim()) draft.title = tpl ? tpl.title : isSql ? "SQL grafiği" : "Özel grafik";
      if (isNew) {
        state.current.widgets.push(draft);
        mountWidget(draft);
        updateEmpty();
      } else {
        const i = state.current.widgets.findIndex((w) => w.id === draft.id);
        Object.assign(state.current.widgets[i], { title: draft.title, chart: draft.chart, source: draft.source });
        paintHeader(state.current.widgets[i]);
        loadWidget(draft.id);
      }
      scheduleSave();
      close();
    };
    form.onsubmit = onSubmit;
    dlg.querySelectorAll("[data-close]").forEach((b) => { b.onclick = close; });
    dlg.onclose = () => { preview.clear(); preview.onData = null; preview.onError = null; };
    dlg.showModal();
    titleInput.focus();
  }

  function buildTemplateFields(root, tpl, draft, update) {
    const params = draft.source.params;
    const opts = state.meta.options;
    for (const p of tpl.params) {
      const slot = el("div", { style: "display:contents" });
      root.appendChild(slot);
      const renderParam = () => {
        slot.textContent = "";
        const set = (v) => { params[p.name] = v; update(); };
        const vt = PARAM_VAR_TYPE[p.type];
        // Filtreye bağlanabilen parametre: önce değer kaynağı seçimi
        let bindRow = null;
        if (vt) {
          bindRow = bindSelect(vt, params[p.name], (id) => {
            const cur = params[p.name];
            params[p.name] = id ? { $var: id } : isRef(cur) ? (valueList(varById(cur.$var) || {})[0] || p.default) : cur;
            renderParam();
            update();
          }, () => ({ label: p.label, value: isRef(params[p.name]) ? "" : params[p.name] }));
          if (isRef(params[p.name])) {
            slot.appendChild(el("div", { class: "field" }, [el("div", { class: "label", text: p.label }), bindRow,
              boundNote(params[p.name].$var)]));
            return;
          }
        }
        let node;
        if (p.type === "country" || p.type === "country_or_global") {
          const list = (p.type === "country_or_global" ? [{ value: "__global__", label: "Global (tüm dünya)" }] : [])
            .concat(opts.countries.map((c) => ({ value: c, label: c })));
          if (!list.length) list.push({ value: p.default, label: p.default });
          const sel = selectEl(list, params[p.name]);
          sel.addEventListener("change", () => set(sel.value));
          node = field(p.label, sel);
        } else if (p.type === "tag" || p.type === "artist") {
          const w = datalistInput(p.type === "tag" ? opts.tags : opts.artists, params[p.name],
            { placeholder: p.type === "tag" ? "ör. pop, rock, turkish" : "ör. Tarkan" });
          w.input.addEventListener("change", () => set(w.input.value.trim()));
          node = field(p.label, w, "Listeden seçebilir ya da yazabilirsiniz.");
          node.querySelector("label").setAttribute("for", w.input.id = "f" + Math.random().toString(36).slice(2, 8));
        } else if (p.type === "int") {
          const i = el("input", { type: "number", min: p.min, max: p.max, value: params[p.name] });
          i.addEventListener("change", () => set(Number(i.value)));
          node = field(p.label, i, `${p.min}–${p.max} arası`);
        } else if (p.type === "bool") {
          const c = el("input", { type: "checkbox" });
          c.checked = !!params[p.name];
          c.addEventListener("change", () => set(c.checked));
          node = el("div", { class: "field check" }, [el("label", {}, [c, document.createTextNode(p.label)])]);
        } else if (p.type === "select") {
          const sel = selectEl(p.options, params[p.name]);
          sel.addEventListener("change", () => set(sel.value));
          node = field(p.label, sel);
        } else {
          const i = el("input", { type: "text", value: params[p.name] ?? "" });
          i.addEventListener("change", () => set(i.value));
          node = field(p.label, i);
        }
        if (bindRow) node.insertBefore(bindRow, node.children[1]);
        slot.appendChild(node);
      };
      renderParam();
    }
  }

  // ---------------------------------------------------------------- özel sorgu: yardımcılar
  function suggestionsFor(field) {
    const o = state.meta.options;
    if (field === "country") return o.countries;
    if (field === "home_country") return o.all_countries.map((c) => c.name);
    if (field === "tag_name") return o.tags;
    if (field === "artist_name") return o.artists;
    if (field === "location") return o.locations;
    if (field === "home_source") return o.home_sources;
    return [];
  }

  function customCharts(spec) {
    if (!spec.x) return ["kpi", "table"];
    if (spec.series) {
      return spec.value_mode === "pct_x"
        ? ["hstack", "stack", "table"]
        : ["hbar", "bar", "hstack", "stack", "line", "heatmap", "table"];
    }
    if (spec.x === "fetched_at") return ["line", "bar", "table"];
    return ["hbar", "bar", "line", "pie", "treemap", "table"];
  }

  /* Tek satırlık koşul düzenleyicisi (oran ölçüsünün pay/payda koşulu için) */
  function condEditor(ds, cond, onChange) {
    const b = state.meta.builder;
    const fields = [{ value: "", label: "— Koşul yok —" },
      ...Object.entries({ ...ds.dims, ...ds.metrics }).map(([value, label]) => ({ value, label }))];
    const fSel = selectEl(fields, cond.field || "", { "aria-label": "Koşul alanı" });
    const oSel = selectEl(Object.entries(b.ops).map(([value, label]) => ({ value, label })), cond.op || "eq", { "aria-label": "Koşul" });
    const vIn = datalistInput(suggestionsFor(cond.field), cond.value, { placeholder: "değer", "aria-label": "Koşul değeri" });
    const sync = () => {
      cond.field = fSel.value || null;
      cond.op = oSel.value;
      cond.value = vIn.input.value;
      oSel.disabled = vIn.input.disabled = !cond.field;
      onChange();
    };
    fSel.addEventListener("change", () => { cond.value = ""; vIn.input.value = ""; sync(); onChange(true); });
    oSel.addEventListener("change", sync);
    vIn.input.addEventListener("change", sync);
    oSel.disabled = vIn.input.disabled = !cond.field;
    vIn.className = "filter-value";
    return el("div", { class: "filter-row" }, [fSel, oSel, el("span"), vIn]);
  }

  function aggEditor(ds, part, onChange, withCond) {
    const b = state.meta.builder;
    const dimOpts = Object.entries(ds.dims).map(([value, label]) => ({ value, label }));
    const metOpts = Object.entries(ds.metrics).map(([value, label]) => ({ value, label }));
    part.agg = part.agg || "sum";
    if (part.agg !== "count" && part.agg !== "count_distinct" && !ds.metrics[part.metric]) part.metric = metOpts[0]?.value;
    const aggSel = selectEl(Object.entries(b.aggs).map(([value, label]) => ({ value, label })), part.agg);
    const list = part.agg === "count_distinct" ? [...dimOpts, ...metOpts] : metOpts;
    const mSel = selectEl(list, part.metric, part.agg === "count" ? { disabled: true } : {});
    aggSel.addEventListener("change", () => { part.agg = aggSel.value; onChange(true); });
    mSel.addEventListener("change", () => { part.metric = mSel.value; onChange(); });
    const nodes = [el("div", { class: "row2" }, [field("Toplama", aggSel), field("Alan", mSel)])];
    if (withCond) {
      part.cond = part.cond || {};
      nodes.push(el("div", { class: "field" }, [el("div", { class: "label", text: "Koşul (isteğe bağlı)" }),
        condEditor(ds, part.cond, onChange)]));
    }
    return nodes;
  }

  function buildCustomFields(root, draft, update) {
    const b = state.meta.builder;
    const spec = draft.source.spec;
    spec.filters = spec.filters || [];
    spec.measure = spec.measure || "simple";
    spec.value_mode = spec.value_mode || "raw";
    const wrap = el("div", { style: "display:contents" });
    root.appendChild(wrap);

    const render = () => {
      wrap.textContent = "";
      const ds = b.datasets[spec.dataset];
      const dimOpts = Object.entries(ds.dims).map(([value, label]) => ({ value, label }));
      const metOpts = Object.entries(ds.metrics).map(([value, label]) => ({ value, label }));
      const changed = (rerender) => { if (rerender) render(); update(); };
      const change = (key, rerender) => (e) => { spec[key] = e.target.value || null; changed(rerender); };

      // Veri kaynağı
      const dsSel = selectEl(Object.entries(b.datasets).map(([value, d]) => ({ value, label: d.label })), spec.dataset);
      dsSel.addEventListener("change", (e) => {
        const nds = b.datasets[e.target.value];
        Object.assign(spec, { dataset: e.target.value, x: Object.keys(nds.dims)[0], series: null, sort_series: "",
          metric: Object.keys(nds.metrics)[0], filters: [], num: {}, den: {}, value_mode: "raw" });
        changed(true);
      });
      wrap.appendChild(field("Veri kaynağı", dsSel));

      // Eksenler
      wrap.appendChild(el("div", { class: "section-title", text: "Eksenler" }));
      const xSel = selectEl([{ value: "", label: "— Yok (tek sayı) —" }, ...dimOpts], spec.x);
      xSel.addEventListener("change", (e) => {
        spec.x = e.target.value || null;
        if (spec.series === spec.x) spec.series = null;
        changed(true);
      });
      const sSel = selectEl([{ value: "", label: "— Yok —" }, ...dimOpts.filter((o) => o.value !== spec.x)], spec.series,
        spec.x ? {} : { disabled: true });
      sSel.addEventListener("change", (e) => {
        spec.series = e.target.value || null;
        spec.sort_series = "";
        if (!spec.series && ["pct_x", "pct_series"].includes(spec.value_mode)) spec.value_mode = "pct_total";
        changed(true);
      });
      wrap.appendChild(el("div", { class: "row2" }, [field("X ekseni (gruplama)", xSel), field("Seri (renk)", sSel)]));

      // Ölçü
      wrap.appendChild(el("div", { class: "section-title", text: "Ölçü" }));
      const typeSeg = el("div", { class: "seg", role: "radiogroup", "aria-label": "Ölçü türü" });
      const segName = "mt" + Math.random().toString(36).slice(2, 6);
      for (const [value, label] of [["simple", "Tek ölçü"], ["ratio", "Oran (A ÷ B)"]]) {
        const input = el("input", { type: "radio", name: segName, value });
        input.checked = spec.measure === value;
        input.addEventListener("change", () => {
          spec.measure = value;
          if (value === "ratio") {
            spec.num = spec.num?.agg ? spec.num : { agg: spec.agg || "sum", metric: spec.metric, cond: {} };
            spec.den = spec.den?.agg ? spec.den : { agg: spec.agg || "sum", metric: spec.metric, cond: {} };
            spec.value_mode = "raw";
          }
          changed(true);
        });
        typeSeg.appendChild(el("label", {}, [input, el("span", { text: label })]));
      }
      wrap.appendChild(el("div", { class: "field" }, [typeSeg]));

      if (spec.measure === "ratio") {
        spec.num = spec.num || {};
        spec.den = spec.den || {};
        wrap.appendChild(el("div", { class: "sub-box" }, [el("div", { class: "sub-title", text: "A · Pay" }),
          ...aggEditor(ds, spec.num, changed, true)]));
        wrap.appendChild(el("div", { class: "sub-box" }, [el("div", { class: "sub-title", text: "B · Payda" }),
          ...aggEditor(ds, spec.den, changed, true)]));
        wrap.appendChild(el("div", { class: "hint", text: "Sonuç = 100 × A ÷ B (yüzde). Örnek: A = Toplam dinleyici [Konum = Yurt dışı], B = Toplam dinleyici." }));
      } else {
        const part = { agg: spec.agg, metric: spec.metric };
        aggEditor(ds, part, (rerender) => { spec.agg = part.agg; spec.metric = part.metric; changed(rerender); })
          .forEach((n) => wrap.appendChild(n));
        spec.agg = part.agg;
        spec.metric = part.metric;
        const modes = Object.entries(b.value_modes)
          .filter(([k]) => spec.series || !["pct_x", "pct_series"].includes(k))
          .map(([value, label]) => ({ value, label }));
        const modeSel = selectEl(modes, spec.value_mode, spec.x ? {} : { disabled: true });
        modeSel.addEventListener("change", change("value_mode", true));
        wrap.appendChild(field("Gösterim", modeSel,
          spec.value_mode === "pct_x" ? "Her X değerindeki serilerin payı; çubuklar %100'e tamamlanır." : null));
      }
      const lblIn = el("input", { type: "text", value: spec.value_label || "", placeholder: "Otomatik", maxlength: 60 });
      lblIn.addEventListener("change", () => { spec.value_label = lblIn.value; update(); });
      wrap.appendChild(field("Ölçü adı (isteğe bağlı)", lblIn));

      // Filtreler
      wrap.appendChild(el("div", { class: "section-title", text: "Filtreler" }));
      const fl = el("div", { class: "filters" });
      const allFields = [...dimOpts, ...metOpts];
      spec.filters.forEach((f, i) => {
        const fSel = selectEl(allFields, f.field, { "aria-label": "Alan" });
        const oSel = selectEl(Object.entries(b.ops).map(([value, label]) => ({ value, label })), f.op, { "aria-label": "Koşul" });
        const del = el("button", { type: "button", class: "icon-btn", title: "Filtreyi kaldır" });
        del.innerHTML = `<svg><use href="#i-x"/></svg>`;
        fSel.addEventListener("change", () => { f.field = fSel.value; f.value = ""; changed(true); });
        oSel.addEventListener("change", () => { f.op = oSel.value; update(); });
        del.addEventListener("click", () => { spec.filters.splice(i, 1); changed(true); });
        const cells = [fSel, oSel, del];
        const vt = FIELD_VAR_TYPE[f.field];
        if (vt) {
          cells.push(bindSelect(vt, f.value, (id) => {
            f.value = id ? { $var: id } : isRef(f.value) ? valueList(varById(f.value.$var) || {}).join(", ") : f.value;
            if (id && f.op === "in") f.op = "eq";
            changed(true);
          }, () => ({ label: ds.dims[f.field] || varTypeLabel(vt), value: isRef(f.value) ? "" : String(f.value || "").split(",")[0].trim() })));
        }
        if (isRef(f.value)) {
          const note = boundNote(f.value.$var);
          note.classList.add("filter-value");
          cells.push(note);
        } else {
          const vIn = datalistInput(suggestionsFor(f.field), f.value, { placeholder: f.op === "in" ? "a, b, c" : "değer", "aria-label": "Değer" });
          vIn.input.addEventListener("change", () => { f.value = vIn.input.value; update(); });
          vIn.className = "filter-value";
          cells.push(vIn);
        }
        fl.appendChild(el("div", { class: "filter-row" }, cells));
      });
      if (spec.filters.some((f) => isRef(f.value))) {
        fl.appendChild(el("div", { class: "hint", text: "Filtrede seçim yoksa (Tümü) bu koşul uygulanmaz; çoklu seçimde tüm seçilen değerler kullanılır." }));
      }
      const addF = el("button", { type: "button", class: "link-btn", text: "+ Filtre ekle" });
      addF.addEventListener("click", () => { spec.filters.push({ field: dimOpts[0].value, op: "eq", value: "" }); render(); });
      fl.appendChild(addF);
      wrap.appendChild(fl);

      // Seçenekler
      wrap.appendChild(el("div", { class: "section-title", text: "Seçenekler" }));
      const sortSel = selectEl(Object.entries(b.sorts).map(([value, label]) => ({ value, label })), spec.sort);
      sortSel.addEventListener("change", change("sort", true));
      const lim = el("input", { type: "number", min: 1, max: 500, value: spec.limit ?? 20 });
      lim.addEventListener("change", () => { spec.limit = Number(lim.value); update(); });
      if (ds.snapshots) {
        const snapSel = selectEl([{ value: "latest", label: "Son snapshot" }, { value: "all", label: "Tüm snapshot'lar" }], spec.snapshot);
        snapSel.addEventListener("change", change("snapshot"));
        wrap.appendChild(el("div", { class: "row2" }, [
          field("Zaman aralığı", snapSel, spec.x === "fetched_at" ? "Zaman ekseni için 'Tüm snapshot'lar' seçin." : null),
          field("Sıralama", sortSel)]));
      } else {
        wrap.appendChild(field("Sıralama", sortSel));
      }
      if (spec.series && spec.sort !== "label") {
        const ss = datalistInput(suggestionsFor(spec.series), spec.sort_series || "", { placeholder: "Tüm seriler (toplam)" });
        ss.input.addEventListener("change", () => { spec.sort_series = ss.input.value.trim(); update(); });
        wrap.appendChild(field("Sıralamada esas alınacak seri", ss, "Ör. 'Yurt dışı' yazarsanız X değerleri yurtdışı değerine göre sıralanır."));
      }
      wrap.appendChild(field(spec.x ? "En fazla kaç X değeri" : "En fazla kaç satır", lim));
    };
    render();
  }

  // ---------------------------------------------------------------- SQL widget'ı
  const DEFAULT_SQL = `-- Örnek: Türk sanatçıların yurtdışı payı
SELECT artist_name        AS sanatci,
       home_listeners     AS yurt_ici,
       foreign_listeners  AS yurt_disi,
       foreign_share_pct  AS yurtdisi_payi
FROM v_artist_foreign_share
WHERE home_country = 'Turkey' AND home_listeners IS NOT NULL
ORDER BY foreign_share_pct DESC
LIMIT 15`;

  function sqlCharts(spec) {
    if (spec.series) return ["hbar", "bar", "hstack", "stack", "line", "heatmap", "table"];
    if ((spec.ys || []).length > 1) return ["hbar", "bar", "hstack", "stack", "line", "table"];
    return ["hbar", "bar", "line", "pie", "treemap", "table", "kpi"];
  }

  function buildSqlFields(root, draft, update) {
    const spec = draft.source.spec;
    spec.ys = spec.ys || [];
    let columns = [], types = [];

    // Editör
    const ta = el("textarea", { class: "sql-editor", rows: 11, spellcheck: "false", "aria-label": "SQL sorgusu" });
    ta.value = spec.sql || "";
    ta.addEventListener("input", () => { spec.sql = ta.value; });
    const run = () => { spec.sql = ta.value; preview.load(draft); };
    ta.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); run(); }
      if (e.key === "Tab") {       // Tab ile girinti
        e.preventDefault();
        ta.setRangeText("  ", ta.selectionStart, ta.selectionEnd, "end");
        spec.sql = ta.value;
      }
    });
    const runBtn = el("button", { type: "button", class: "btn", text: "Çalıştır" });
    runBtn.addEventListener("click", run);
    const status = el("span", { class: "muted small" });
    root.appendChild(el("div", { class: "field" }, [
      el("label", { text: "SQL sorgusu (yalnızca SELECT)", for: ta.id = "sql" + Math.random().toString(36).slice(2, 6) }),
      ta,
      el("div", { class: "sql-actions" }, [runBtn, el("span", { class: "hint", text: "Ctrl + Enter" }), status]),
    ]));
    // Dashboard filtreleri: tıklayınca sorguya eklenir
    const varBox = el("div", { class: "sql-vars" });
    if (vars().length) {
      varBox.appendChild(el("span", { text: "Filtreler:" }));
      for (const v of vars()) {
        const token = v.multi ? `ANY({{${v.id}}})` : `{{${v.id}}}`;
        const btn = el("button", { type: "button", text: token, title: `${v.label} (${v.multi ? "çoklu: metin dizisi" : "tek değer"}) — şu an: ${displayValue(v)}` });
        btn.addEventListener("click", () => {
          ta.focus();
          ta.setRangeText(token, ta.selectionStart, ta.selectionEnd, "end");
          spec.sql = ta.value;
        });
        varBox.appendChild(btn);
      }
      varBox.appendChild(el("span", { text: "Ör. WHERE home_country = {{country}} · çoklu: WHERE country = ANY({{countries}}) · boşsa tümü: ({{x}} IS NULL OR kolon = {{x}})" }));
    } else {
      varBox.appendChild(el("span", { text: "Üstte bir filtre eklerseniz sorguda {{ad}} şeklinde kullanabilirsiniz." }));
    }
    root.appendChild(varBox);

    // Tablo / kolon rehberi: tıklayınca imlecin olduğu yere ekler
    const insert = (text) => {
      ta.focus();
      ta.setRangeText(text, ta.selectionStart, ta.selectionEnd, "end");
      spec.sql = ta.value;
    };
    const guide = el("details", { class: "schema-guide" }, [el("summary", { text: "Tablolar ve kolonlar" })]);
    const list = el("div", { class: "schema-list" });
    for (const t of state.meta.schema) {
      const tBtn = el("button", { type: "button", class: "schema-table", text: t.name, title: "Sorguya ekle" });
      tBtn.addEventListener("click", () => insert(t.name));
      const cols = el("div", { class: "schema-cols" });
      t.columns.forEach((c) => {
        const cBtn = el("button", { type: "button", class: "schema-col", text: c.name, title: c.type });
        cBtn.addEventListener("click", () => insert(c.name));
        cols.appendChild(cBtn);
      });
      list.appendChild(el("div", { class: "schema-item" }, [tBtn, el("span", { class: "schema-kind", text: t.kind === "view" ? "view" : "tablo" }), cols]));
    }
    guide.appendChild(list);
    root.appendChild(guide);

    // Grafik eşlemesi
    const mapping = el("div", { style: "display:contents" });
    root.appendChild(mapping);
    const renderMapping = () => {
      mapping.textContent = "";
      if (!columns.length) return;
      mapping.appendChild(el("div", { class: "section-title", text: "Grafik eşlemesi" }));
      const colOpts = columns.map((c) => ({ value: c, label: c }));
      const numeric = columns.filter((_, i) => types[i] === "number");
      const xSel = selectEl(colOpts, spec.x);
      xSel.addEventListener("change", () => { spec.x = xSel.value; if (spec.series === spec.x) spec.series = null; renderMapping(); update(); });
      const sSel = selectEl([{ value: "", label: "— Yok —" }, ...colOpts.filter((o) => o.value !== spec.x)], spec.series || "");
      sSel.addEventListener("change", () => { spec.series = sSel.value || null; if (spec.series) spec.ys = spec.ys.slice(0, 1); renderMapping(); update(); });
      mapping.appendChild(el("div", { class: "row2" }, [field("X ekseni / etiket", xSel), field("Seri (uzun format)", sSel)]));

      const chips = el("div", { class: "seg", role: "group", "aria-label": "Değer sütunları" });
      numeric.forEach((c) => {
        const input = el("input", { type: spec.series ? "radio" : "checkbox", name: "ys" + draft.id, value: c });
        input.checked = spec.ys.includes(c);
        input.addEventListener("change", () => {
          spec.ys = [...chips.querySelectorAll("input:checked")].map((i) => i.value);
          if (!spec.ys.length) { spec.ys = [c]; input.checked = true; }
          update();
        });
        chips.appendChild(el("label", {}, [input, el("span", { text: c })]));
      });
      mapping.appendChild(el("div", { class: "field" }, [
        el("div", { class: "label", text: spec.series ? "Değer sütunu" : "Değer sütunları" }),
        numeric.length ? chips : el("div", { class: "hint", text: "Sorguda sayısal bir sütun yok; tablo görünümü kullanılabilir." }),
        spec.series ? null : el("div", { class: "hint", text: "Birden fazla seçerseniz her biri ayrı seri olur (yığılmış grafik için idealdir)." }),
      ]));
      const fSel = selectEl([{ value: "number", label: "Sayı" }, { value: "percent", label: "Yüzde (%)" },
        { value: "hours", label: "Saat" }, { value: "duration", label: "Süre (dk:sn)" }], spec.format || "number");
      fSel.addEventListener("change", () => { spec.format = fSel.value; update(); });
      mapping.appendChild(field("Değer biçimi", fSel));
    };

    // Önizleme her yüklendiğinde kolon listesini güncelle
    // Sütun adından değer biçimini tahmin et (yeni sorguda önceki biçim taşınmasın)
    const guessFormat = (name) => /pay|pct|oran|percent|yuzde|yüzde/i.test(name || "") ? "percent"
      : /saat|hours/i.test(name || "") ? "hours" : /sure|süre|duration/i.test(name || "") ? "duration" : "number";
    preview.onData = (data) => {
      const meta = data.meta || {};
      const changedCols = columns.join("|") !== data.columns.join("|");
      if (changedCols && columns.length) {
        spec.format = guessFormat(data.encoding.y);
        data.encoding.format = spec.format;
        preview.redraw();
      }
      columns = data.columns;
      types = meta.types || [];
      spec.x = data.encoding.x;
      spec.ys = data.encoding.y_cols || (data.encoding.y ? [data.encoding.y] : []);
      spec.series = data.encoding.series || null;
      status.textContent = meta.truncated ? `İlk ${meta.row_count} satır gösteriliyor` : `${meta.row_count} satır`;
      renderMapping();
      update(true);
    };
    preview.onError = () => { status.textContent = ""; };
  }

  // ------------------------------------------------------------------ sanatçı ülkeleri
  const countriesUI = { dirty: false, timer: null, seq: 0 };

  function sourceBadge(source) {
    const cls = source === "MusicBrainz" ? "src-mb" : source === "Elle girildi" ? "src-manual" : "src-guess";
    return el("span", { class: `badge ${cls}`, text: source });
  }

  async function loadCountries() {
    const seq = ++countriesUI.seq;
    const params = new URLSearchParams({ q: $("#acSearch").value, source: $("#acSource").value,
      home: $("#acHome").value, limit: "150" });
    let data;
    try {
      data = await api(`/api/artist-countries?${params}`);
    } catch (err) {
      $("#acHint").textContent = err.message;
      return;
    }
    if (seq !== countriesUI.seq) return;
    const sum = $("#acSummary");
    sum.textContent = "";
    for (const k of ["MusicBrainz", "Elle girildi", "Tahmini"]) {
      const pill = el("span", { class: "pill" }, [el("strong", { text: Charts.fmt(data.counts[k] || 0) }), document.createTextNode(k)]);
      sum.appendChild(pill);
    }
    const tbody = $("#acTable tbody");
    tbody.textContent = "";
    const all = state.meta.options.all_countries;
    for (const r of data.rows) {
      const tr = tbody.insertRow();
      tr.insertCell().textContent = r.artist_name;
      const tot = tr.insertCell(); tot.className = "num"; tot.textContent = Charts.fmt(r.total_listeners);
      const cnt = tr.insertCell(); cnt.className = "num"; cnt.textContent = Charts.fmt(r.countries);
      const sel = selectEl([{ value: "", label: `Otomatik — ${r.auto_country || "bilinmiyor"}` },
        ...all.map((c) => ({ value: c.code, label: c.name }))], r.override_code || "",
        { "aria-label": `${r.artist_name} için ana ülke` });
      tr.insertCell().appendChild(sel);
      const srcCell = tr.insertCell();
      srcCell.appendChild(sourceBadge(r.home_source));
      sel.addEventListener("change", async () => {
        sel.disabled = true;
        try {
          const res = await api("/api/artist-countries", { method: "PUT",
            body: { artist_name: r.artist_name, country_code: sel.value || null } });
          srcCell.textContent = "";
          srcCell.appendChild(sourceBadge(res.home_source));
          countriesUI.dirty = true;
        } catch (err) {
          toast(err.message);
        } finally {
          sel.disabled = false;
        }
      });
    }
    $("#acHint").textContent = data.rows.length >= 150
      ? "En çok dinlenen ilk 150 sanatçı gösteriliyor; diğerleri için arama yapın."
      : data.rows.length ? "" : "Eşleşen sanatçı yok.";
  }

  function openCountriesDialog() {
    const home = $("#acHome");
    if (home.options.length <= 1) {
      state.meta.options.all_countries.forEach((c) => home.appendChild(el("option", { value: c.code, text: c.name })));
    }
    countriesUI.dirty = false;
    const dlg = $("#countriesDialog");
    dlg.showModal();
    loadCountries();
  }

  $("#btnCountries").addEventListener("click", openCountriesDialog);
  $("#acSearch").addEventListener("input", () => { clearTimeout(countriesUI.timer); countriesUI.timer = setTimeout(loadCountries, 250); });
  $("#acSource").addEventListener("change", loadCountries);
  $("#acHome").addEventListener("change", loadCountries);
  $("#countriesDialog").querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => $("#countriesDialog").close()));
  $("#countriesDialog").addEventListener("close", () => {
    if (countriesUI.dirty && state.current) {
      state.current.widgets.forEach((w) => loadWidget(w.id));
      toast("Ülke düzeltmeleri uygulandı");
    }
  });

  // ------------------------------------------------------------------ dashboard filtreleri
  const FIELD_VAR_TYPE = { artist_name: "artist", country: "country", home_country: "country", tag_name: "tag" };
  const PARAM_VAR_TYPE = { country: "country", country_or_global: "country", artist: "artist", tag: "tag" };
  const isRef = (x) => !!x && typeof x === "object" && !Array.isArray(x) && "$var" in x;
  const vars = () => state.current?.variables || [];
  const varById = (id) => vars().find((v) => v.id === id);
  const varTypeLabel = (t) => state.meta.var_types[t] || t;

  function varOptions(type) {
    const o = state.meta.options;
    return type === "country" ? o.countries : type === "artist" ? o.artists : o.tags;
  }
  function varValues() {
    const out = {};
    for (const v of vars()) out[v.id] = v.value ?? (v.multi ? [] : "");
    return out;
  }
  function valueList(v) {
    return Array.isArray(v.value) ? v.value.filter(Boolean) : v.value ? [v.value] : [];
  }
  function displayValue(v) {
    const list = valueList(v);
    return list.length ? list.join(", ") : v.multi ? "Tümü" : "seçilmedi";
  }
  function fillTitle(text) {
    return (text || "").replace(/\{\{\s*([A-Za-z_]\w*)\s*\}\}/g, (m, id) => (varById(id) ? displayValue(varById(id)) : m));
  }
  function sourceUsesVar(w, id) {
    if (JSON.stringify(w.source).includes(`"$var":"${id}"`)) return true;
    return w.source.type === "sql" && new RegExp(`\\{\\{\\s*${id}\\s*\\}\\}`).test(w.source.spec?.sql || "");
  }
  const widgetUsesVar = (w, id) => sourceUsesVar(w, id) || new RegExp(`\\{\\{\\s*${id}\\s*\\}\\}`).test(w.title || "");

  function uniqueVarId(type) {
    let id = type, n = 2;
    while (varById(id)) id = `${type}${n++}`;
    return id;
  }

  function flash(w) {
    const card = state.views.get(w.id)?.el.querySelector(".card");
    if (!card) return;
    card.classList.remove("flash");
    void card.offsetWidth;   // animasyonu yeniden başlat
    card.classList.add("flash");
    card.addEventListener("animationend", () => card.classList.remove("flash"), { once: true });
  }

  function reloadUsing(id) {
    const v = varById(id);
    for (const w of state.current.widgets) {
      const view = state.views.get(w.id);
      if (widgetUsesVar(w, id)) {
        paintHeader(w);
        if (sourceUsesVar(w, id)) { loadWidget(w.id); flash(w); }
      } else if (v && view?.data?.encoding?.x_type === v.type) {
        drawWidget(w.id);     // yalnızca vurgu değişti, veriyi tekrar çekmeye gerek yok
      }
    }
  }

  function setVarValue(v, value) {
    v.value = value;
    renderFilterBar();
    reloadUsing(v.id);
    scheduleSave();
  }

  // Bir filtre silinince ona bağlı alanlar o anki değerle sabitlenir
  function unbindRefs(node, id, value) {
    if (Array.isArray(node)) return node.map((x) => unbindRefs(x, id, value));
    if (isRef(node)) return node.$var === id ? value : node;
    if (node && typeof node === "object") {
      const out = {};
      for (const [k, x] of Object.entries(node)) out[k] = unbindRefs(x, id, value);
      return out;
    }
    return node;
  }

  async function removeVar(v) {
    const users = state.current.widgets.filter((w) => widgetUsesVar(w, v.id));
    const sqlUsers = users.filter((w) => w.source.type === "sql" && sourceUsesVar(w, v.id));
    const text = users.length
      ? `${users.length} widget bu filtreyi kullanıyor. Kaldırınca bu widget'lar filtrenin şu anki değeriyle (${displayValue(v)}) sabitlenir.`
        + (sqlUsers.length ? ` ${sqlUsers.length} SQL widget'ında {{${v.id}}} ifadesini ayrıca düzeltmeniz gerekir.` : "")
      : "Bu filtreyi hiçbir widget kullanmıyor.";
    const ok = await ask({ title: `"${v.label}" filtresi kaldırılsın mı?`, text, input: false, ok: "Kaldır" });
    if (ok === null) return;
    const list = valueList(v);
    for (const w of state.current.widgets) {
      w.source = unbindRefs(w.source, v.id, v.multi ? list : list[0] || "");
      w.title = (w.title || "").replace(new RegExp(`\\{\\{\\s*${v.id}\\s*\\}\\}`, "g"), displayValue(v));
    }
    state.current.variables = vars().filter((x) => x !== v);
    renderFilterBar();
    users.forEach((w) => { paintHeader(w); loadWidget(w.id); });
    scheduleSave();
  }

  // ---- seçim listesi (açılır pencere)
  let openPop = null;
  function closePicker() {
    if (!openPop) return;
    openPop.remove();
    openPop = null;
    document.removeEventListener("mousedown", onDocDown, true);
  }
  function onDocDown(e) {
    if (openPop && !openPop.contains(e.target) && !openPop._anchor.contains(e.target)) closePicker();
  }
  function openPicker(anchor, { type, multi, value, onChange }) {
    if (openPop?._anchor === anchor) { closePicker(); return; }
    closePicker();
    const options = varOptions(type) || [];
    let selected = Array.isArray(value) ? value.filter(Boolean) : value ? [value] : [];
    const pop = el("div", { class: "popover", role: "dialog", "aria-label": `${varTypeLabel(type)} seçin` });
    pop._anchor = anchor;
    const search = el("input", { type: "search", placeholder: type === "country" ? "Ülke ara…" : "Ara ya da yaz…", "aria-label": "Ara" });
    const list = el("div", { class: "opts", role: "listbox", "aria-multiselectable": String(!!multi) });
    pop.append(search, list);
    const commit = () => onChange(multi ? [...selected] : selected[0] || "");
    if (multi) {
      const clear = el("button", { type: "button", class: "btn", text: "Temizle (tümü)" });
      clear.addEventListener("click", () => { selected = []; commit(); draw(); });
      const done = el("button", { type: "button", class: "btn primary", text: "Tamam" });
      done.addEventListener("click", () => { closePicker(); anchor.focus(); });
      pop.appendChild(el("div", { class: "foot" }, [clear, done]));
    }
    const draw = () => {
      list.textContent = "";
      const typed = search.value.trim();
      const q = typed.toLocaleLowerCase("tr");
      const match = options.filter((o) => !q || o.toLocaleLowerCase("tr").includes(q));
      const items = [...selected.filter((s) => !q || s.toLocaleLowerCase("tr").includes(q)),
        ...match.filter((o) => !selected.includes(o))].slice(0, 200);
      const exact = typed && [...options, ...selected].some((o) => o.toLocaleLowerCase("tr") === q);
      if (typed && !exact && type !== "country") items.unshift({ free: typed });
      if (!items.length) list.appendChild(el("div", { class: "none", text: "Eşleşen yok" }));
      for (const it of items) {
        const val = typeof it === "string" ? it : it.free;
        const on = selected.includes(val);
        const b = el("button", { type: "button", class: "opt" + (on ? " active" : ""), role: "option", "aria-selected": String(on) },
          [el("span", { class: "tick", text: on ? "✓" : "" }), el("span", { text: typeof it === "string" ? it : `"${it.free}" kullan` })]);
        b.addEventListener("click", () => {
          if (multi) {
            selected = on ? selected.filter((s) => s !== val) : [...selected, val];
            commit();
            draw();
          } else {
            selected = [val];
            commit();
            closePicker();
            anchor.focus();
          }
        });
        list.appendChild(b);
      }
    };
    search.addEventListener("input", draw);
    search.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closePicker(); anchor.focus(); }
      if (e.key === "Enter") { e.preventDefault(); list.querySelector(".opt")?.click(); }
      if (e.key === "ArrowDown") { e.preventDefault(); list.querySelector(".opt")?.focus(); }
    });
    list.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closePicker(); anchor.focus(); }
      const opts = [...list.querySelectorAll(".opt")];
      const i = opts.indexOf(document.activeElement);
      if (e.key === "ArrowDown" && i >= 0) { e.preventDefault(); opts[Math.min(i + 1, opts.length - 1)].focus(); }
      if (e.key === "ArrowUp" && i >= 0) { e.preventDefault(); (i === 0 ? search : opts[i - 1]).focus(); }
    });
    (anchor.closest("dialog") || document.body).appendChild(pop);
    const r = anchor.getBoundingClientRect();
    pop.style.left = `${Math.max(8, Math.min(r.left, innerWidth - 288))}px`;
    const below = innerHeight - r.bottom;
    if (below < 320 && r.top > below) pop.style.bottom = `${innerHeight - r.top + 4}px`;
    else pop.style.top = `${r.bottom + 4}px`;
    openPop = pop;
    draw();
    search.focus();
    setTimeout(() => document.addEventListener("mousedown", onDocDown, true));
  }

  function pickerButton(v, onClick) {
    const list = valueList(v);
    const btn = el("button", { type: "button", class: "picker-btn", "aria-haspopup": "listbox",
      "aria-label": `${v.label || varTypeLabel(v.type)}: ${displayValue(v)}` });
    btn.appendChild(el("span", { class: "pv" + (list.length ? "" : " empty"),
      text: list.length ? list[0] : v.multi ? "Tümü" : "Seçin…" }));
    if (list.length > 1) btn.appendChild(el("span", { class: "count", text: `+${list.length - 1}` }));
    btn.insertAdjacentHTML("beforeend", `<svg aria-hidden="true"><use href="#i-chevron"/></svg>`);
    btn.title = displayValue(v);
    btn.addEventListener("click", () => onClick(btn));
    return btn;
  }

  function smallIcon(icon, title, onClick) {
    const b = el("button", { type: "button", class: "icon-btn fb-edit", title, "aria-label": title });
    b.innerHTML = `<svg><use href="#${icon}"/></svg>`;
    b.addEventListener("click", onClick);
    return b;
  }

  function renderFilterBar() {
    const bar = $("#filterBar");
    bar.textContent = "";
    if (!state.current) return;
    for (const v of vars()) {
      const btn = pickerButton(v, (anchor) => openPicker(anchor, { type: v.type, multi: v.multi, value: v.value,
        onChange: (val) => setVarValue(v, val) }));
      const used = state.current.widgets.filter((w) => widgetUsesVar(w, v.id)).length;
      btn.title = `${displayValue(v)} — ${used ? `${used} widget'ı etkiler` : "Henüz hiçbir widget bu filtreye bağlı değil"}`;
      if (!used) btn.classList.add("unused");
      const label = el("div", { class: "fb-label" }, [el("span", { text: v.label || varTypeLabel(v.type) }),
        smallIcon("i-gear", "Filtreyi düzenle", () => openVarDialog(v)),
        smallIcon("i-x", "Filtreyi kaldır", () => removeVar(v))]);
      bar.appendChild(el("div", { class: "fb-item" }, [label, btn]));
    }
    if (state.editing) {
      const add = el("button", { type: "button", class: "btn fb-add fb-edit" });
      add.innerHTML = `<svg aria-hidden="true"><use href="#i-filter"/></svg>Filtre ekle`;
      add.addEventListener("click", () => openVarDialog(null));
      bar.appendChild(add);
    }
  }

  function openVarDialog(existing, { type, label, value, onCreate } = {}) {
    const dlg = $("#varDialog");
    const draft = existing
      ? { ...existing, value: structuredClone(existing.value) }
      : { id: "", label: label || "", type: type || "country", multi: false, value: value ?? "", pick: true };
    if (!existing) draft.id = uniqueVarId(draft.type);
    $("#varTitle").textContent = existing ? "Filtreyi düzenle" : "Filtre ekle";
    $("#varSubmit").textContent = existing ? "Kaydet" : "Ekle";
    $("#varError").textContent = "";
    const typeSel = $("#varType"), lab = $("#varLabel"), multi = $("#varMulti"), pick = $("#varPick");
    typeSel.value = draft.type;
    typeSel.disabled = !!existing || !!type;
    lab.value = draft.label;
    lab.placeholder = varTypeLabel(draft.type);
    multi.checked = !!draft.multi;
    pick.checked = draft.pick !== false;
    const renderValue = () => {
      const box = $("#varValue");
      box.textContent = "";
      box.appendChild(pickerButton(draft, (anchor) => openPicker(anchor, { type: draft.type, multi: draft.multi,
        value: draft.value, onChange: (val) => { draft.value = val; renderValue(); } })));
      $("#varCode").textContent = `{{${draft.id}}}`;
    };
    typeSel.onchange = () => {
      draft.type = typeSel.value;
      draft.id = uniqueVarId(draft.type);
      draft.value = draft.multi ? [] : "";
      lab.placeholder = varTypeLabel(draft.type);
      renderValue();
    };
    multi.onchange = () => {
      draft.multi = multi.checked;
      const cur = valueList(draft);
      draft.value = draft.multi ? cur : cur[0] || "";
      renderValue();
    };
    renderValue();
    $("#varForm").onsubmit = (e) => {
      e.preventDefault();
      closePicker();
      draft.label = lab.value.trim() || varTypeLabel(draft.type);
      draft.pick = pick.checked;
      if (existing) Object.assign(existing, draft);
      else state.current.variables = [...vars(), draft];
      dlg.close();
      renderFilterBar();
      reloadUsing(draft.id);
      scheduleSave();
      onCreate?.(existing || draft);
    };
    dlg.querySelectorAll("[data-close]").forEach((b) => { b.onclick = () => { closePicker(); dlg.close(); }; });
    dlg.addEventListener("close", closePicker, { once: true });
    dlg.showModal();
    lab.focus();
  }

  /* Widget ayarlarında "Sabit değer / Filtre: X / + Yeni filtre" seçimi */
  function bindSelect(varType, current, onBind, newDefaults) {
    const compatible = vars().filter((v) => v.type === varType);
    const opts = [{ value: "", label: "Sabit değer" },
      ...compatible.map((v) => ({ value: v.id, label: `Filtreye bağlı: ${v.label}` })),
      { value: "__new__", label: `+ Yeni "${varTypeLabel(varType)}" filtresi oluştur ve bağla` }];
    const sel = selectEl(opts, isRef(current) ? current.$var : "", { "aria-label": "Değer kaynağı" });
    sel.addEventListener("change", () => {
      if (sel.value === "__new__") {
        sel.value = isRef(current) ? current.$var : "";
        openVarDialog(null, { type: varType, ...newDefaults(), onCreate: (v) => onBind(v.id) });
      } else {
        onBind(sel.value || null);
      }
    });
    return el("div", { class: "bind-row" }, [sel]);
  }

  function boundNote(id) {
    const v = varById(id);
    const note = el("div", { class: "bound-note" });
    note.innerHTML = `<svg aria-hidden="true"><use href="#i-filter"/></svg>`;
    note.appendChild(el("span", { text: v ? `Üstteki "${v.label}" filtresinden: ${displayValue(v)}` : `Filtre bulunamadı (${id})` }));
    return note;
  }

  $("#varDialog").addEventListener("cancel", closePicker);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && openPop) closePicker(); });
  window.addEventListener("resize", closePicker);

  // ------------------------------------------------------------------ başlangıç
  async function init() {
    applyTheme(store.get("md-theme"));
    initGrid();
    try {
      state.meta = await api("/api/meta");
    } catch (err) {
      $("#emptyState").hidden = false;
      $("#emptyState h3").textContent = "Sunucuya bağlanılamadı";
      $("#emptyState p").textContent = err.message;
      return;
    }
    if (state.meta.last_update) {
      $("#lastUpdate").textContent = "Veri: " + Charts.fmt(state.meta.last_update, "datetime");
    }
    buildLibrary();
    await refreshDashboardList();
    const saved = store.get("md-dashboard");
    const start = state.dashboards.find((d) => String(d.id) === saved) || state.dashboards[0];
    if (start) await openDashboard(start.id);
    else await newDashboard("Yeni dashboard");
    setEditing(store.get("md-editing") === "1" || !state.current.widgets.length);
  }

  init();
})();
