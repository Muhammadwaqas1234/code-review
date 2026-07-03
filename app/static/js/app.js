/* AI Code Review Dashboard — frontend logic.
 *
 * Security note: all dynamic values are inserted with textContent /
 * createElement, never innerHTML. The one exception is the Markdown report,
 * which is rendered with marked and sanitized with DOMPurify first; if either
 * library failed to load, the report falls back to plain text.
 */
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("review-form");
    const submitBtn = document.getElementById("submit-btn");
    const btnLabel = submitBtn.querySelector(".btn-label");
    const repoInput = document.getElementById("repo-url");
    const fileInput = document.getElementById("roles-file");
    const fileDrop = document.getElementById("file-drop");
    const fileDropText = document.getElementById("file-drop-text");

    const states = {
        empty: document.getElementById("empty-state"),
        loading: document.getElementById("loading-state"),
        error: document.getElementById("error-state"),
        results: document.getElementById("results-state"),
    };
    const loadingStatus = document.getElementById("loading-status");
    const errorMessage = document.getElementById("error-message");

    let statusTimers = [];
    let lastReportMarkdown = "";
    let lastResult = null;   // full response data, for the downloadable report
    let lastRepoLabel = "";

    const reviewerList = document.getElementById("reviewer-list");
    const toggleReviewers = document.getElementById("toggle-reviewers");

    // ---------------------------------------------------------- reviewers
    // Loaded from the backend so any rule set added there appears here with
    // no frontend change.
    loadReviewers();

    async function loadReviewers() {
        try {
            const response = await fetch("/api/reviewers");
            if (!response.ok) throw new Error();
            renderReviewers(await response.json());
        } catch {
            reviewerList.replaceChildren(
                el("p", "field-hint", "Could not load reviewers; all will run by default."));
        }
    }

    function renderReviewers(reviewers) {
        reviewerList.replaceChildren();
        for (const reviewer of reviewers) {
            const item = el("label", "reviewer-item");

            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.value = reviewer.id;
            checkbox.checked = true;
            checkbox.className = "reviewer-checkbox";

            item.append(checkbox, el("span", "reviewer-name", reviewer.name));
            reviewerList.append(item);
        }
    }

    function selectedReviewers() {
        return [...reviewerList.querySelectorAll(".reviewer-checkbox")]
            .filter((c) => c.checked)
            .map((c) => c.value);
    }

    toggleReviewers.addEventListener("click", () => {
        const boxes = [...reviewerList.querySelectorAll(".reviewer-checkbox")];
        const makeAllOn = boxes.some((c) => !c.checked);
        boxes.forEach((c) => { c.checked = makeAllOn; });
        toggleReviewers.textContent = makeAllOn ? "None" : "All";
    });

    // ---------------------------------------------------------- state switching
    function showState(name) {
        Object.entries(states).forEach(([key, el]) =>
            el.classList.toggle("hidden", key !== name));
    }

    function setLoadingStages() {
        const stages = [
            [0, "Cloning repository…"],
            [8000, "Reading source files and building the index…"],
            [20000, "Reviewer agents are analyzing the code…"],
            [60000, "Still reviewing — large repositories take longer…"],
            [120000, "Scoring findings and writing the report…"],
        ];
        statusTimers = stages.map(([delay, text]) =>
            setTimeout(() => { loadingStatus.textContent = text; }, delay));
    }

    function clearLoadingStages() {
        statusTimers.forEach(clearTimeout);
        statusTimers = [];
    }

    // ---------------------------------------------------------- file input UX
    fileInput.addEventListener("change", () => {
        const file = fileInput.files[0];
        fileDropText.textContent = file ? file.name : "Choose a PDF file…";
        fileDrop.classList.toggle("has-file", Boolean(file));
    });

    ["dragover", "dragleave", "drop"].forEach((evt) =>
        fileDrop.addEventListener(evt, (e) => {
            e.preventDefault();
            fileDrop.classList.toggle("dragover", evt === "dragover");
            if (evt === "drop" && e.dataTransfer.files.length) {
                fileInput.files = e.dataTransfer.files;
                fileInput.dispatchEvent(new Event("change"));
            }
        }));

    document.getElementById("error-dismiss").addEventListener("click", () =>
        showState("empty"));

    // ---------------------------------------------------------- submit
    form.addEventListener("submit", async (e) => {
        e.preventDefault();

        const repoUrl = repoInput.value.trim();
        const file = fileInput.files[0];  // optional
        if (!repoUrl) {
            showError("Enter a repository URL.");
            return;
        }

        const chosen = selectedReviewers();
        if (chosen.length === 0) {
            showError("Select at least one reviewer, or click “All”.");
            return;
        }

        const formData = new FormData();
        formData.append("repo_url", repoUrl);
        // The roles PDF is optional — it only adds context; the reviewer rules
        // are enforced either way.
        if (file) formData.append("roles_file", file);
        // Send the selection only when it's a real subset; empty = planner decides.
        const all = reviewerList.querySelectorAll(".reviewer-checkbox").length;
        if (chosen.length < all) formData.append("reviewers", chosen.join(","));

        submitBtn.disabled = true;
        btnLabel.textContent = "Reviewing…";
        showState("loading");
        loadingStatus.textContent = "Cloning repository…";
        setLoadingStages();

        try {
            const response = await fetch("/api/review", { method: "POST", body: formData });

            if (!response.ok) {
                throw new Error(await extractError(response));
            }

            renderResults(await response.json(), repoUrl);
            showState("results");
        } catch (err) {
            // Only fetch() itself throws a TypeError (server down / network).
            // Errors we throw for a non-ok response are plain Error objects.
            const message = err instanceof TypeError
                ? "Could not reach the server. Is it running?"
                : err.message;
            showError(message);
        } finally {
            clearLoadingStages();
            submitBtn.disabled = false;
            btnLabel.textContent = "Start review";
        }
    });

    function showError(message) {
        errorMessage.textContent = message;
        showState("error");
    }

    // Turn any error response into a readable message. FastAPI returns
    // {detail: "..."} for our HTTPExceptions but {detail: [{msg, loc}, ...]}
    // for 422 validation errors — handle both, and non-JSON bodies too.
    async function extractError(response) {
        const fallback = `The server returned an error (${response.status}).`;
        try {
            const body = await response.json();
            const detail = body && body.detail;
            if (typeof detail === "string") return detail;
            if (Array.isArray(detail) && detail.length) {
                return detail.map((d) => d.msg || String(d)).join("; ");
            }
            return fallback;
        } catch {
            return fallback;
        }
    }

    // ---------------------------------------------------------- rendering
    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function scoreBand(score) {
        if (score >= 80) return "good";
        if (score >= 55) return "warning";
        if (score >= 30) return "serious";
        return "critical";
    }

    function renderResults(data, repoUrl) {
        const repoLabel = (repoUrl || "").replace(/^https?:\/\/(www\.)?/, "").replace(/\.git$/, "");
        lastResult = data;
        lastRepoLabel = repoLabel;
        document.getElementById("results-repo").textContent = repoLabel;
        renderScore(data.score);
        renderCategories(data.score.category_scores || {});
        renderFindings(data.reviews || []);
        renderReport(data.report || "");
    }

    function renderScore(score) {
        const value = Math.round(score.final_score);
        document.getElementById("score-value").textContent = String(value);

        const badge = document.getElementById("risk-badge");
        const risk = (score.risk_level || "unknown").toLowerCase();
        badge.textContent = `${risk} risk`;
        badge.className = `badge risk-${risk}`;

        const wrap = document.getElementById("score-meter-wrap");
        wrap.className = `meter band-${scoreBand(value)}`;
        wrap.setAttribute("aria-label", `Overall score ${value} out of 100`);
        requestAnimationFrame(() => {
            document.getElementById("score-meter").style.width = `${value}%`;
        });

        document.getElementById("score-reasoning").textContent = score.reasoning || "";
    }

    function renderCategories(categoryScores) {
        const container = document.getElementById("category-bars");
        container.replaceChildren();

        const entries = Object.entries(categoryScores);
        if (!entries.length) {
            container.append(el("p", "field-hint", "No per-category scores were produced."));
            return;
        }

        for (const [category, rawValue] of entries) {
            const value = Math.round(rawValue);
            const row = el("div", "category-row");
            row.append(el("span", "category-name", category));

            const track = el("div", "category-track");
            const fill = el("div", "category-fill");
            track.setAttribute("role", "img");
            track.setAttribute("aria-label", `${category} score ${value} out of 100`);
            track.append(fill);
            row.append(track);

            row.append(el("span", "category-value", String(value)));
            container.append(row);
            requestAnimationFrame(() => { fill.style.width = `${value}%`; });
        }
    }

    const SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"];

    function renderFindings(reviews) {
        const container = document.getElementById("findings");
        container.replaceChildren();

        const allFindings = reviews.flatMap((r) => r.findings || []);
        const total = allFindings.length;

        // Severity summary bar — the shape of the review at a glance.
        container.append(renderSeveritySummary(allFindings));

        // Reviewer groups: expanded only when they contain a critical/high
        // finding, so the page opens focused on what matters instead of a wall.
        for (const review of reviews) {
            if ((review.findings || []).length || review.raw) {
                container.append(renderAgentGroup(review));
            }
        }

        const n = reviews.length;
        document.getElementById("findings-total").textContent =
            `${total} finding${total === 1 ? "" : "s"} across ${n} reviewer${n === 1 ? "" : "s"}`;
    }

    function renderSeveritySummary(findings) {
        const bar = el("div", "sev-summary");
        for (const sev of SEVERITY_ORDER) {
            const n = findings.filter((f) => f.severity === sev).length;
            const item = el("div", `sev-summary-item sev-${sev}${n ? "" : " is-zero"}`);
            item.append(el("span", "sev-summary-count", String(n)));
            item.append(el("span", "sev-summary-label", sev));
            bar.append(item);
        }
        return bar;
    }

    function renderAgentGroup(review) {
        const group = el("details", "agent-group");
        const findings = review.findings || [];
        // Expand only reviewers that found something serious; the rest start
        // collapsed so the reader isn't buried in low/info findings.
        group.open = findings.some((f) => f.severity === "critical" || f.severity === "high");

        const summary = el("summary");
        const head = el("div", "agent-head");
        head.append(el("span", "agent-name", review.agent));
        const counts = el("span", "agent-counts");
        for (const sev of SEVERITY_ORDER) {
            const n = findings.filter((f) => f.severity === sev).length;
            if (n) counts.append(el("span", `count-chip sev-${sev}`, `${n}`));
        }
        if (!findings.length) counts.append(el("span", "count-chip", "clear"));
        head.append(counts);
        summary.append(head);
        group.append(summary);

        const body = el("div", "agent-body");
        if (review.summary) body.append(el("p", "agent-summary", review.summary));

        const sorted = [...findings].sort((a, b) =>
            SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity));
        for (const finding of sorted) body.append(renderFinding(finding));

        if (review.raw) {
            body.append(el("p", "raw-note",
                "This reviewer's structured output could not be parsed; its raw notes were kept server-side."));
        }
        group.append(body);
        return group;
    }

    function renderFinding(finding) {
        const row = el("div", "finding");
        row.append(el("span", `sev-badge sev-${finding.severity}`, finding.severity));

        const body = el("div", "finding-body");
        if (finding.file) {
            const where = finding.line ? `${finding.file}:${finding.line}` : finding.file;
            body.append(el("p", "finding-file", where));
        }
        body.append(el("p", "finding-issue", finding.issue));
        if (finding.recommendation) {
            const fix = el("p", "finding-fix");
            fix.append(el("strong", null, "Fix: "), document.createTextNode(finding.recommendation));
            body.append(fix);
        }
        row.append(body);
        return row;
    }

    function renderReport(markdown) {
        lastReportMarkdown = markdown;
        const report = document.getElementById("report");

        if (window.marked && window.DOMPurify) {
            report.classList.remove("plain");
            report.innerHTML = DOMPurify.sanitize(marked.parse(markdown));
            colorCodeReportTable(report);
        } else {
            // Markdown libraries unavailable (offline / CDN blocked): show as text.
            report.classList.add("plain");
            report.textContent = markdown;
        }
    }

    // Tag each report-table row with its severity so CSS can color the
    // Severity cell — the report's findings table is where severity is most
    // scanned, and raw markdown gives it no visual weight.
    function colorCodeReportTable(report) {
        const known = new Set(SEVERITY_ORDER);
        report.querySelectorAll("table tbody tr").forEach((tr) => {
            const first = tr.querySelector("td");
            if (!first) return;
            const sev = first.textContent.trim().toLowerCase();
            if (known.has(sev)) tr.setAttribute("data-sev", sev);
        });
    }

    document.getElementById("copy-report").addEventListener("click", async (e) => {
        try {
            await navigator.clipboard.writeText(lastReportMarkdown);
            e.target.textContent = "Copied!";
            setTimeout(() => { e.target.textContent = "Copy Markdown"; }, 1600);
        } catch {
            e.target.textContent = "Copy failed";
            setTimeout(() => { e.target.textContent = "Copy Markdown"; }, 1600);
        }
    });

    // ---------------------------------------------------------- download report
    // Builds a self-contained, print-ready HTML document and opens it in a new
    // tab. The user saves it as a PDF via the browser's Print dialog — no
    // server round-trip, no extra dependency, and the styling is baked in.
    document.getElementById("download-report").addEventListener("click", () => {
        if (!lastResult) return;
        const html = buildReportDocument(lastResult, lastRepoLabel);
        const blob = new Blob([html], { type: "text/html" });
        const url = URL.createObjectURL(blob);
        const win = window.open(url, "_blank");
        // Give the new tab a moment to render, then open the print dialog.
        if (win) {
            win.addEventListener("load", () => setTimeout(() => win.print(), 400));
        }
        setTimeout(() => URL.revokeObjectURL(url), 60000);
    });

    function esc(s) {
        return String(s ?? "").replace(/[&<>"']/g, (c) => (
            { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    }

    function buildReportDocument(data, repoLabel) {
        const score = data.score || {};
        const value = Math.round(score.final_score || 0);
        const risk = (score.risk_level || "unknown").toLowerCase();
        const band = scoreBand(value);
        const reviews = data.reviews || [];
        const allFindings = reviews.flatMap((r) =>
            (r.findings || []).map((f) => ({ ...f, agent: r.agent })));
        const sevRank = (s) => SEVERITY_ORDER.indexOf(s);
        allFindings.sort((a, b) => sevRank(a.severity) - sevRank(b.severity));

        const sevCounts = SEVERITY_ORDER
            .map((s) => ({ s, n: allFindings.filter((f) => f.severity === s).length }))
            .filter((x) => x.n);

        const catRows = Object.entries(score.category_scores || {})
            .map(([c, v]) => `<tr><td>${esc(c)}</td><td class="num">${Math.round(v)}</td></tr>`)
            .join("");

        const findingRows = allFindings.map((f) => `
            <tr data-sev="${esc(f.severity)}">
                <td class="sev sev-${esc(f.severity)}">${esc(f.severity)}</td>
                <td class="mono">${esc(f.file || "—")}${f.line ? ":" + f.line : ""}</td>
                <td>${esc(f.issue)}</td>
                <td>${esc(f.recommendation || "")}</td>
            </tr>`).join("");

        const reportHtml = (window.marked && window.DOMPurify)
            ? DOMPurify.sanitize(marked.parse(data.report || ""))
            : `<pre>${esc(data.report || "")}</pre>`;

        const sevPills = sevCounts.map((x) =>
            `<span class="pill sev-${x.s}">${x.n} ${x.s}</span>`).join("");

        const now = new Date().toLocaleString();

        return `<!doctype html><html><head><meta charset="utf-8">
<title>Code Review Report — ${esc(repoLabel)}</title>
<style>
  :root{ --ink:#111; --sec:#444; --muted:#777; --line:#e2e2dd; --accent:#2a78d6;
         --crit:#d03b3b; --high:#96401e; --med:#7a5200; --low:#1c5cab; --info:#888; }
  *{ box-sizing:border-box; }
  body{ font-family:system-ui,-apple-system,"Segoe UI",sans-serif; color:var(--ink);
        margin:0; padding:48px 56px; font-size:13px; line-height:1.6; }
  h1{ font-size:24px; margin:0 0 2px; letter-spacing:-.4px; }
  .repo{ font-family:ui-monospace,Consolas,monospace; color:var(--muted); font-size:13px; }
  .meta{ color:var(--muted); font-size:11.5px; margin-top:4px; }
  .rule{ height:3px; background:var(--accent); width:64px; margin:14px 0 26px; border-radius:2px; }
  .top{ display:flex; gap:32px; align-items:flex-start; margin-bottom:26px; }
  .scorebox{ text-align:center; padding:18px 26px; border:1px solid var(--line);
             border-radius:12px; min-width:150px; }
  .scorebox .n{ font-size:44px; font-weight:700; line-height:1; }
  .scorebox .d{ color:var(--muted); font-size:12px; }
  .riskbadge{ display:inline-block; margin-top:8px; padding:3px 12px; border-radius:999px;
              font-size:11.5px; font-weight:700; text-transform:capitalize; }
  .risk-low{background:#e6f4e6;color:#136c13}.risk-medium{background:#fdf1d8;color:#7a5200}
  .risk-high{background:#fbe7dd;color:#96401e}.risk-critical{background:#fbe0e0;color:#c02a2a}
  .risk-unknown{background:#eee;color:#555}
  .summary{ flex:1; }
  .summary p{ margin:0; color:var(--sec); }
  .pills{ margin-top:12px; display:flex; flex-wrap:wrap; gap:6px; }
  .pill{ font-size:11px; font-weight:700; padding:3px 10px; border-radius:999px; text-transform:capitalize; }
  .pill.sev-critical,.sev.sev-critical{color:var(--crit)} .pill.sev-critical{background:#fbe0e0}
  .pill.sev-high,.sev.sev-high{color:var(--high)} .pill.sev-high{background:#fbe7dd}
  .pill.sev-medium,.sev.sev-medium{color:var(--med)} .pill.sev-medium{background:#fdf1d8}
  .pill.sev-low,.sev.sev-low{color:var(--low)} .pill.sev-low{background:#e2edfb}
  .pill.sev-info,.sev.sev-info{color:var(--info)} .pill.sev-info{background:#eee}
  h2{ font-size:13px; text-transform:uppercase; letter-spacing:.05em; margin:30px 0 10px;
      padding-bottom:7px; border-bottom:2px solid var(--accent); display:inline-block; }
  table{ width:100%; border-collapse:collapse; margin:8px 0 20px; font-size:12px; }
  th{ text-align:left; text-transform:uppercase; font-size:10px; letter-spacing:.05em;
      color:var(--muted); padding:8px 10px; border-bottom:1.5px solid var(--line); }
  td{ padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; color:var(--sec); }
  td.num{ text-align:right; font-weight:600; color:var(--ink); }
  td.sev{ font-weight:700; text-transform:capitalize; white-space:nowrap; }
  td.mono{ font-family:ui-monospace,Consolas,monospace; font-size:11px; color:var(--low); }
  .cat{ width:280px; }
  .cat td:first-child{ text-transform:capitalize; }
  .report p{ color:var(--sec); } .report strong{ color:var(--ink); }
  .report ul,.report ol{ margin:0 0 12px 20px; color:var(--sec); }
  .report code{ font-family:ui-monospace,Consolas,monospace; background:#f2f1ee;
                padding:1px 5px; border-radius:4px; font-size:11px; }
  .foot{ margin-top:34px; padding-top:14px; border-top:1px solid var(--line);
         color:var(--muted); font-size:10.5px; }
  @media print{ body{ padding:0; } h2{ break-after:avoid; } tr{ break-inside:avoid; } }
</style></head><body>
  <h1>Code Review Report</h1>
  <div class="repo">${esc(repoLabel)}</div>
  <div class="meta">Generated ${esc(now)}</div>
  <div class="rule"></div>

  <div class="top">
    <div class="scorebox">
      <div class="n">${value}</div>
      <div class="d">out of 100</div>
      <div class="riskbadge risk-${esc(risk)}">${esc(risk)} risk</div>
    </div>
    <div class="summary">
      <p>${esc(score.reasoning || "")}</p>
      <div class="pills">${sevPills || '<span class="pill sev-info">no findings</span>'}</div>
    </div>
  </div>

  ${catRows ? `<h2>Category Scores</h2>
  <table class="cat"><thead><tr><th>Category</th><th class="num">Score</th></tr></thead>
  <tbody>${catRows}</tbody></table>` : ""}

  <h2>Summary &amp; Recommendations</h2>
  <div class="report">${reportHtml}</div>

  <h2>All Findings (${allFindings.length})</h2>
  <table><thead><tr><th>Severity</th><th>Location</th><th>Issue</th><th>Recommended fix</th></tr></thead>
  <tbody>${findingRows || '<tr><td colspan="4">No findings.</td></tr>'}</tbody></table>

  <div class="foot">AI Code Review — multi-agent analysis (code quality, bugs, security,
       architecture, performance). This report is generated by automated reviewers and is
       intended as decision support, not a guarantee of correctness.</div>
</body></html>`;
    }
});
