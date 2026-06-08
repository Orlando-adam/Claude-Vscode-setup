# Brain Graph

A locally-hosted, Obsidian-style knowledge graph that visualises your notes, documents, and files as an interactive D3 force graph — with a VS Code extension that opens it as a native panel.

![Brain Graph screenshot](docs/screenshot.png)

## Features

- **Interactive D3 graph** — force-directed layout, pinch-to-zoom, drag to pan
- **All file types** — reads `.md`, `.docx`, `.pdf`, `.txt`
- **Three link types** — wiki links (`[[...]]`), name mentions, shared title tokens
- **Live reload** — graph updates automatically when files change on disk
- **VS Code extension** — opens as a panel; click any node → open file in editor
- **Inline editor** — edit markdown notes without leaving the graph
- **Full-text search** — search across all file types via the sidebar
- **API endpoints** — token-efficient context loading for AI tools

## Requirements

- Python 3.9+
- `pdftotext` for PDF text extraction (optional): `brew install poppler`

## Quick start

```bash
git clone https://github.com/Orlando-adam/brain-graph
cd brain-graph
python3 graph_viewer.py
# open http://localhost:4322
```

## Configuration

Copy `config.example.json` to `~/.brain-graph.json` and edit:

```json
{
  "scan_dirs": ["~/Notes", "~/Documents/Work"],
  "write_dir": "~/Notes",
  "port": 4322
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `scan_dirs` | `~/Notes`, `~/Documents`, `~/Obsidian` | Directories to scan |
| `write_dir` | first scan dir | Where new notes are created |
| `port` | `4322` | Server port |
| `poll_secs` | `3` | File watch interval |
| `home_max_depth` | `2` | Depth limit when scanning home directory |
| `exclude` | common build dirs | Directory names to skip |
| `pdftotext` | auto-detected | Path to `pdftotext` binary |

## VS Code extension

Install the extension:

```bash
npm install -g @vscode/vsce
vsce package
code --install-extension brain-graph-0.1.0.vsix
```

Then reload VS Code. Use **⌘⌥G** (Mac) or **Ctrl+Alt+G** to open the graph panel.

To use a custom server script or port, add to VS Code settings:

```json
{
  "brainGraph.serverScript": "/path/to/graph_viewer.py",
  "brainGraph.port": 4322
}
```

## API

The server exposes endpoints for token-efficient use with AI tools:

| Endpoint | Description |
|----------|-------------|
| `GET /api/nodes` | All files as lightweight metadata (no content) |
| `GET /api/search?q=TERM` | Full-text search across all file types |
| `GET /file?path=PATH` | Read a file's content |
| `GET /api/extract?path=PATH` | Extracted plain text from any file |

## License

MIT
