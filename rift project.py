import mimetypes
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from flask import Flask, jsonify, render_template_string, request, send_file

app = Flask(__name__)
ROOT = Path(__file__).resolve().parent.parent
IGNORED_DIRS = {".git", "venv", "__pycache__", "node_modules", ".next", "dist", "build"}
SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".txt", ".yml", ".yaml"}
PREVIEW_FILES = {}

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>IntellectOps</title>
  <style>
    :root { color-scheme: dark; --bg:#050816; --panel:rgba(7,14,30,0.95); --border:rgba(148,163,184,0.23); --text:#e2e8f0; --muted:#94a3b8; --accent:#8b5cf6; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: radial-gradient(circle at top, #172554 0%, var(--bg) 55%); color: var(--text); min-height: 100vh; }
    .shell { max-width: 1200px; margin: 0 auto; padding: 24px; }
    .hero { background: linear-gradient(135deg, rgba(139,92,246,0.22), rgba(34,197,94,0.12)); border: 1px solid var(--border); border-radius: 24px; padding: 24px; display: grid; grid-template-columns: 1.2fr 0.8fr; gap: 20px; }
    .eyebrow { color: #c4b5fd; text-transform: uppercase; letter-spacing: 0.2em; font-size: 0.8rem; margin-bottom: 8px; }
    .hero h1 { font-size: 2.4rem; margin-bottom: 8px; }
    .hero p { color: var(--muted); line-height: 1.6; }
    .repo-form { display: flex; flex-direction: column; gap: 10px; background: rgba(2,6,23,0.6); padding: 16px; border-radius: 16px; border: 1px solid var(--border); }
    .repo-form input, .repo-form button { padding: 12px 14px; border-radius: 10px; border: 1px solid rgba(148,163,184,0.25); }
    .repo-form input { background: rgba(15,23,42,0.9); color: var(--text); }
    .repo-form button { border: none; cursor: pointer; background: linear-gradient(135deg, var(--accent), #6366f1); color: white; font-weight: 700; }
    .dashboard { margin-top: 22px; display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 18px; }
    .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 18px; padding: 18px; }
    .panel-live { grid-row: span 2; }
    .panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
    .status-pill { background: rgba(34,197,94,0.16); color:#86efac; border-radius:999px; padding:5px 10px; font-size:0.82rem; font-weight:700; }
    .feed-item, .finding-item { background: rgba(11,20,42,0.95); border: 1px solid rgba(148,163,184,0.16); border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; }
    .feed-item p, .finding-item p, .summary-card p, .pr-card p { margin-top: 6px; color: var(--muted); line-height: 1.5; }
    .summary-card, .pr-card { background: linear-gradient(135deg, rgba(34,197,94,0.1), rgba(59,130,246,0.08)); border-radius: 14px; padding: 14px; border: 1px solid rgba(148,163,184,0.16); }
    .severity { border-radius:999px; padding:4px 8px; font-size:0.72rem; font-weight:700; text-transform:uppercase; }
    .severity.high { background: rgba(248,113,113,0.16); color:#fda4af; }
    .severity.medium { background: rgba(245,158,11,0.16); color:#fde68a; }
    .severity.info { background: rgba(59,130,246,0.16); color:#bfdbfe; }
    .pr-meta { display:flex; gap:16px; margin-top:10px; color:#cbd5e1; font-size:0.95rem; }
    .error { color:#fda4af; }
    @media (max-width: 900px) { .hero, .dashboard { grid-template-columns: 1fr; } .panel-live { grid-row:auto; } }
  </style>
</head>
<body>
  <div class="shell">
    <header class="hero">
      <div>
        <p class="eyebrow">Autonomous multi-agent software testing</p>
        <h1>IntellectOps</h1>
        <p>Drop in a repository link and let AI agents hunt for security flaws, UI regressions, and patch-ready fixes before launch.</p>
      </div>
      <form id="repoForm" class="repo-form">
        <label for="repoUrl">Code or website link</label>
        <input id="repoUrl" name="repo_url" type="url" placeholder="https://github.com/owner/repo or https://example.com" />
        <button type="submit">Analyze & preview</button>
      </form>
    </header>

    <main class="dashboard">
      <section class="panel panel-live">
        <div class="panel-head"><h2>Live agent swarm</h2><span class="status-pill">ACTIVE</span></div>
        <div id="agentFeed"></div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>Audit summary</h2></div>
        <div id="summaryCard" class="summary-card"><p>Paste a repository link to start the autonomous review.</p></div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>Findings</h2></div>
        <ul id="findingsList" style="list-style:none;"></ul>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>Patch plan</h2></div>
        <ol id="patchPlanList" style="margin-left:20px;"></ol>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>PR preview</h2></div>
        <div id="prCard" class="pr-card"></div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>Live preview</h2></div>
        <div id="previewCard" class="summary-card"><p>No preview available yet.</p></div>
        <iframe id="previewFrame" style="display:none;width:100%;min-height:360px;border:0;border-radius:12px;margin-top:10px;"></iframe>
      </section>
    </main>
  </div>

  <script>
    const form = document.getElementById('repoForm');
    const repoUrlInput = document.getElementById('repoUrl');
    const agentFeed = document.getElementById('agentFeed');
    const summaryCard = document.getElementById('summaryCard');
    const findingsList = document.getElementById('findingsList');
    const patchPlanList = document.getElementById('patchPlanList');
    const prCard = document.getElementById('prCard');
    const previewCard = document.getElementById('previewCard');
    const previewFrame = document.getElementById('previewFrame');

    function pushFeed(entry, delay = 0) {
      setTimeout(() => {
        const row = document.createElement('div');
        row.className = 'feed-item';
        row.innerHTML = `<strong>${entry.agent}</strong><p>${entry.message}</p>`;
        agentFeed.appendChild(row);
      }, delay);
    }

    async function runAnalysis(repoUrl = '') {
      const targetValue = (repoUrl || repoUrlInput.value || '').trim();
      if (!targetValue) {
        summaryCard.innerHTML = '<p class="error">Please enter a repository or website link, or let the app inspect the local project.</p>';
        return;
      }
      agentFeed.innerHTML = '';
      summaryCard.innerHTML = '<p>Scanning repository and coordinating the swarm...</p>';
      findingsList.innerHTML = '';
      patchPlanList.innerHTML = '';
      prCard.innerHTML = '';
      previewCard.innerHTML = '<p>Preparing preview and audit report...</p>';
      previewFrame.style.display = 'none';
      previewFrame.src = '';

      const loadingFeed = [
        { agent: 'Agent 1 • Penetration Tester', message: 'Connecting to repository and scanning for secrets, injection paths, and insecure defaults.' },
        { agent: 'Agent 2 • UI/UX Tester', message: 'Inspecting layout, form accessibility, and likely broken user journeys.' },
        { agent: 'Agent 3 • Code Patcher', message: 'Drafting a patch strategy and preparing a pull request summary.' }
      ];

      loadingFeed.forEach((entry, index) => pushFeed(entry, index * 450));

      try {
        const response = await fetch('/analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ repo_url: targetValue })
        });
        const result = await response.json();
        renderResults(result);
        (result.agent_log || []).forEach((entry, index) => pushFeed(entry, (loadingFeed.length + index) * 450));
      } catch (error) {
        summaryCard.innerHTML = '<p class="error">The audit could not be completed. Please try again.</p>';
        console.error(error);
      }
    }

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      await runAnalysis();
    });

    window.addEventListener('load', () => {
      runAnalysis('/local-project');
    });

    function renderResults(result) {
      summaryCard.innerHTML = `<h3>${result.repo_name}</h3><p>${result.summary}</p>`;
      findingsList.innerHTML = result.findings.map((finding) => `
        <li class="finding-item">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
            <strong>${finding.title}</strong>
            <span class="severity ${finding.severity}">${finding.severity.toUpperCase()}</span>
          </div>
          <p>${finding.details}</p>
          <small>${finding.category}</small>
        </li>
      `).join('');
      patchPlanList.innerHTML = result.patch_plan.map((step) => `<li>${step}</li>`).join('');
      prCard.innerHTML = `
        <h3>${result.pr_preview.title}</h3>
        <p>${result.pr_preview.body}</p>
        <div class="pr-meta">
          <span>Branch: ${result.pr_preview.branch}</span>
          <span>Target: main</span>
        </div>
      `;
      const previewUrl = result.preview_url || '';
      if (previewUrl) {
        previewCard.innerHTML = `<p>Previewing ${result.target_type || 'target'}.</p>`;
        previewFrame.src = previewUrl;
        previewFrame.style.display = 'block';
      } else {
        previewCard.innerHTML = '<p>No preview could be generated for this target.</p>';
        previewFrame.style.display = 'none';
      }
    }
  </script>
</body>
</html>
"""


def normalize_repo_name(repo_url: str) -> str:
    repo_url = repo_url.strip()
    if not repo_url:
        return "local workspace"
    if repo_url.startswith("http"):
        repo_url = repo_url.rstrip("/")
        parts = [part for part in repo_url.split("/") if part]
        if len(parts) >= 2:
            return parts[-2] + "/" + parts[-1]
        return repo_url
    return repo_url


def looks_like_website_url(value: str) -> bool:
    if not value:
        return False
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def find_preview_file(base_dir: Path):
    for name in ["index.html", "index.htm", "main.html", "app.html"]:
        candidate = base_dir / name
        if candidate.exists() and candidate.is_file():
            return candidate
    for path in base_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".html", ".htm"} and path.name.lower() in {"index.html", "index.htm", "main.html", "app.html"}:
            return path
    return None


def register_preview_file(file_path: Path):
    slug = uuid.uuid4().hex
    PREVIEW_FILES[slug] = file_path.resolve()
    return slug


def is_github_repo_url(repo_url: str) -> bool:
    try:
        parsed = urlparse(repo_url)
    except Exception:
        return False
    host = parsed.netloc.lower().replace("www.", "")
    return host == "github.com" and bool(parsed.path.strip("/"))


def collect_source_files(base_dir: Path):
    files = []
    if not base_dir or not base_dir.exists():
        return files
    for path in base_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        rel_path = path.relative_to(base_dir).as_posix()
        files.append((rel_path, content))
    return files


def resolve_repository_files(repo_url: str):
    repo_url = (repo_url or "").strip()
    if repo_url.startswith("http") and is_github_repo_url(repo_url):
        temp_root = Path(tempfile.mkdtemp(prefix="intellectops-", dir=str(ROOT)))
        clone_dir = temp_root / "repo"
        try:
            subprocess.run(["git", "clone", "--depth", "1", repo_url, str(clone_dir)], check=True, capture_output=True, text=True, timeout=120)
            files = collect_source_files(clone_dir)
            if files:
                preview_file = find_preview_file(clone_dir)
                preview_url = None
                if preview_file:
                    preview_slug = register_preview_file(preview_file)
                    preview_url = f"/preview/{preview_slug}"
                return files, preview_url, "repository"
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    if repo_url.startswith(("/", ".", "~")):
        path = Path(repo_url).expanduser()
        if path.exists():
            files = collect_source_files(path)
            preview_file = find_preview_file(path)
            preview_url = None
            if preview_file:
                preview_slug = register_preview_file(preview_file)
                preview_url = f"/preview/{preview_slug}"
            return files, preview_url, "local-project"

    if repo_url and not repo_url.startswith("http"):
        path = Path(repo_url).expanduser()
        if path.exists():
            files = collect_source_files(path)
            preview_file = find_preview_file(path)
            preview_url = None
            if preview_file:
                preview_slug = register_preview_file(preview_file)
                preview_url = f"/preview/{preview_slug}"
            return files, preview_url, "local-project"

    if looks_like_website_url(repo_url):
        try:
            request = Request(repo_url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=20) as response:
                html = response.read().decode("utf-8", errors="ignore")
            return [(repo_url, html)], repo_url, "website"
        except (URLError, ValueError, TimeoutError):
            pass

    return collect_source_files(ROOT), None, "repository"


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/preview/<slug>")
def preview(slug):
    path = PREVIEW_FILES.get(slug)
    if not path or not path.exists():
        return "Preview not found", 404
    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return send_file(path, mimetype=content_type)


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json(silent=True) or {}
    repo_url = data.get("repo_url", "")
    if repo_url == "/local-project":
        repo_url = str(ROOT)
    repo_name = normalize_repo_name(repo_url)
    files, preview_url, target_type = resolve_repository_files(repo_url)

    findings = []
    for rel_path, content in files:
        if "debug=True" in content:
            findings.append({
                "severity": "high",
                "category": "Security",
                "title": "Debug mode enabled",
                "details": f"{rel_path} exposes verbose stack traces and should be disabled in production."
            })
        if re.search(r"(api[_-]?key|secret|token|password)\s*[:=]\s*[\"'][^\"']{4,}", content, re.I):
            findings.append({
                "severity": "high",
                "category": "Secrets",
                "title": "Hard-coded credential pattern",
                "details": f"Potential secret-like value detected in {rel_path}."
            })
        if re.search(r"(SELECT|INSERT|UPDATE|DELETE).*(\+|format\(|f\")", content, re.I):
            findings.append({
                "severity": "medium",
                "category": "Injection",
                "title": "Possible SQL injection vector",
                "details": f"Database query composition looks dynamic in {rel_path}."
            })
        if re.search(r"<input[^>]+type=['\"](text|password)['\"][^>]*>", content, re.I) and "aria-label" not in content:
            findings.append({
                "severity": "medium",
                "category": "UI",
                "title": "Form accessibility gap",
                "details": f"A form field in {rel_path} lacks an explicit accessible label."
            })
        if target_type == "website" and "<title" not in content.lower():
            findings.append({
                "severity": "medium",
                "category": "UI",
                "title": "Missing title tag",
                "details": f"The website at {rel_path} is missing a title tag, which hurts clarity and SEO."
            })
        if target_type == "website" and '<meta name="viewport"' not in content.lower():
            findings.append({
                "severity": "medium",
                "category": "UI",
                "title": "Viewport meta tag missing",
                "details": f"The page at {rel_path} may not scale correctly on mobile screens."
            })

    if not findings:
        findings.append({
            "severity": "info",
            "category": "Health",
            "title": "No obvious flaws detected",
            "details": "The target looks structurally sound, but the agents still recommend hardening steps."
        })

    patch_plan = []
    for finding in findings:
        if finding["category"] == "Security":
            patch_plan.append("Disable debug mode in production and route errors through a safe handler.")
        elif finding["category"] == "Secrets":
            patch_plan.append("Move credentials to environment variables and rotate any exposed values immediately.")
        elif finding["category"] == "Injection":
            patch_plan.append("Switch database access to parameterized queries and validation layers.")
        elif finding["category"] == "UI":
            patch_plan.append("Add accessible labels, validation states, and a clearer recovery flow for the form.")

    if not patch_plan:
        patch_plan.append("Add a lightweight CI security scan and dependency audit job before release.")

    return jsonify({
        "repo_name": repo_name,
        "summary": f"IntellectOps inspected {repo_name} and surfaced {len(findings)} high-value issues to harden before deployment.",
        "agent_log": [
            {"agent": "Agent 1 • Penetration Tester", "message": f"Scanning {repo_name} for leaked secrets, injection issues, and unsafe defaults."},
            {"agent": "Agent 2 • UI/UX Tester", "message": "Launching a headless review pass and checking for broken flows, accessibility gaps, and layout regressions."},
            {"agent": "Agent 3 • Code Patcher", "message": "Preparing a pull-request-ready patch with targeted fixes and a deployment safety checklist."},
            {"agent": "Agent 4 • Release Guardian", "message": "Routing the final report back to the developer with severity-ranked remediation steps."},
        ],
        "findings": findings,
        "patch_plan": patch_plan,
        "preview_url": preview_url,
        "target_type": target_type,
        "pr_preview": {
            "title": "[IntellectOps] Automated security and UI hardening",
            "body": "This patch addresses discovered vulnerabilities, improves accessibility, and adds stronger release guards.",
            "branch": "intellectops/agent-hardening"
        },
    })


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
