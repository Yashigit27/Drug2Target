(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  let catalog = null;
  let pollTimer = null;
  let currentArtifact = "known_genes";
  let selectedRunId = sessionStorage.getItem("d2t_run_id") || "";
  let currentUser = null;
  let authTab = "login";

  async function apiFetch(url, options = {}) {
    const res = await fetch(url, { credentials: "include", ...options });
    if (res.status === 401 && !url.includes("/api/auth/")) {
      openAuthModal();
      throw new Error("Authentication required");
    }
    return res;
  }

  async function refreshAuth() {
    try {
      const res = await fetch("/api/auth/me", { credentials: "include" });
      const data = await res.json();
      currentUser = data.authenticated ? data : null;
    } catch {
      currentUser = null;
    }
    updateAuthUI();
  }

  function updateAuthUI() {
    const label = $("#nav-user-label");
    const loginBtn = $("#btn-auth-open");
    const logoutBtn = $("#btn-auth-logout");
    if (!label || !loginBtn || !logoutBtn) return;
    if (currentUser) {
      label.textContent = currentUser.name || currentUser.email;
      label.classList.remove("hidden");
      loginBtn.classList.add("hidden");
      logoutBtn.classList.remove("hidden");
    } else {
      label.classList.add("hidden");
      loginBtn.classList.remove("hidden");
      logoutBtn.classList.add("hidden");
    }
  }

  function openAuthModal(tab) {
    authTab = tab || authTab;
    const modal = $("#auth-modal");
    if (!modal) return;
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
    setAuthTab(authTab);
  }

  function closeAuthModal() {
    const modal = $("#auth-modal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    const err = $("#auth-error");
    if (err) err.classList.add("hidden");
  }

  function setAuthTab(tab) {
    authTab = tab;
    $$(".auth-tab").forEach((t) => t.classList.toggle("active", t.dataset.authTab === tab));
    const nameWrap = $("#auth-name-wrap");
    const title = $("#auth-modal-title");
    const submit = $("#auth-submit");
    if (tab === "register") {
      nameWrap?.classList.remove("hidden");
      if (title) title.textContent = "Create account";
      if (submit) submit.textContent = "Register";
    } else {
      nameWrap?.classList.add("hidden");
      if (title) title.textContent = "Sign in";
      if (submit) submit.textContent = "Sign in";
    }
  }

  function bindAuthUI() {
    $("#btn-auth-open")?.addEventListener("click", () => openAuthModal("login"));
    $("#btn-auth-logout")?.addEventListener("click", async () => {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
      currentUser = null;
      updateAuthUI();
    });
    $("#auth-modal-close")?.addEventListener("click", closeAuthModal);
    $("#auth-modal-backdrop")?.addEventListener("click", closeAuthModal);
    $$(".auth-tab").forEach((tab) => {
      tab.addEventListener("click", () => setAuthTab(tab.dataset.authTab));
    });
    $("#auth-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const errEl = $("#auth-error");
      const email = $("#auth-email")?.value?.trim();
      const password = $("#auth-password")?.value;
      const name = $("#auth-name")?.value?.trim() || null;
      const url = authTab === "register" ? "/api/auth/register" : "/api/auth/login";
      const body = authTab === "register" ? { email, password, name } : { email, password };
      try {
        const res = await fetch(url, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await res.json();
        if (!res.ok) {
          if (errEl) {
            errEl.textContent = data.detail || "Authentication failed";
            errEl.classList.remove("hidden");
          }
          return;
        }
        currentUser = data;
        updateAuthUI();
        closeAuthModal();
      } catch {
        if (errEl) {
          errEl.textContent = "Network error";
          errEl.classList.remove("hidden");
        }
      }
    });
  }

  bindAuthUI();
  refreshAuth();

  const PAGES = ["landing", "setup", "pipeline", "results", "report"];

  async function loadCatalog() {
    if (catalog) return catalog;
    const res = await fetch("/api/catalog");
    catalog = await res.json();
    return catalog;
  }

  function getRoute() {
    const hash = location.hash.slice(1) || "/";
    const parts = hash.replace(/^\//, "").split("/");
    const page = parts[0] || "landing";
    return PAGES.includes(page) ? page : "landing";
  }

  function showPage(name) {
    if (name !== "landing" && !currentUser) {
      openAuthModal("login");
      location.hash = "#/";
      name = "landing";
    }
    $$(".page").forEach((p) => p.classList.remove("active"));
    const el = document.getElementById(`page-${name}`);
    if (el) el.classList.add("active");

    const nav = $("#top-nav");
    if (name === "landing") {
      nav.classList.add("hidden");
    } else {
      nav.classList.remove("hidden");
      $$(".nav-links a").forEach((a) => {
        a.classList.toggle("active", a.dataset.nav === name);
      });
    }

    if (name === "pipeline") initPipelinePage();
    if (name === "results") initResultsPage();
    if (name === "report") initReportPage();
  }

  window.addEventListener("hashchange", () => {
    showPage(getRoute());
  });

  refreshAuth().then(() => showPage(getRoute()));

  $$("[data-tilt]").forEach((card) => {
    card.addEventListener("mousemove", (e) => {
      const r = card.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5;
      const y = (e.clientY - r.top) / r.height - 0.5;
      card.style.transform = `perspective(600px) rotateY(${x * 6}deg) rotateX(${-y * 6}deg) translateY(-4px)`;
    });
    card.addEventListener("mouseleave", () => {
      card.style.transform = "";
    });
  });

  $$(".approach-card").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".approach-card").forEach((b) => b.classList.remove("selected"));
      btn.classList.add("selected");
      $("#approach-input").value = btn.dataset.approach;
    });
  });

  $("#setup-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      approach: fd.get("approach"),
      disease: fd.get("disease"),
      subtype: fd.get("subtype") || null,
      tissue: fd.get("tissue") || null,
      run_id: fd.get("run_id") || null,
      disease_id: fd.get("disease_id") || null,
      skip_literature: fd.get("skip_literature") === "on",
      use_snakemake: fd.get("use_snakemake") === "on",
    };
    const btn = e.target.querySelector('button[type="submit"]');
    btn.disabled = true;
    btn.textContent = "Starting...";

    const res = await apiFetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    btn.disabled = false;
    btn.textContent = "Launch pipeline";

    if (!res.ok) {
      alert(data.detail || "Failed to start");
      return;
    }
    sessionStorage.setItem("d2t_job_id", data.job_id);
    sessionStorage.setItem("d2t_run_id", data.run_id);
    sessionStorage.setItem("d2t_approach", body.approach);
    selectedRunId = data.run_id;
    location.hash = "#/pipeline";
  });

  function stepsForApproach(approach) {
    const steps = [];
    if (!catalog) return steps;
    for (const layer of catalog.layers) {
      if (layer.id === "foundation") {
        steps.push(...layer.steps);
      } else if (layer.id === "fusion") {
        if (approach !== "foundation") steps.push(...layer.steps);
      } else if (approach === "both") {
        steps.push(...layer.steps);
      } else if (approach === "track_a" && layer.id === "track_a") {
        steps.push(...layer.steps);
      } else if (approach === "track_b" && layer.id === "track_b") {
        steps.push(...layer.steps);
      }
    }
    return steps;
  }

  function renderTimeline(stepDefs, statusMap, runningStep, jobRunning) {
    const wrap = $("#step-timeline");
    wrap.innerHTML = stepDefs
      .map((s, i) => {
        const st = statusMap[s.id];
        const isRunning = jobRunning && runningStep === s.id;
        const isDone = st?.done && !isRunning;
        let cls = "";
        if (isRunning) cls = "running";
        else if (isDone) cls = "done";
        const icon = isDone ? "OK" : isRunning ? ".." : i + 1;
        const extra =
          s.id === "step2" && st?.literature
            ? `<span class="step-extra">${st.literature}</span>`
            : "";
        return `<div class="step-row ${cls}" data-step="${s.id}">
          <div class="step-dot">${icon}</div>
          <div class="step-info">
            <strong>${s.name}</strong>
            <span>${s.summary}</span>
            ${extra}
          </div>
        </div>`;
      })
      .join("");
  }

  async function initPipelinePage() {
    await loadCatalog();
    const jobId = sessionStorage.getItem("d2t_job_id");
    const runId = sessionStorage.getItem("d2t_run_id");
    const approach = sessionStorage.getItem("d2t_approach") || "both";

    if (!jobId) {
      $("#pipeline-subtitle").textContent = "No active job. Start from Configure.";
      return;
    }

    const stepDefs = stepsForApproach(approach);
    $("#pipeline-meta").textContent = `Run ID: ${runId} | Approach: ${approach}`;

    if (pollTimer) clearInterval(pollTimer);

    const tick = async () => {
      const [jobRes, statusRes] = await Promise.all([
        apiFetch(`/api/jobs/${jobId}`),
        apiFetch(`/api/runs/${runId}/status`),
      ]);
      const job = await jobRes.json();
      const status = await statusRes.json();

      const statusMap = {};
      (status.steps || []).forEach((s) => {
        statusMap[s.id] = s;
      });

      let runningStep = null;
      const log = job.log || [];
      for (let i = log.length - 1; i >= 0; i--) {
        const m = log[i];
        if (m.startsWith(">> ")) {
          runningStep = m.slice(3).trim();
          if (runningStep === "trackA") runningStep = "stepA1";
          if (runningStep === "trackB") runningStep = "stepB1";
          if (runningStep === "snakemake workflow") runningStep = "step1";
          break;
        }
      }

      const jobRunning = job.status === "running";
      renderTimeline(stepDefs, statusMap, jobRunning ? runningStep : null, jobRunning);

      const done = stepDefs.filter((s) => {
        const st = statusMap[s.id];
        return st?.done && !(jobRunning && runningStep === s.id);
      }).length;
      const pct = stepDefs.length ? Math.round((done / stepDefs.length) * 100) : 0;
      $("#pipeline-progress").style.width = `${pct}%`;

      $("#pipeline-subtitle").textContent =
        job.status === "running"
          ? `Running... ${done}/${stepDefs.length} steps complete`
          : job.status === "completed"
            ? "Analysis complete"
            : job.status === "failed"
              ? "Analysis failed"
              : "Queued";

      $("#pipeline-log").textContent = log.join("\n");
      if (job.error) $("#pipeline-log").textContent += `\nERROR: ${job.error}`;

      if (job.status === "completed" || job.status === "failed") {
        clearInterval(pollTimer);
        $("#btn-to-results").classList.remove("hidden");
        if (job.status === "completed") $("#btn-to-report").classList.remove("hidden");
      }
    };

    tick();
    pollTimer = setInterval(tick, 2000);
  }

  async function loadRunsIntoSelect(selectEl, selected) {
    const res = await apiFetch("/api/runs");
    const data = await res.json();
    selectEl.innerHTML = "";
    data.runs.forEach((r) => {
      const opt = document.createElement("option");
      opt.value = r.run_id;
      opt.textContent = `${r.run_id} | ${r.disease || "?"}`;
      if (r.run_id === selected) opt.selected = true;
      selectEl.appendChild(opt);
    });
    if (!data.runs.length) {
      selectEl.innerHTML = '<option value="">No runs yet</option>';
    }
    return data.runs;
  }

  async function loadPreview(runId, artifact, targetEl) {
    targetEl.innerHTML = '<p class="placeholder-text">Loading...</p>';
    try {
      const res = await apiFetch(`/api/runs/${runId}/preview/${artifact}?limit=25`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      const cols = data.columns.slice(0, 7);
      const geneCol = data.columns.find((c) => /gene_symbol|gene/i.test(c));
      let html = `<table class="data-table"><thead><tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>`;
      data.rows.forEach((row) => {
        const gene = geneCol ? row[geneCol] : null;
        const attrs = gene
          ? ` class="gene-row" data-gene="${escapeHtml(String(gene))}" title="Click to load evidence for ${escapeHtml(String(gene))}"`
          : "";
        html += `<tr${attrs}>` + cols.map((c) => `<td>${escapeHtml(row[c])}</td>`).join("") + "</tr>";
      });
      html += `</tbody></table><p class="placeholder-text">${data.rows.length} of ${data.rows_total} rows${geneCol ? " — click a row to load evidence" : ""}</p>`;
      targetEl.innerHTML = html;
    } catch {
      targetEl.innerHTML = '<p class="placeholder-text">Not available for this run.</p>';
    }
  }

  function currentResultsRunId() {
    const sel = $("#results-run-select");
    return (sel && sel.value) || selectedRunId || sessionStorage.getItem("d2t_run_id") || "";
  }

  async function downloadFile(url, filename) {
    const res = await apiFetch(url);
    if (!res.ok) {
      const err = await res.text();
      throw new Error(err || `Download failed (${res.status})`);
    }
    const blob = await res.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(href);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderNetworkGraphSVG(data) {
    const seeds = data.nodes.filter((n) => n.group === "seed");
    const cands = data.nodes.filter((n) => n.group === "candidate");
    const positions = {};
    const w = 760;
    const h = Math.max(340, 40 + cands.length * 18);
    seeds.forEach((n, i) => {
      positions[n.id] = { x: 90, y: 40 + i * (Math.min(280, h - 80) / Math.max(1, seeds.length - 1 || 1)) };
    });
    cands.forEach((n, i) => {
      positions[n.id] = { x: 520, y: 30 + i * ((h - 60) / Math.max(1, cands.length - 1 || 1)) };
    });
    const edges = data.edges.slice(0, 60);
    let svg = `<svg class="network-svg" viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">`;
    edges.forEach((e) => {
      const s = positions[e.source];
      const t = positions[e.target];
      if (!s || !t) return;
      const op = Math.min(0.85, 0.2 + (Number(e.weight) || 0) / 1000);
      svg += `<line x1="${s.x}" y1="${s.y}" x2="${t.x}" y2="${t.y}" stroke-opacity="${op.toFixed(2)}" />`;
    });
    data.nodes.forEach((n) => {
      const p = positions[n.id];
      if (!p) return;
      const cls = n.group === "seed" ? "seed" : "candidate";
      const r = n.group === "seed" ? 7 : 5;
      svg += `<circle class="${cls}" cx="${p.x}" cy="${p.y}" r="${r}" />`;
      svg += `<text x="${p.x + (n.group === "seed" ? -10 : 10)}" y="${p.y + 3}" text-anchor="${n.group === "seed" ? "end" : "start"}">${n.label}</text>`;
    });
    svg += `<text x="90" y="16" text-anchor="middle" font-size="10" fill="#14706c">Seeds</text>`;
    svg += `<text x="520" y="16" text-anchor="middle" font-size="10" fill="#8b5cf6">Candidates</text>`;
    svg += "</svg>";
    return svg;
  }

  async function loadNetworkGraph(runId) {
    const wrap = $("#network-graph-wrap");
    if (!wrap) return;
    if (!runId) {
      wrap.innerHTML = '<p class="placeholder-text">Select a run first.</p>';
      return;
    }
    wrap.innerHTML = '<p class="placeholder-text">Loading network...</p>';
    try {
      const res = await apiFetch(`/api/runs/${encodeURIComponent(runId)}/network?top_n=30`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      if (!data.edges || !data.edges.length) {
        wrap.innerHTML = `<p class="placeholder-text">${data.node_count || 0} nodes — no edge file yet. Rerun Track B to generate STRING edges.</p>`;
        return;
      }
      wrap.innerHTML = `<p class="network-meta">${data.node_count} nodes, ${data.edge_count} edges (showing up to 60)</p>${renderNetworkGraphSVG(data)}`;
    } catch (err) {
      wrap.innerHTML = `<p class="placeholder-text">Network graph error: ${err.message || "unavailable"}</p>`;
    }
  }

  function renderEvidenceHTML(card, narrative) {
    const lit = card.literature || {};
    const pmids = (lit.pmids || []).join(", ") || "none";
    const fusion = card.fusion || {};
    const net = card.network || {};
    let html = `<div class="ev-section"><div class="ev-label">Target</div><strong>${escapeHtml(card.gene_symbol)}</strong> — ${escapeHtml(card.disease)} (${escapeHtml(card.ontology_id || "")})<br/>Tissue: ${escapeHtml(card.tissue || "-")}</div>`;
    html += `<div class="ev-section"><div class="ev-label">Literature</div>PMIDs: ${escapeHtml(pmids)}<br/>Association score: ${escapeHtml(lit.association_score ?? "-")}<br/><span class="ev-snippet">${escapeHtml(lit.snippet || "No snippet stored.")}</span></div>`;
    if (fusion && Object.keys(fusion).length) {
      html += `<div class="ev-section"><div class="ev-label">Fusion</div>Tier: ${escapeHtml(fusion.tier || "-")} | Portfolio score: ${escapeHtml(fusion.portfolio_score ?? "-")} | Tracks: ${escapeHtml(fusion.source_tracks || "-")}</div>`;
    }
    if (net && Object.keys(net).length) {
      html += `<div class="ev-section"><div class="ev-label">Network</div>Seed count: ${escapeHtml(net.seed_count ?? "-")} | STRING score: ${escapeHtml(net.mean_string_score ?? net.prioritization_score ?? "-")}</div>`;
    }
    if (narrative && narrative.narrative) {
      html += `<div class="ev-section"><div class="ev-label">Narrative ${narrative.llm_used ? "(LLM)" : "(template)"}</div><p class="ev-narrative">${escapeHtml(narrative.narrative)}</p></div>`;
    }
    return html;
  }

  async function loadEvidenceCard(runId, gene) {
    const el = $("#evidence-card");
    if (!el) return;
    if (!runId || !gene) {
      el.innerHTML = '<p class="placeholder-text">Select a run and enter a gene symbol.</p>';
      return;
    }
    el.innerHTML = '<p class="placeholder-text">Loading evidence...</p>';
    try {
      const res = await apiFetch(`/api/runs/${encodeURIComponent(runId)}/evidence/${encodeURIComponent(gene)}`);
      if (!res.ok) throw new Error(await res.text());
      const card = await res.json();
      el.innerHTML = renderEvidenceHTML(card, null);
      const narrRes = await apiFetch(`/api/runs/${encodeURIComponent(runId)}/narrative/${encodeURIComponent(gene)}`);
      const narr = narrRes.ok ? await narrRes.json() : null;
      el.innerHTML = renderEvidenceHTML(card, narr);
    } catch (err) {
      el.innerHTML = `<p class="placeholder-text">Could not load evidence: ${err.message || "unknown error"}</p>`;
    }
  }

  let resultsPageBound = false;

  function bindResultsPageEvents() {
    if (resultsPageBound) return;
    resultsPageBound = true;

    document.addEventListener("click", async (e) => {
      const t = e.target;
      if (!(t instanceof HTMLElement)) return;

      if (t.id === "btn-download-zip") {
        e.preventDefault();
        const runId = currentResultsRunId();
        if (!runId) {
          alert("Select a run first.");
          return;
        }
        t.disabled = true;
        const label = t.textContent;
        t.textContent = "Preparing...";
        try {
          await downloadFile(`/api/runs/${encodeURIComponent(runId)}/download`, `${runId}_artifacts.zip`);
        } catch (err) {
          alert(err.message || "Download failed");
        } finally {
          t.disabled = false;
          t.textContent = label;
        }
      }

      if (t.id === "btn-evidence-load") {
        e.preventDefault();
        const gene = ($("#evidence-gene-input") || {}).value?.trim();
        loadEvidenceCard(currentResultsRunId(), gene);
      }

      const row = t.closest("tr.gene-row");
      if (row && row.dataset.gene) {
        const input = $("#evidence-gene-input");
        if (input) input.value = row.dataset.gene;
        loadEvidenceCard(currentResultsRunId(), row.dataset.gene);
        $("#evidence-card")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    });

    const evidenceInput = $("#evidence-gene-input");
    if (evidenceInput) {
      evidenceInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          const gene = evidenceInput.value.trim();
          loadEvidenceCard(currentResultsRunId(), gene);
        }
      });
    }
  }

  bindResultsPageEvents();

  async function initResultsPage() {
    const sel = $("#results-run-select");
    const runId = selectedRunId || sessionStorage.getItem("d2t_run_id");
    await loadRunsIntoSelect(sel, runId);
    if (sel.value) {
      selectedRunId = sel.value;
      await refreshResultsSummary(sel.value);
      await loadPreview(sel.value, currentArtifact, $("#results-table"));
      await loadNetworkGraph(sel.value);
    }

    sel.onchange = async () => {
      selectedRunId = sel.value;
      sessionStorage.setItem("d2t_run_id", sel.value);
      await refreshResultsSummary(sel.value);
      await loadPreview(sel.value, currentArtifact, $("#results-table"));
      await loadNetworkGraph(sel.value);
    };

    $$(".artifact-tabs .tab").forEach((tab) => {
      tab.onclick = () => {
        $$(".artifact-tabs .tab").forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        currentArtifact = tab.dataset.artifact;
        if (sel.value) loadPreview(sel.value, currentArtifact, $("#results-table"));
      };
    });

    const reportLink = $("#results-report-link");
    if (reportLink) {
      reportLink.onclick = () => {
        if (sel.value) sessionStorage.setItem("d2t_run_id", sel.value);
      };
    }
  }

  async function refreshResultsSummary(runId) {
    const res = await apiFetch(`/api/runs/${runId}/status`);
    const data = await res.json();
    const m = data.manifest;
    const el = $("#results-summary");
    if (!m) {
      el.innerHTML = runId;
      return;
    }
    const step2 = data.steps.find((s) => s.id === "step2");
    const litLine = step2?.literature ? `<br/>Step 2 literature: ${step2.literature}` : "";
    el.innerHTML = `<strong>${m.disease_resolution?.selected?.name}</strong> (${m.disease_resolution?.selected?.id})<br/>
      Tissue: ${m.input?.tissue || "-"} | Subtype: ${m.input?.disease_subtype || "-"}<br/>
      Steps complete: ${data.steps.filter((s) => s.done).length} / ${data.steps.length}${litLine}`;
  }

  let reportPageBound = false;

  function bindReportPageEvents() {
    if (reportPageBound) return;
    reportPageBound = true;
    document.addEventListener("click", async (e) => {
      const t = e.target;
      if (!(t instanceof HTMLElement) || t.id !== "btn-download-pdf") return;
      e.preventDefault();
      const sel = $("#report-run-select");
      const runId = sel && sel.value;
      if (!runId) {
        alert("Select a run first.");
        return;
      }
      t.disabled = true;
      const label = t.textContent;
      t.textContent = "Preparing...";
      try {
        await downloadFile(`/api/runs/${encodeURIComponent(runId)}/report.pdf`, `${runId}_report.pdf`);
      } catch (err) {
        alert(err.message || "PDF download failed");
      } finally {
        t.disabled = false;
        t.textContent = label;
      }
    });
  }

  bindReportPageEvents();

  async function initReportPage() {
    const sel = $("#report-run-select");
    const runId = selectedRunId || sessionStorage.getItem("d2t_run_id");
    await loadRunsIntoSelect(sel, runId);
    if (sel.value) renderReport(sel.value);

    sel.onchange = () => {
      sessionStorage.setItem("d2t_run_id", sel.value);
      renderReport(sel.value);
    };
  }

  async function renderReport(runId) {
    const wrap = $("#report-content");
    wrap.innerHTML = '<p class="placeholder-text">Generating report...</p>';
    try {
      const res = await apiFetch(`/api/runs/${runId}/report`);
      if (!res.ok) throw new Error();
      const data = await res.json();

      let html = `<div class="report-stats">
        <div class="stat-box"><div class="num">${data.known_gene_count}</div><div class="lbl">Known genes</div></div>
        <div class="stat-box"><div class="num">${data.steps_completed}</div><div class="lbl">Steps done</div></div>
        <div class="stat-box"><div class="num">${data.has_fusion ? "Yes" : "No"}</div><div class="lbl">Fusion F1</div></div>
        <div class="stat-box"><div class="num">${data.tissue || "-"}</div><div class="lbl">Tissue</div></div>
      </div>`;

      for (const sec of data.sections) {
        html += `<article class="report-section"><h3>${sec.title}</h3>`;
        if (sec.subtitle) html += `<p class="subtitle">${sec.subtitle}</p>`;
        if (sec.body) html += `<p>${sec.body}</p>`;
        if (sec.targets) {
          for (const t of sec.targets) {
            html += `<div class="target-card">
              <div class="rank">Rank #${t.rank}${t.tier ? ` | ${t.tier}` : ""}</div>
              <div class="gene">${t.gene}</div>
              <div class="score">Score: ${t.score}</div>
              <div class="explain">${t.explain}</div>
            </div>`;
          }
        }
        html += "</article>";
      }

      if (data.llm_narrative && data.llm_narrative.sections) {
        html += `<article class="report-section"><h3>LLM narrative (literature-grounded)</h3>`;
        for (const block of data.llm_narrative.sections) {
          html += `<div class="target-card">
            <div class="gene">${block.gene_symbol}${block.llm_used ? " (LLM)" : " (template)"}</div>
            <div class="explain">${block.narrative}</div>
            ${block.pmids_cited?.length ? `<div class="score">PMIDs: ${block.pmids_cited.join(", ")}</div>` : ""}
          </div>`;
        }
        html += "</article>";
      }
      wrap.innerHTML = html;
    } catch {
      wrap.innerHTML = '<p class="placeholder-text">Could not load report. Run pipeline first.</p>';
    }
  }
})();
