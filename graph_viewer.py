#!/usr/bin/env python3
"""
Brain Graph Viewer
Run:  python3 ~/ProductBrain/graph_viewer.py
Open: http://localhost:4322
"""

import json, os, re, subprocess, threading, time, urllib.parse, zipfile
from collections import defaultdict
import xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

HOME = Path.home()
SCAN_DIRS = [
    HOME / "ProductBrain",          # rename to match your own folder
    HOME / "Documents" / "Notes",
    HOME / "Documents" / "Work",
    HOME / "Documents" / "Learning",
    HOME / "Downloads",
    HOME / ".claude",
    HOME,                           # picks up home-level docs (limited depth)
]
WRITE_DIR = HOME / "ProductBrain"   # rename to match your own folder
EXTENSIONS = {".md", ".docx", ".pdf", ".txt"}
EXCLUDE = {
    "node_modules", ".git", "__pycache__", "dist", "build", ".next",
    "skills", ".obsidian", "_deps", "cmake", "Library", "Applications",
    "Movies", "Music", "Pictures", "Public", "Desktop",
    ".cache", ".npm", ".vscode",
}
HOME_MAX_DEPTH = 2                            # how deep to scan from $HOME (after the dedicated dirs)
PORT = 4322
POLL_SECS = 5
PDFTOTEXT = "/opt/homebrew/bin/pdftotext"

# ── Text extraction ───────────────────────────────────────────────────────────

_text_cache: dict = {}   # path -> (mtime, text, word_set)
_cache_lock = threading.Lock()
_WORD_RE = re.compile(r'(?i)\b\w{4,}\b')

def extract_words(text: str) -> set:
    return set(_WORD_RE.findall(text))

def extract_text(path: Path) -> str:
    """Extract plain text from .md, .txt, .docx, .pdf. Cached by mtime."""
    try:
        mtime = path.stat().st_mtime
    except Exception:
        return ""
    pid = str(path)
    with _cache_lock:
        cached = _text_cache.get(pid)
        if cached and cached[0] == mtime:
            return cached[1]

    ext = path.suffix.lower()
    text = ""
    try:
        if ext in (".md", ".txt"):
            text = path.read_text(errors="ignore")
        elif ext == ".docx":
            text = _extract_docx(path)
        elif ext == ".pdf":
            text = _extract_pdf(path)
    except Exception:
        pass

    with _cache_lock:
        _text_cache[pid] = (mtime, text, extract_words(text))
    return text

def _extract_docx(path: Path) -> str:
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        if "word/document.xml" not in z.namelist():
            return ""
        xml_bytes = z.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    parts = []
    for para in root.iter(ns + "p"):
        words = [t.text for t in para.iter(ns + "t") if t.text]
        if words:
            parts.append("".join(words))
    return "\n".join(parts)

def _extract_pdf(path: Path) -> str:
    if not os.path.exists(PDFTOTEXT):
        return ""
    result = subprocess.run(
        [PDFTOTEXT, "-q", str(path), "-"],
        capture_output=True, timeout=15
    )
    return result.stdout.decode("utf-8", errors="ignore")

# ── Scanner ───────────────────────────────────────────────────────────────────

def _iter_files(base: Path):
    """Walk a directory, honouring EXCLUDE and capping depth when base is $HOME."""
    is_home = (base == HOME)
    base_depth = len(base.parts)
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in EXCLUDE and not d.startswith("~$")]
        rp = Path(root)
        if is_home and len(rp.parts) - base_depth > HOME_MAX_DEPTH:
            dirs[:] = []
            continue
        for f in files:
            if f.startswith("~$") or f.startswith("."):
                continue
            if Path(f).suffix.lower() in EXTENSIONS:
                yield rp / f


def scan():
    nodes = {}
    name_index = {}                           # lowercased stem -> path  (for wikilinks)
    for base in SCAN_DIRS:
        if not base.exists():
            continue
        for path in _iter_files(base):
            pid = str(path)
            if pid in nodes:
                continue
            try:
                folder = str(path.parent.relative_to(HOME))
            except ValueError:
                folder = str(path.parent)
            ext = path.suffix.lower().lstrip(".")
            nodes[pid] = {
                "id":     pid,
                "name":   path.stem,
                "path":   pid,
                "folder": folder,
                "ext":    ext,
                "size":   path.stat().st_size,
            }
            name_index.setdefault(path.stem.lower(), pid)

    wiki = re.compile(r'\[\[([^\]|#\n]+)')
    mdlnk = re.compile(r'\[[^\]]*\]\(([^)]+)\)')
    edges, seen = [], set()

    def add_edge(a, b, kind="link") -> bool:
        if a == b: return False
        key = tuple(sorted([a, b]))
        if key in seen: return False
        seen.add(key)
        edges.append({"source": a, "target": b, "kind": kind})
        return True

    # Read markdown files only (fast — no DOCX/PDF extraction in scan)
    md_contents = {}
    for pid, node in nodes.items():
        if node["ext"] == "md":
            try:
                md_contents[pid] = Path(pid).read_text(errors="ignore")
            except Exception:
                pass

    # Pass 1: explicit md links (wikilinks + markdown links)
    for pid, content in md_contents.items():
        path = Path(pid)
        for m in wiki.finditer(content):
            name = m.group(1).strip().lower()
            t = name_index.get(name)
            if t: add_edge(pid, t, "wiki")
        for m in mdlnk.finditer(content):
            raw = m.group(1).split("#")[0].split("?")[0]
            if raw.startswith(("http://", "https://", "mailto:")):
                continue
            t = str((path.parent / raw).resolve())
            if t in nodes: add_edge(pid, t, "link")

    # Pass 2: mention detection
    # 2a: build word→[md_pids] inverted index for O(1) stem lookup
    word_to_md: dict = {}
    for mpid, content in md_contents.items():
        for word in extract_words(content):
            word_to_md.setdefault(word, []).append(mpid)

    for pid, node in nodes.items():
        if node["ext"] == "md": continue
        stem_l = node["name"].lower()
        if len(stem_l) < 4: continue
        for mpid in word_to_md.get(stem_l, []):
            add_edge(mpid, pid, "mention")

    # 2b: cached DOCX/PDF — reuse stored word_set, no re-tokenisation
    with _cache_lock:
        cached_paths = dict(_text_cache)
    for pid, entry in cached_paths.items():
        if pid not in nodes or nodes[pid]["ext"] == "md": continue
        doc_words = entry[2] if len(entry) > 2 else extract_words(entry[1])
        if not doc_words: continue
        for other_pid, other_node in nodes.items():
            if other_pid == pid: continue
            stem = other_node["name"]
            if len(stem) < 4: continue
            if stem.lower() in doc_words:
                add_edge(pid, other_pid, "mention")

    # Pass 3: shared title tokens — O(n) inverted index
    STOP = {"the","a","an","of","in","on","for","and","or","to","with",
            "is","are","be","by","my","our","at","this","that","new","old",
            "v1","v2","ver","copy","final","draft","notes","note","md","pdf","docx"}
    def tokens(name):
        parts = re.split(r"[\s_\-\.\(\)\[\]]+", name.lower())
        return {p for p in parts if len(p) >= 3 and p not in STOP and not p.isdigit()}

    node_tokens = {pid: tokens(n["name"]) for pid, n in nodes.items()}

    token_index: dict = {}
    for pid, toks in node_tokens.items():
        for tok in toks:
            token_index.setdefault(tok, []).append(pid)

    pair_counts: defaultdict = defaultdict(int)
    for pids in token_index.values():
        if len(pids) < 2: continue
        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                pair_counts[tuple(sorted([pids[i], pids[j]]))] += 1

    for (a, b), count in pair_counts.items():
        if count >= 2:
            add_edge(a, b, "similar")

    # ── Pass 4: Tag linking ────────────────────────────────────────────────────
    # Parse YAML frontmatter tags and link files that share a tag
    _fm_re = re.compile(r'^---\s*\n(.*?)\n---', re.DOTALL)
    _tag_re = re.compile(r'tags:\s*\[([^\]]+)\]|tags:\s*\n((?:[ \t]*-[^\n]+\n)+)', re.IGNORECASE)

    def extract_tags(content: str) -> list:
        fm = _fm_re.match(content)
        if not fm: return []
        block = fm.group(1)
        m = _tag_re.search(block)
        if not m: return []
        if m.group(1):  # inline: tags: [a, b, c]
            return [t.strip().strip('"\'') for t in m.group(1).split(',')]
        else:           # block: tags:\n  - a\n  - b
            return [line.strip().lstrip('- ').strip() for line in m.group(2).strip().splitlines()]

    tag_index: dict = {}  # tag -> [pids]
    for pid, content in md_contents.items():
        for tag in extract_tags(content):
            if tag:
                tag_index.setdefault(tag.lower(), []).append(pid)

    for tag, pids in tag_index.items():
        if len(pids) < 2: continue
        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                add_edge(pids[i], pids[j], "tag")

    # ── Pass 5: Entity linking ─────────────────────────────────────────────────
    # Files that mention the same named entity (person/product/company) are linked.
    # Entity list drawn from ProductBrain context — extend as needed.
    # Add your own people, products, and topics here.
    # Files that mention the same entity will be linked in the graph.
    # Keep entries lowercase. Multi-word entries use spaces.
    ENTITIES = [
        # People — e.g. "alice smith", "bob jones"
        # Products / companies — e.g. "acme corp", "my product"
        # Topics — e.g. "sustainability", "machine learning"
    ]
    # Build entity→word pattern once
    entity_patterns = [(e, e.replace(" ", r"[\s_\-]+")) for e in ENTITIES]

    def file_entities(text: str) -> set:
        found = set()
        tl = text.lower()
        for entity, pat in entity_patterns:
            if entity in tl:  # fast pre-check before regex
                found.add(entity)
        return found

    # Build entity→[pids] index from all available text (md + cached)
    entity_index: dict = {}
    for pid, content in md_contents.items():
        for ent in file_entities(content):
            entity_index.setdefault(ent, set()).add(pid)
    with _cache_lock:
        snap = dict(_text_cache)
    for pid, entry in snap.items():
        if pid not in nodes or not entry[1]: continue
        for ent in file_entities(entry[1]):
            entity_index.setdefault(ent, set()).add(pid)

    # Only link via entities that appear in 2–8 files — broader = not discriminating
    MAX_ENTITY_FILES = 8
    entity_count: defaultdict = defaultdict(int)
    for ent, pids in entity_index.items():
        pid_list = list(pids)
        if len(pid_list) < 2 or len(pid_list) > MAX_ENTITY_FILES: continue
        for i in range(len(pid_list)):
            if entity_count[pid_list[i]] >= 4: continue
            for j in range(i + 1, len(pid_list)):
                if entity_count[pid_list[j]] >= 4: continue
                if add_edge(pid_list[i], pid_list[j], "entity"):
                    entity_count[pid_list[i]] += 1
                    entity_count[pid_list[j]] += 1

    # ── Pass 6: Series detection ───────────────────────────────────────────────
    # Files with the same alphabetic prefix + sequential numbers form a series.
    # e.g. "Activity 4.1", "Activity 4.2" → linked in sequence
    _num_re = re.compile(r'^(.*?)(\d+(?:[.\-]\d+)*)(.*)$')

    def series_key(name: str):
        m = _num_re.match(name.strip())
        if not m: return None, None
        prefix = m.group(1).strip().lower()
        num_str = m.group(2)
        if not prefix or len(prefix) < 2: return None, None
        try:
            parts = [int(x) for x in re.split(r'[.\-]', num_str)]
        except ValueError:
            return None, None
        return prefix, parts

    series_index: dict = {}  # prefix -> [(num_parts, pid)]
    for pid, node in nodes.items():
        prefix, parts = series_key(node["name"])
        if prefix:
            series_index.setdefault(prefix, []).append((parts, pid))

    for prefix, entries in series_index.items():
        if len(entries) < 2: continue
        entries.sort(key=lambda x: x[0])
        for i in range(len(entries) - 1):
            add_edge(entries[i][1], entries[i + 1][1], "series")

    # ── Pass 7: Temporal co-location ──────────────────────────────────────────
    # Files modified within the same 7-day window get a weak temporal link.
    # Capped at 5 links per file to avoid dense temporal clusters.
    _date_re = re.compile(r'(\d{4}[-_]\d{2}[-_]\d{2})')

    # Only use explicit dates in filenames — mtime catches everything and is too noisy
    dated = []
    for pid, n in nodes.items():
        m = _date_re.search(n["name"])
        if m:
            try:
                from datetime import datetime
                ts = datetime.strptime(m.group(1).replace('_', '-'), '%Y-%m-%d').timestamp()
                dated.append((ts, pid))
            except ValueError:
                pass
    dated.sort()

    TWO_DAYS = 2 * 24 * 3600
    temporal_count: dict = defaultdict(int)
    for i, (ts_a, pid_a) in enumerate(dated):
        for j in range(i + 1, len(dated)):
            ts_b, pid_b = dated[j]
            if ts_b - ts_a > TWO_DAYS: break
            if temporal_count[pid_a] >= 3 or temporal_count[pid_b] >= 3: continue
            if add_edge(pid_a, pid_b, "temporal"):
                temporal_count[pid_a] += 1
                temporal_count[pid_b] += 1

    # ── Pass 8: TF-IDF content similarity ────────────────────────────────────
    # Link files whose content is genuinely similar, not just same-named tokens.
    # Only run over MD files + cached text. Top-N similar pairs per file linked.
    import math
    all_texts: dict = {}  # pid -> word_set (already computed)
    for pid, content in md_contents.items():
        ws = extract_words(content)
        if ws: all_texts[pid] = ws
    with _cache_lock:
        snap2 = dict(_text_cache)
    for pid, entry in snap2.items():
        if pid not in nodes or not entry[1]: continue
        ws = entry[2] if len(entry) > 2 else extract_words(entry[1])
        if ws: all_texts[pid] = ws

    # IDF: how rare is each word across all docs
    doc_count = len(all_texts)
    if doc_count >= 4:
        df: dict = defaultdict(int)
        for ws in all_texts.values():
            for w in ws:
                df[w] += 1
        # Build TF-IDF vectors (sparse: only top-K words by IDF weight per doc)
        TOP_K = 30
        idf = {w: math.log(doc_count / (1 + c)) for w, c in df.items() if c < doc_count * 0.6}

        def tfidf_top(ws: set) -> set:
            scored = [(idf.get(w, 0), w) for w in ws if w in idf]
            scored.sort(reverse=True)
            return {w for _, w in scored[:TOP_K]}

        tfidf_vecs = {pid: tfidf_top(ws) for pid, ws in all_texts.items()}

        # Jaccard similarity on TF-IDF top-K vectors
        pid_list2 = list(tfidf_vecs.keys())
        SIM_THRESHOLD = 0.25   # at least 25% Jaccard overlap on top-K TF-IDF words
        MAX_LINKS = 2           # max tfidf links per file
        tfidf_count: dict = defaultdict(int)

        for i, pid_a in enumerate(pid_list2):
            va = tfidf_vecs[pid_a]
            if not va: continue
            scores = []
            for j in range(i + 1, len(pid_list2)):
                pid_b = pid_list2[j]
                vb = tfidf_vecs[pid_b]
                if not vb: continue
                inter = len(va & vb)
                if inter == 0: continue
                jac = inter / len(va | vb)
                if jac >= SIM_THRESHOLD:
                    scores.append((jac, pid_b))
            scores.sort(reverse=True)
            for _, pid_b in scores[:MAX_LINKS]:
                if tfidf_count[pid_a] < MAX_LINKS and tfidf_count[pid_b] < MAX_LINKS:
                    if add_edge(pid_a, pid_b, "tfidf"):
                        tfidf_count[pid_a] += 1
                        tfidf_count[pid_b] += 1

    return list(nodes.values()), edges

# ── File watcher ──────────────────────────────────────────────────────────────

class State:
    nodes, edges = [], []
    mtimes = {}
    sse_clients = []
    lock = threading.Lock()

def snapshot_mtimes():
    result = {}
    for base in SCAN_DIRS:
        if not base.exists(): continue
        for path in _iter_files(base):
            try: result[str(path)] = path.stat().st_mtime
            except: pass
    return result

def push_graph(nodes, edges):
    """Push updated graph to all connected SSE clients."""
    payload = "data:" + json.dumps({"nodes": nodes, "links": edges}) + "\n\n"
    with State.lock:
        dead = []
        for client in State.sse_clients:
            try:
                client.wfile.write(payload.encode())
                client.wfile.flush()
            except Exception:
                dead.append(client)
        for d in dead:
            State.sse_clients.remove(d)


def rescan_and_push():
    nodes, edges = scan()
    with State.lock:
        State.nodes, State.edges = nodes, edges
    push_graph(nodes, edges)


def warm_cache():
    """Extract text from all non-md files in parallel, then re-scan with full data."""
    with State.lock:
        all_nodes = list(State.nodes)

    non_md = [n for n in all_nodes if n["ext"] in ("docx", "pdf", "txt")]
    if not non_md:
        return

    def extract_one(node):
        try:
            extract_text(Path(node["path"]))
        except Exception:
            pass

    # Use threads to parallelise extraction (I/O bound)
    threads = [threading.Thread(target=extract_one, args=(n,), daemon=True) for n in non_md]
    for t in threads: t.start()
    for t in threads: t.join()

    # Now rescan — scan() will pick up cached text in Pass 2b
    rescan_and_push()
    print(f"Cache warm complete — {len(non_md)} files extracted")


def watcher():
    State.mtimes = snapshot_mtimes()
    while True:
        time.sleep(POLL_SECS)
        current = snapshot_mtimes()
        if current != State.mtimes:
            prev = State.mtimes
            State.mtimes = current
            # Invalidate cache for changed or new files
            changed = {p for p, m in current.items() if prev.get(p) != m}
            for p in changed:
                with _cache_lock:
                    _text_cache.pop(p, None)
            rescan_and_push()

# ── HTTP Handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        p = urllib.parse.urlparse(self.path)
        if p.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with State.lock:
                State.sse_clients.append(self)
            try:
                while True:
                    time.sleep(30)
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except:
                with State.lock:
                    if self in State.sse_clients:
                        State.sse_clients.remove(self)

        elif p.path == "/file":
            params = urllib.parse.parse_qs(p.query)
            path = params.get("path", [""])[0]
            try:
                content = Path(path).read_text(errors="ignore")
                self._respond(200, "text/plain", content.encode())
            except:
                self.send_error(404)

        elif p.path == "/open":
            params = urllib.parse.parse_qs(p.query)
            path = params.get("path", [""])[0]
            try:
                subprocess.run(["open", path], check=False)
                self._respond(200, "application/json", b'{"ok":true}')
            except Exception:
                self.send_error(500)

        elif p.path == "/api/extract":
            params = urllib.parse.parse_qs(p.query)
            path = params.get("path", [""])[0]
            text = extract_text(Path(path)) if path else ""
            self._respond(200, "application/json", json.dumps({"text": text}).encode())

        elif p.path == "/api/nodes":
            # Lightweight node index — name, path, folder, ext, size. No file content.
            with State.lock:
                nodes = State.nodes
            self._respond(200, "application/json", json.dumps(nodes).encode())

        elif p.path == "/api/search":
            params = urllib.parse.parse_qs(p.query)
            q = params.get("q", [""])[0].lower().strip()
            if not q:
                self._respond(400, "application/json", b'{"error":"missing q"}')
                return
            results = []
            with State.lock:
                nodes = list(State.nodes)
            for node in nodes:
                content = extract_text(Path(node["path"]))
                if not content:
                    continue
                cl = content.lower()
                if q in cl:
                    idx = cl.find(q)
                    start = max(0, idx - 80)
                    end   = min(len(content), idx + 160)
                    excerpt = content[start:end].replace("\n", " ").strip()
                    results.append({
                        "name":    node["name"],
                        "path":    node["path"],
                        "folder":  node["folder"],
                        "ext":     node["ext"],
                        "excerpt": excerpt,
                    })
            self._respond(200, "application/json", json.dumps(results).encode())

        elif p.path == "/":
            html = build_html(State.nodes, State.edges)
            self._respond(200, "text/html", html.encode())

        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        p = urllib.parse.urlparse(self.path)

        if p.path == "/save":
            data = json.loads(body)
            path = Path(data["path"])
            # safety: only allow writing inside SCAN_DIRS
            allowed = any(str(path).startswith(str(d)) for d in SCAN_DIRS)
            if not allowed:
                self.send_error(403); return
            path.write_text(data["content"], encoding="utf-8")
            self._respond(200, "application/json", b'{"ok":true}')

        elif p.path == "/new":
            data = json.loads(body)
            name = re.sub(r'[^\w\s\-]', '', data.get("name", "Untitled")).strip() or "Untitled"
            path = WRITE_DIR / f"{name}.md"
            if path.exists():
                self._respond(409, "application/json", b'{"error":"exists"}'); return
            path.write_text(f"# {name}\n\n", encoding="utf-8")
            self._respond(200, "application/json", json.dumps({"path": str(path)}).encode())

        elif p.path == "/delete":
            data = json.loads(body)
            path = Path(data["path"])
            allowed = any(str(path).startswith(str(d)) for d in SCAN_DIRS)
            if not allowed:
                self.send_error(403); return
            path.unlink(missing_ok=True)
            self._respond(200, "application/json", b'{"ok":true}')

        else:
            self.send_error(404)

    def _respond(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

# ── HTML ──────────────────────────────────────────────────────────────────────

def build_html(nodes, edges):
    return HTML.replace("__GRAPH_DATA__", json.dumps({"nodes": nodes, "links": edges}))

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Brain Graph</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0d0d0f; color: #e0e0e0; display: flex; height: 100vh; overflow: hidden; }

#graph-pane { flex: 1; position: relative; min-width: 0; touch-action: none; }
svg { width: 100%; height: 100%; display: block; touch-action: none; user-select: none; -webkit-user-select: none; }

#sidebar {
  width: 400px; min-width: 300px;
  background: #141416;
  border-left: 1px solid #2a2a2e;
  display: flex; flex-direction: column; overflow: hidden;
}

#sidebar-header {
  padding: 14px 16px;
  border-bottom: 1px solid #2a2a2e;
  display: flex; flex-direction: column; gap: 10px;
}
.header-row { display: flex; align-items: center; justify-content: space-between; }
#sidebar-header h2 { font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 0.8px; }

#search {
  width: 100%; background: #1e1e22; border: 1px solid #333; border-radius: 6px;
  padding: 7px 12px; color: #e0e0e0; font-size: 13px; outline: none;
}
#search:focus { border-color: #6c63ff; }

#file-info {
  padding: 12px 16px; font-size: 12px; border-bottom: 1px solid #2a2a2e; min-height: 50px;
}
#file-info .file-name { font-size: 14px; font-weight: 600; color: #e0e0e0; margin-bottom: 3px; }
#file-info .file-meta { color: #555; font-size: 11px; }
#file-actions { display: flex; gap: 6px; margin-top: 8px; }

#content-area {
  flex: 1; overflow-y: auto; padding: 16px;
  font-size: 13px; line-height: 1.75; color: #ccc;
}
#editor {
  display: none; flex: 1;
  flex-direction: column;
}
#editor-textarea {
  flex: 1; resize: none; background: #0f0f12; border: none; outline: none;
  color: #d4d4d4; font-family: "SF Mono", "Fira Code", monospace; font-size: 12px;
  line-height: 1.6; padding: 16px; width: 100%;
}
#editor-bar {
  padding: 8px 16px; background: #1a1a1e; border-top: 1px solid #2a2a2e;
  display: flex; gap: 8px; align-items: center;
}
.save-status { font-size: 11px; color: #555; margin-left: auto; }

/* Markdown rendering */
#content-area h1, #content-area h2, #content-area h3, #content-area h4 { color: #e8e8e8; margin: 1em 0 0.4em; font-weight: 600; }
#content-area h1 { font-size: 17px; }
#content-area h2 { font-size: 14px; border-bottom: 1px solid #2a2a2e; padding-bottom: 4px; }
#content-area h3 { font-size: 13px; color: #aaa; }
#content-area h4 { font-size: 12px; color: #888; }
#content-area p { margin: 0.5em 0; }
#content-area ul, #content-area ol { padding-left: 20px; margin: 0.4em 0; }
#content-area li { margin: 0.2em 0; }
#content-area code { background: #1e1e22; border: 1px solid #333; border-radius: 3px; padding: 1px 5px; font-family: "SF Mono", monospace; font-size: 11px; color: #a8dadc; }
#content-area pre { background: #1a1a1e; border: 1px solid #2a2a2e; border-radius: 6px; padding: 12px; overflow-x: auto; margin: 0.8em 0; }
#content-area pre code { background: none; border: none; padding: 0; }
#content-area blockquote { border-left: 3px solid #6c63ff; padding-left: 12px; color: #888; margin: 0.6em 0; }
#content-area table { border-collapse: collapse; width: 100%; margin: 0.8em 0; font-size: 12px; }
#content-area th, #content-area td { border: 1px solid #2a2a2e; padding: 6px 10px; text-align: left; }
#content-area th { background: #1e1e22; color: #aaa; }
#content-area a { color: #6c63ff; text-decoration: none; }
#content-area a.wikilink { color: #8b85ff; border-bottom: 1px dashed #6c63ff55; padding-bottom: 1px; cursor: pointer; }
#content-area a.wikilink:hover { background: #6c63ff20; }
#content-area a.mdlink { color: #6c63ff; cursor: pointer; }
#content-area a.mdlink:hover { text-decoration: underline; }
#content-area strong { color: #e0e0e0; }
#content-area hr { border: none; border-top: 1px solid #2a2a2e; margin: 1em 0; }

.placeholder { color: #3a3a3e; text-align: center; padding: 48px 20px; font-size: 13px; line-height: 2; }

#legend {
  padding: 8px 16px; display: flex; gap: 14px; flex-wrap: wrap;
  border-top: 1px solid #2a2a2e; background: #0f0f12;
}
.leg-item { display: flex; align-items: center; gap: 5px; font-size: 11px; color: #666; }
.leg-item svg { flex-shrink: 0; }
#stats-bar {
  padding: 7px 16px; font-size: 11px; color: #444;
  border-top: 1px solid #2a2a2e; display: flex; justify-content: space-between; align-items: center;
}
.dot { width: 6px; height: 6px; border-radius: 50%; background: #2a2a2e; display: inline-block; margin-right: 6px; vertical-align: middle; }
.dot.live { background: #43c6ac; box-shadow: 0 0 4px #43c6ac; }

/* Buttons */
btn, button {
  padding: 6px 14px; border: none; border-radius: 5px; font-size: 12px;
  cursor: pointer; font-weight: 500; font-family: inherit;
}
.btn-primary   { background: #6c63ff; color: white; }
.btn-primary:hover { background: #7c73ff; }
.btn-ghost     { background: #1e1e22; color: #aaa; border: 1px solid #333; }
.btn-ghost:hover { background: #2a2a2e; color: #e0e0e0; }
.btn-danger    { background: transparent; color: #ff6584; border: 1px solid #ff658440; font-size: 11px; padding: 4px 10px; }
.btn-danger:hover { background: #ff658415; }
.btn-save      { background: #43c6ac; color: #0d0d0f; }
.btn-save:hover { background: #53d6bc; }
.btn-new       { background: transparent; color: #6c63ff; border: 1px solid #6c63ff40; padding: 5px 12px; font-size: 12px; }
.btn-new:hover { background: #6c63ff15; }

/* Graph */
.node circle {
  cursor: pointer;
  transition: r 0.12s ease, fill-opacity 0.12s ease, filter 0.12s ease;
}
.node text {
  font-size: 11px; fill: #aaa; pointer-events: none;
  paint-order: stroke; stroke: #0d0d0f; stroke-width: 3px; stroke-linejoin: round;
  opacity: 0; transition: opacity 0.15s;
}
.node.show-label text { opacity: 1; }
.node.selected text { fill: #fff; font-weight: 600; }
.node.hub text { fill: #ccc; }
.node.hovered circle {
  filter: drop-shadow(0 0 10px #6c63ffaa) drop-shadow(0 0 20px #6c63ff44);
  fill-opacity: 1 !important;
}
.node.hovered text { fill: #fff !important; opacity: 1 !important; }
.node.neighbour circle {
  filter: drop-shadow(0 0 5px #43c6ac66);
  fill-opacity: 0.95 !important;
}
.node.neighbour text { opacity: 1 !important; fill: #ddd !important; }
.link            { stroke: #6a5fad; stroke-opacity: 0.55; stroke-width: 1.2px; transition: stroke-opacity 0.12s, stroke-width 0.12s; }
.link.kind-wiki     { stroke: #7c70c0; stroke-opacity: 0.7;  stroke-width: 1.4px; }
.link.kind-mention  { stroke: #43c6ac; stroke-opacity: 0.45; stroke-width: 1px;   stroke-dasharray: 5,3; }
.link.kind-similar  { stroke: #888;    stroke-opacity: 0.2;  stroke-width: 0.8px; stroke-dasharray: 2,5; }
.link.kind-tag      { stroke: #f8b400; stroke-opacity: 0.55; stroke-width: 1.2px; stroke-dasharray: 6,2; }
.link.kind-entity   { stroke: #ff6584; stroke-opacity: 0.4;  stroke-width: 1px;   stroke-dasharray: 4,3; }
.link.kind-series   { stroke: #00bcd4; stroke-opacity: 0.6;  stroke-width: 1.4px; }
.link.kind-temporal { stroke: #aaa;    stroke-opacity: 0.18; stroke-width: 0.7px; stroke-dasharray: 1,5; }
.link.kind-tfidf    { stroke: #e040fb; stroke-opacity: 0.35; stroke-width: 1px;   stroke-dasharray: 3,4; }
.link.highlighted {
  stroke: #b8b0ff !important;
  stroke-opacity: 1 !important;
  stroke-width: 2.5px !important;
  stroke-dasharray: none !important;
  filter: drop-shadow(0 0 4px #6c63ffaa);
}
.link.neighbour-link {
  stroke-opacity: 0.9 !important;
  stroke-width: 2px !important;
  stroke-dasharray: none !important;
}
.node.highlighted circle { filter: drop-shadow(0 0 10px #6c63ffcc); }
.node.dimmed circle { opacity: 0.2; }
.node.dimmed text { opacity: 0; }

/* Link type toggles */
.toggle-link { cursor: pointer; opacity: 0.35; transition: opacity 0.15s; user-select: none; }
.toggle-link.active { opacity: 1; }

/* Tooltip */
#graph-tooltip {
  position: fixed;
  background: #1a1a20;
  border: 1px solid #3a3a4a;
  border-radius: 8px;
  padding: 9px 13px;
  pointer-events: none;
  font-size: 12px;
  color: #e0e0e0;
  box-shadow: 0 4px 20px rgba(0,0,0,0.5);
  display: none;
  max-width: 220px;
  z-index: 50;
  transition: opacity 0.1s;
}
#graph-tooltip .tip-name { font-weight: 600; font-size: 13px; margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#graph-tooltip .tip-meta { color: #666; font-size: 11px; line-height: 1.6; }
#graph-tooltip .tip-connections { color: #6c63ff; font-size: 11px; margin-top: 4px; }

/* New note modal */
#modal-bg {
  display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6);
  z-index: 100; align-items: center; justify-content: center;
}
#modal-bg.open { display: flex; }
#modal {
  background: #1a1a1e; border: 1px solid #2a2a2e; border-radius: 10px;
  padding: 24px; width: 360px; box-shadow: 0 16px 48px rgba(0,0,0,0.6);
}
#modal h3 { font-size: 14px; margin-bottom: 16px; color: #e0e0e0; }
#modal input {
  width: 100%; background: #0f0f12; border: 1px solid #333; border-radius: 6px;
  padding: 9px 12px; color: #e0e0e0; font-size: 13px; outline: none; margin-bottom: 14px;
}
#modal input:focus { border-color: #6c63ff; }
#modal-actions { display: flex; gap: 8px; justify-content: flex-end; }
</style>
</head>
<body>

<div id="graph-pane">
  <svg id="svg">
    <rect width="100%" height="100%" fill="#0d0d0f"/>
    <g id="zoom-group">
      <g id="links-g"></g>
      <g id="nodes-g"></g>
    </g>
  </svg>
</div>

<div id="sidebar">
  <div id="sidebar-header">
    <div class="header-row">
      <h2>Brain Graph</h2>
      <button class="btn-new" onclick="openNewModal()">+ New note</button>
    </div>
    <input id="search" type="text" placeholder="Search files..." oninput="onSearch(this.value)">
  </div>

  <div id="file-info">
    <div class="placeholder">Click a node to open a file</div>
  </div>

  <div id="content-area">
    <div class="placeholder">Nothing selected yet.<br>The graph will update live<br>as you add or edit files.</div>
  </div>

  <div id="editor">
    <textarea id="editor-textarea" spellcheck="true" oninput="markDirty()"></textarea>
    <div id="editor-bar">
      <button class="btn-save" onclick="saveFile()">Save</button>
      <button class="btn-ghost" onclick="exitEditor()">Preview</button>
      <span class="save-status" id="save-status"></span>
    </div>
  </div>

  <div id="legend">
    <span class="leg-item toggle-link active" data-kind="wiki"     onclick="toggleLinkKind('wiki',this)"><svg width="16" height="10"><line x1="0" y1="5" x2="16" y2="5" stroke="#7c70c0" stroke-width="1.4"/></svg> Wiki</span>
    <span class="leg-item toggle-link active" data-kind="mention"  onclick="toggleLinkKind('mention',this)"><svg width="16" height="10"><line x1="0" y1="5" x2="16" y2="5" stroke="#43c6ac" stroke-width="1" stroke-dasharray="5,3"/></svg> Mention</span>
    <span class="leg-item toggle-link active" data-kind="tag"      onclick="toggleLinkKind('tag',this)"><svg width="16" height="10"><line x1="0" y1="5" x2="16" y2="5" stroke="#f8b400" stroke-width="1.2" stroke-dasharray="6,2"/></svg> Tag</span>
    <span class="leg-item toggle-link active" data-kind="entity"   onclick="toggleLinkKind('entity',this)"><svg width="16" height="10"><line x1="0" y1="5" x2="16" y2="5" stroke="#ff6584" stroke-width="1" stroke-dasharray="4,3"/></svg> Entity</span>
    <span class="leg-item toggle-link active" data-kind="series"   onclick="toggleLinkKind('series',this)"><svg width="16" height="10"><line x1="0" y1="5" x2="16" y2="5" stroke="#00bcd4" stroke-width="1.4"/></svg> Series</span>
    <span class="leg-item toggle-link active" data-kind="tfidf"    onclick="toggleLinkKind('tfidf',this)"><svg width="16" height="10"><line x1="0" y1="5" x2="16" y2="5" stroke="#e040fb" stroke-width="1" stroke-dasharray="3,4"/></svg> Topic</span>
    <span class="leg-item toggle-link" data-kind="temporal" onclick="toggleLinkKind('temporal',this)"><svg width="16" height="10"><line x1="0" y1="5" x2="16" y2="5" stroke="#aaa" stroke-width="0.7" stroke-dasharray="1,5"/></svg> Time</span>
    <span class="leg-item toggle-link" data-kind="similar"  onclick="toggleLinkKind('similar',this)"><svg width="16" height="10"><line x1="0" y1="5" x2="16" y2="5" stroke="#888" stroke-width="1" stroke-dasharray="2,4"/></svg> Similar</span>
  </div>
  <div id="stats-bar">
    <span><span class="dot" id="live-dot"></span><span id="stat-nodes">—</span></span>
    <span id="stat-links">—</span>
  </div>
</div>

<!-- New note modal -->
<div id="modal-bg">
  <div id="modal">
    <h3>New note</h3>
    <input id="modal-name" type="text" placeholder="Note name..." onkeydown="if(event.key==='Enter')createNote()">
    <div id="modal-actions">
      <button class="btn-ghost" onclick="closeModal()">Cancel</button>
      <button class="btn-primary" onclick="createNote()">Create</button>
    </div>
  </div>
</div>

<!-- Discard changes modal -->
<div id="discard-bg" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:200;align-items:center;justify-content:center;">
  <div style="background:#1a1a1e;border:1px solid #2a2a2e;border-radius:10px;padding:24px;width:320px;box-shadow:0 16px 48px rgba(0,0,0,0.6);">
    <h3 style="font-size:14px;margin-bottom:10px;color:#e0e0e0;">Unsaved changes</h3>
    <p style="font-size:12px;color:#888;margin-bottom:18px;">Discard changes to this note?</p>
    <div style="display:flex;gap:8px;justify-content:flex-end;">
      <button class="btn-ghost" id="discard-cancel">Keep editing</button>
      <button class="btn-danger" id="discard-ok">Discard</button>
    </div>
  </div>
</div>

<div id="graph-tooltip">
  <div class="tip-name" id="tip-name"></div>
  <div class="tip-meta" id="tip-meta"></div>
  <div class="tip-connections" id="tip-connections"></div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<script>
// ── State ──────────────────────────────────────────────────────────────────
let GRAPH = __GRAPH_DATA__;
let selectedNode = null;
let dirty = false;
let currentPath = null;
const _hiddenKinds = new Set(["similar", "temporal"]); // off by default

const PALETTE = ["#6c63ff","#ff6584","#43c6ac","#f8b400","#e040fb","#00bcd4","#ff7043","#66bb6a","#ec407a","#26c6da"];
const FOLDER_COLORS = {};
let ci = 0;
function folderColor(f) {
  if (!FOLDER_COLORS[f]) FOLDER_COLORS[f] = PALETTE[ci++ % PALETTE.length];
  return FOLDER_COLORS[f];
}

// ── Graph setup ────────────────────────────────────────────────────────────
const svg  = d3.select("#svg");
const gWrap = d3.select("#zoom-group");
const W = () => document.getElementById("graph-pane").clientWidth;
const H = () => document.getElementById("graph-pane").clientHeight;

let currentZoom = 1;
const LABEL_PX = 12;          // constant on-screen label size in CSS pixels
const zoom = d3.zoom().scaleExtent([0.05, 10])
  .filter(e => {
    if (e.type === 'wheel') { e.preventDefault(); e.stopPropagation(); }
    return !e.button; // allow ctrlKey+wheel (trackpad pinch) and regular scroll
  })
  .on("zoom", e => {
    gWrap.attr("transform", e.transform);
    currentZoom = e.transform.k;
    if (nodeSel) nodeSel.select("text").attr("font-size", (LABEL_PX / currentZoom) + "px");
    updateLabels();
  });
svg.call(zoom);

// Stop wheel events bubbling up to VS Code's webview container
document.addEventListener('wheel', e => e.stopPropagation(), { passive: false });

let sim, linkSel, nodeSel;
let degreeMap = {};
let hoveredId = null;

function buildGraph(data) {
  GRAPH = data;

  // Compute degree (link count) per node
  degreeMap = {};
  GRAPH.links.forEach(l => {
    const s = l.source?.id ?? l.source, t = l.target?.id ?? l.target;
    degreeMap[s] = (degreeMap[s] || 0) + 1;
    degreeMap[t] = (degreeMap[t] || 0) + 1;
  });

  d3.select("#links-g").selectAll("*").remove();
  d3.select("#nodes-g").selectAll("*").remove();
  if (sim) sim.stop();

  sim = d3.forceSimulation(GRAPH.nodes)
    .alphaDecay(0.04)
    .velocityDecay(0.4)
    .force("link", d3.forceLink(GRAPH.links).id(d => d.id)
      .distance(l => l.kind === "similar" ? 220 : l.kind === "mention" ? 160 : 130)
      .strength(l => l.kind === "similar" ? 0.05 : l.kind === "mention" ? 0.12 : 0.3))
    .force("charge",    d3.forceManyBody().strength(d => -450 - (degreeMap[d.id] || 0) * 25).distanceMax(700).theta(0.9))
    .force("center",    d3.forceCenter(W() / 2, H() / 2).strength(0.03))
    .force("x",         d3.forceX(W() / 2).strength(0.015))
    .force("y",         d3.forceY(H() / 2).strength(0.015))
    .force("collision", d3.forceCollide(d => nodeR(d) + 22).iterations(1));

  linkSel = d3.select("#links-g").selectAll("line")
    .data(GRAPH.links).join("line")
    .attr("class", l => "link kind-" + (l.kind || "link"));

  nodeSel = d3.select("#nodes-g").selectAll("g")
    .data(GRAPH.nodes, d => d.id).join("g")
    .attr("class", d => "node" + ((degreeMap[d.id] || 0) >= 5 ? " hub" : ""))
    .call(d3.drag()
      .on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag",  (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on("end",   (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }))
    .on("click",      (e, d) => { e.stopPropagation(); selectNode(d); })
    .on("dblclick",   (e, d) => { e.stopPropagation(); zoomToNode(d); })
    .on("mouseenter", (e, d) => { hoveredId = d.id; onHover(e, d); })
    .on("mousemove",  (e, d) => { moveTooltip(e); })
    .on("mouseleave", (e, d) => { hoveredId = null; offHover(d); });

  nodeSel.append("circle")
    .attr("r", d => nodeR(d, degreeMap[d.id] || 0))
    .attr("fill", d => d.ext === "md" ? folderColor(d.folder) : "#0d0d0f")
    .attr("fill-opacity", d => d.ext === "md" ? 0.8 : 1)
    .attr("stroke", d => folderColor(d.folder))
    .attr("stroke-width", d => d.ext === "md" ? 1.5 : 2)
    .attr("stroke-opacity", d => d.ext === "md" ? 0.35 : 0.9);

  nodeSel.append("text")
    .attr("dx", d => nodeR(d, degreeMap[d.id] || 0) + 5)
    .attr("dy", "0.35em")
    .attr("font-size", (LABEL_PX / currentZoom) + "px")
    .text(d => d.name);

  updateLabels();

  applyLinkVisibility();

  let _lastRender = 0;
  sim.on("tick", () => {
    const now = performance.now();
    if (now - _lastRender < 32) return; // ~30fps cap during simulation
    _lastRender = now;
    linkSel.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
           .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    nodeSel.attr("transform", d => `translate(${d.x},${d.y})`);
  });
  sim.on("end", () => { // final position flush when simulation cools
    linkSel.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
           .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    nodeSel.attr("transform", d => `translate(${d.x},${d.y})`);
  });

  updateStats();

  // Re-select previously selected node if still exists
  if (selectedNode) {
    const still = GRAPH.nodes.find(n => n.id === selectedNode.id);
    if (still) highlight(still);
  }
}

function nodeR(d, deg = 0) {
  // Size by degree (link count) so hubs stand out
  return Math.max(5, Math.min(20, 5 + deg * 0.6 + d.size / 6000));
}

function updateLabels() {
  if (!nodeSel) return;

  // Always apply correct screen-size font
  nodeSel.select("text").attr("font-size", (LABEL_PX / currentZoom) + "px");

  // Build neighbour set of anything focused (hovered or selected)
  const focusIds = new Set();
  const focusNode = hoveredId || selectedNode?.id;
  if (focusNode) {
    focusIds.add(focusNode);
    GRAPH.links.forEach(l => {
      const s = l.source?.id ?? l.source, t = l.target?.id ?? l.target;
      if (s === focusNode) focusIds.add(t);
      if (t === focusNode) focusIds.add(s);
    });
  }

  // Tier 1 (< 0.4): no labels
  // Tier 2 (0.4–1.4): hubs only (8+ connections)
  // Tier 3 (1.4–2.5): hubs (3+) + neighbours of focused
  // Tier 4 (> 2.5): all labels
  // Always: hovered/selected node + direct neighbours
  nodeSel.classed("show-label", d => {
    if (focusIds.has(d.id)) return true;
    const deg = degreeMap[d.id] || 0;
    if (currentZoom >= 2.5) return true;
    if (currentZoom >= 1.4 && deg >= 3) return true;
    if (currentZoom >= 0.4 && deg >= 8) return true;
    return false;
  });
}

// ── Hover interaction ─────────────────────────────────────────────────────
const tooltip = document.getElementById("graph-tooltip");

function onHover(e, d) {
  if (!nodeSel) return;

  // Get neighbour ids
  const neighbours = new Set();
  const neighbourLinks = new Set();
  GRAPH.links.forEach((l, i) => {
    const s = l.source?.id ?? l.source, t = l.target?.id ?? l.target;
    if (s === d.id) { neighbours.add(t); neighbourLinks.add(i); }
    if (t === d.id) { neighbours.add(s); neighbourLinks.add(i); }
  });

  // Grow hovered node
  nodeSel.select("circle")
    .filter(n => n.id === d.id)
    .transition().duration(100)
    .attr("r", nodeR(d, degreeMap[d.id] || 0) * 1.5);

  // Apply classes
  nodeSel.classed("hovered",   n => n.id === d.id);
  nodeSel.classed("neighbour", n => neighbours.has(n.id));
  linkSel.classed("neighbour-link", (l, i) => neighbourLinks.has(i));

  updateLabels();

  // Show tooltip
  const deg = degreeMap[d.id] || 0;
  const ext = {md:"Markdown", docx:"Word doc", pdf:"PDF", txt:"Text"}[d.ext] || d.ext.toUpperCase();
  document.getElementById("tip-name").textContent = d.name;
  document.getElementById("tip-meta").innerHTML = `${d.folder}<br>${ext} &bull; ${(d.size/1024).toFixed(1)} KB`;
  document.getElementById("tip-connections").textContent = deg > 0 ? `${deg} connection${deg !== 1 ? "s" : ""}` : "No connections";
  tooltip.style.display = "block";
  moveTooltip(e);
}

function offHover(d) {
  if (!nodeSel) return;

  // Shrink node back
  nodeSel.select("circle")
    .filter(n => n.id === d.id)
    .transition().duration(150)
    .attr("r", nodeR(d, degreeMap[d.id] || 0));

  nodeSel.classed("hovered neighbour", false);
  linkSel.classed("neighbour-link", false);
  updateLabels();
  tooltip.style.display = "none";
}

function moveTooltip(e) {
  const pad = 14;
  const tw = tooltip.offsetWidth, th = tooltip.offsetHeight;
  let x = e.clientX + pad, y = e.clientY + pad;
  if (x + tw > window.innerWidth  - 10) x = e.clientX - tw - pad;
  if (y + th > window.innerHeight - 10) y = e.clientY - th - pad;
  tooltip.style.left = x + "px";
  tooltip.style.top  = y + "px";
}

buildGraph(GRAPH);

// Fit on first idle
sim.on("end.fit", () => {
  try {
    const b = d3.select("#nodes-g").node().getBBox();
    if (!b.width) return;
    const s = Math.min(W() / (b.width + 100), H() / (b.height + 100), 1);
    const tx = W() / 2 - s * (b.x + b.width / 2);
    const ty = H() / 2 - s * (b.y + b.height / 2);
    svg.call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(s));
  } catch(e) {}
  sim.on("end.fit", null);
});

svg.on("click", () => { clearHighlight(); });

function zoomToNode(d) {
  const w = W(), h = H();
  const scale = 1.8;
  const tx = w / 2 - scale * d.x;
  const ty = h / 2 - scale * d.y;
  svg.transition().duration(500)
    .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
}

svg.on("dblclick.zoom", null); // disable default double-click zoom on background

// ── Selection & highlight ─────────────────────────────────────────────────
let _pendingNode = null;

function confirmDiscard(onOk) {
  const bg = document.getElementById("discard-bg");
  bg.style.display = "flex";
  document.getElementById("discard-ok").onclick = () => { bg.style.display = "none"; onOk(); };
  document.getElementById("discard-cancel").onclick = () => { bg.style.display = "none"; };
}

function selectNode(d) {
  if (dirty && currentPath) {
    confirmDiscard(() => {
      dirty = false;
      _doSelectNode(d);
    });
    return;
  }
  _doSelectNode(d);
}

function _doSelectNode(d) {
  selectedNode = d;
  currentPath  = d.path;
  highlight(d);
  showFileInfo(d);
  exitEditor();
  if (d.ext === "md") {
    loadFile(d.path);
  } else {
    showNonMdPreview(d);
  }
}

function showNonMdPreview(d) {
  document.getElementById("content-area").style.display = "";
  document.getElementById("editor").style.display = "none";
  const icon = {docx: "📄", pdf: "📕", txt: "📝"}[d.ext] || "📁";
  const area = document.getElementById("content-area");
  area.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;">
      <span style="font-size:28px;">${icon}</span>
      <button class="btn-primary" onclick="openInApp()" style="margin-left:auto">Open in app</button>
    </div>
    <div id="doc-preview" style="color:#888;font-size:12px;font-style:italic;">Loading preview…</div>`;

  fetch("/api/extract?path=" + encodeURIComponent(d.path))
    .then(r => r.json())
    .then(data => {
      const preview = document.getElementById("doc-preview");
      if (!preview) return;
      if (data.text) {
        preview.style.fontStyle = "normal";
        preview.style.color = "#ccc";
        preview.style.lineHeight = "1.7";
        preview.style.whiteSpace = "pre-wrap";
        preview.textContent = data.text.slice(0, 3000) + (data.text.length > 3000 ? "\n\n…" : "");
      } else {
        preview.textContent = "No text could be extracted from this file.";
      }
    })
    .catch(() => {
      const preview = document.getElementById("doc-preview");
      if (preview) preview.textContent = "Could not load preview.";
    });
}

function openInApp() {
  if (currentPath) fetch("/open?path=" + encodeURIComponent(currentPath));
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
}

function highlight(d) {
  const connected = new Set([d.id]);
  GRAPH.links.forEach(l => {
    const s = l.source?.id ?? l.source, t = l.target?.id ?? l.target;
    if (s === d.id) connected.add(t);
    if (t === d.id) connected.add(s);
  });
  if (nodeSel) {
    nodeSel.classed("highlighted", n => n.id === d.id);
    nodeSel.classed("selected",    n => n.id === d.id);
    nodeSel.classed("dimmed",      n => !connected.has(n.id));
  }
  if (linkSel) {
    linkSel.classed("highlighted", l => {
      const s = l.source?.id ?? l.source, t = l.target?.id ?? l.target;
      return s === d.id || t === d.id;
    });
  }
  updateLabels();
}

function clearHighlight() {
  if (nodeSel) nodeSel.classed("highlighted dimmed selected", false);
  if (linkSel) linkSel.classed("highlighted", false);
  updateLabels();
}

function applyLinkVisibility() {
  if (linkSel) linkSel.style("display", l => _hiddenKinds.has(l.kind) ? "none" : null);
}

function toggleLinkKind(kind, el) {
  el.classList.toggle("active");
  if (_hiddenKinds.has(kind)) _hiddenKinds.delete(kind);
  else _hiddenKinds.add(kind);
  applyLinkVisibility();
}

function showFileInfo(d) {
  const kb = (d.size / 1024).toFixed(1);
  const editBtn = d.ext === "md" ? '<button class="btn-ghost" onclick="enterEditor()">Edit</button>' : '';
  document.getElementById("file-info").innerHTML =
    `<div class="file-name">${escapeHtml(d.name)}</div>
     <div class="file-meta">${escapeHtml(d.folder)} &bull; ${d.ext.toUpperCase()} &bull; ${kb} KB</div>
     <div id="file-actions">
       ${editBtn}
       <button class="btn-danger" onclick="deleteFile()">Delete</button>
     </div>`;
}

// ── File ops ──────────────────────────────────────────────────────────────
function loadFile(path) {
  fetch("/file?path=" + encodeURIComponent(path))
    .then(r => r.ok ? r.text() : Promise.reject(r.status))
    .then(md => {
      document.getElementById("editor-textarea").value = md;
      showPreview(md);
    })
    .catch(err => {
      document.getElementById("content-area").innerHTML =
        `<p style="color:#888;font-style:italic;">Could not load file (${err})</p>`;
    });
}

function showPreview(md) {
  document.getElementById("content-area").style.display = "";
  document.getElementById("editor").style.display = "none";
  document.getElementById("content-area").innerHTML = renderMd(md);
}

function enterEditor() {
  document.getElementById("content-area").style.display = "none";
  document.getElementById("editor").style.display = "flex";
  document.getElementById("editor-textarea").focus();
}

function exitEditor() {
  const md = document.getElementById("editor-textarea").value;
  showPreview(md);
  document.getElementById("save-status").textContent = "";
}

function markDirty() {
  dirty = true;
  document.getElementById("save-status").textContent = "Unsaved";
}

function saveFile() {
  const content = document.getElementById("editor-textarea").value;
  fetch("/save", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ path: currentPath, content })
  }).then(r => r.json()).then(() => {
    dirty = false;
    document.getElementById("save-status").textContent = "Saved ✓";
    setTimeout(() => document.getElementById("save-status").textContent = "", 2000);
  });
}

function deleteFile() {
  if (!currentPath) return;
  const name = selectedNode?.name || "this file";
  if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;
  fetch("/delete", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ path: currentPath })
  }).then(() => {
    selectedNode = null; currentPath = null; dirty = false;
    document.getElementById("file-info").innerHTML = '<div class="placeholder">File deleted</div>';
    document.getElementById("content-area").innerHTML = '<div class="placeholder">File deleted</div>';
    showPreview("");
  });
}

// ── New note ──────────────────────────────────────────────────────────────
function openNewModal() {
  document.getElementById("modal-name").value = "";
  document.getElementById("modal-bg").classList.add("open");
  setTimeout(() => document.getElementById("modal-name").focus(), 50);
}
function closeModal() { document.getElementById("modal-bg").classList.remove("open"); }

function createNote() {
  const name = document.getElementById("modal-name").value.trim();
  if (!name) return;
  fetch("/new", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ name })
  }).then(r => r.json()).then(data => {
    closeModal();
    if (data.error) { alert("A file with that name already exists."); return; }
    // Select the new node once the watcher picks it up (~2s)
    setTimeout(() => {
      const n = GRAPH.nodes.find(nd => nd.path === data.path);
      if (n) { selectNode(n); enterEditor(); }
    }, 2500);
  });
}

document.getElementById("modal-bg").addEventListener("click", e => {
  if (e.target === document.getElementById("modal-bg")) closeModal();
});

// ── Search ────────────────────────────────────────────────────────────────
function onSearch(q) {
  if (!nodeSel) return;
  if (!q) { nodeSel.classed("dimmed highlighted", false); if (linkSel) linkSel.classed("highlighted", false); return; }
  const lq = q.toLowerCase();
  nodeSel.classed("dimmed",      d => !d.name.toLowerCase().includes(lq));
  nodeSel.classed("highlighted", d =>  d.name.toLowerCase().includes(lq));
  if (linkSel) linkSel.classed("highlighted", false);
}

// ── Stats ─────────────────────────────────────────────────────────────────
function updateStats() {
  document.getElementById("stat-nodes").textContent = GRAPH.nodes.length + " files";
  document.getElementById("stat-links").textContent = GRAPH.links.length + " links";
}

// ── SSE live updates ──────────────────────────────────────────────────────
function connectSSE() {
  const es = new EventSource("/events");
  es.onmessage = e => {
    const data = JSON.parse(e.data);
    buildGraph(data);
  };
  es.onerror = () => {
    document.getElementById("live-dot").classList.remove("live");
    setTimeout(connectSSE, 3000);
  };
  es.onopen = () => document.getElementById("live-dot").classList.add("live");
}
connectSSE();

// ── Markdown renderer ─────────────────────────────────────────────────────
function renderMd(text) {
  if (!text) return '<div class="placeholder">Empty file</div>';
  let h = text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/```[\w]*\n([\s\S]*?)```/g, (_, c) => `<pre><code>${c}</code></pre>`)
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/^#### (.+)$/gm, "<h4>$1</h4>")
    .replace(/^### (.+)$/gm,  "<h3>$1</h3>")
    .replace(/^## (.+)$/gm,   "<h2>$1</h2>")
    .replace(/^# (.+)$/gm,    "<h1>$1</h1>")
    .replace(/^---+$/gm, "<hr>")
    .replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
    .replace(/\*\*(.+?)\*\*/g,     "<strong>$1</strong>")
    .replace(/\*([^*\n]+)\*/g,     "<em>$1</em>")
    .replace(/^&gt; (.+)$/gm, "<blockquote>$1</blockquote>")
    .replace(/^\- (.+)$/gm,   "<li>$1</li>")
    .replace(/^\* (.+)$/gm,   "<li>$1</li>")
    .replace(/^\d+\. (.+)$/gm,"<li>$1</li>")
    .replace(/(<li>[\s\S]+?<\/li>)/g, m => "<ul>" + m + "</ul>")
    // Wikilinks first  ([[Note]] or [[Note|Alias]])
    .replace(/\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]/g, (_, target, alias) => {
      const label = alias || target;
      return `<a href="#" class="wikilink" data-target="${escapeAttr(target.trim())}">${escapeAttr(label.trim())}</a>`;
    })
    // Markdown links: external opens new tab, internal stays internal
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => {
      if (/^(https?:|mailto:)/.test(url)) return `<a href="${url}" target="_blank">${label}</a>`;
      return `<a href="#" class="mdlink" data-target="${escapeAttr(url)}">${label}</a>`;
    })
    .replace(/\n\n+/g, "</p><p>")
    .replace(/\n/g, "<br>");
  return "<p>" + h + "</p>";
}

function escapeAttr(s) {
  return String(s).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// Delegate clicks on rendered links
document.getElementById("content-area").addEventListener("click", e => {
  const wl = e.target.closest(".wikilink");
  if (wl) {
    e.preventDefault();
    const name = wl.dataset.target.toLowerCase();
    const target = GRAPH.nodes.find(n => n.name.toLowerCase() === name);
    if (target) selectNode(target);
    else flashMessage(`No file named "${wl.dataset.target}"`);
    return;
  }
  const ml = e.target.closest(".mdlink");
  if (ml) {
    e.preventDefault();
    const rel = ml.dataset.target.split("#")[0].split("?")[0];
    // Resolve relative to currentPath
    const base = currentPath.substring(0, currentPath.lastIndexOf("/"));
    const resolved = resolvePath(base, rel);
    const target = GRAPH.nodes.find(n => n.path === resolved);
    if (target) selectNode(target);
    else flashMessage(`No file at "${rel}"`);
  }
});

function resolvePath(base, rel) {
  if (rel.startsWith("/")) return rel;
  const parts = (base + "/" + rel).split("/");
  const out = [];
  for (const p of parts) {
    if (p === "" || p === ".") continue;
    if (p === "..") out.pop();
    else out.push(p);
  }
  return "/" + out.join("/");
}

function flashMessage(msg) {
  const s = document.getElementById("save-status");
  if (s) {
    s.textContent = msg;
    setTimeout(() => s.textContent = "", 2500);
  }
}
</script>
</body>
</html>"""

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Scanning files...")
    State.nodes, State.edges = scan()
    print(f"  {len(State.nodes)} files  |  {len(State.edges)} links (fast pass)")
    threading.Thread(target=watcher, daemon=True).start()
    threading.Thread(target=warm_cache, daemon=True).start()
    print(f"Open: http://localhost:{PORT}  (full text extraction running in background…)")
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
