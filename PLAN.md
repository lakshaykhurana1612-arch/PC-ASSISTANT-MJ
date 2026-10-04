# MJ Ultimate Architecture — Implementation Plan

## Architecture Philosophy
- **Provider-based:** Every backend (memory, embedding, vector, LLM, STT, TTS) is swappable via abstract providers
- **Unified schema:** Single `MemoryEntry` for all memory types — metadata handles differentiation
- **Interface-first:** All modules expose clean interfaces; implementations can be swapped without core changes
- **No premature infrastructure:** Dashboard, Cloud, Plugin SDK come only after core (Memory + Developer + Vision) is mature

---

## Current Status (Completed)
### Phase 1 — Voice Engine ✅
`app/voice_engine/`: VAD, Recorder, STT, TTS, Conversation, WakeWord, Echo

### Phase 2 — Brain ✅
`app/brain/`: ToolRegistry, CapabilityManager, InputNormalizer, IntentRouter, ContextBuilder, Planner, PromptBuilder, PlanValidator, ResponseBuilder, MiddlewarePipeline
`app/planner/`: PipelineOrchestrator, PlanExecutor
`app/events/`: EventBus, Event types
`app/automation/`: TagExecutor adapter

### Phase 3 — Memory System ✅
`app/memory/` + `app/providers/`: Provider-based unified memory with hybrid search, SQLite + FAISS + SentenceTransformer, MemoryManager API

---

## Implementation Order

## Phase 4 — MJ IDE Brain (Workspace Intelligence Engine) 🔥 CURRENT
**Goal:** Transform MJ from a simple assistant into an IDE-level code understanding and editing engine.

### Architecture
```
DeveloperManager (SINGLE PUBLIC API)
│
├── WorkspaceManager
│   ├── ProjectDetector     — Auto-detect Python/React/Django/Node/Rust/Java/C++/Unity/Flutter
│   ├── LanguageManager     — Language-specific parser selection
│   ├── Indexer             — PythonParser (AST) + JSParser + TSParser + RegexParser + PackageParser
│   ├── KnowledgeGraph      — Nodes (Function, Class, Variable, Constant, Module, Package, Import, Decorator)
│   │                        Edges (CALLS, IMPORTS, EXTENDS, USES, RETURNS, REFERENCES, CREATES, READS, WRITES)
│   ├── SymbolIndex         — Every symbol searchable: Function, Method, Class, Variable, Constant, Enum, Decorator
│   ├── SearchEngine        — Regex + AST + Semantic + Knowledge Graph search
│   ├── Metrics             — Files, Symbols, GraphNodes, Edges, PatchTime, SearchTime, CacheHits
│   └── Cache               — RAM → SQLite → JSON (ties to Phase 3 Memory)
│
├── Diagnostics
│   ├── Syntax              — Parse errors, missing brackets, indentation
│   ├── Import              — Missing modules, unused imports, circular dependencies
│   ├── Type                — Type mismatches, missing type hints
│   ├── Runtime             — Potential runtime errors
│   ├── Architecture        — God classes, hotspots, coupling, cohesion
│   └── Performance         — Complexity hotspots, N+1 patterns
│
├── ComplexityAnalyzer      — Cyclomatic, Nesting, LOC, Halstead, Maintainability, Duplication
├── ArchitectureAnalyzer    — Layers, CircularImports, UnusedModules, Hotspots, GodObjects, Suggestions
├── ReferenceFinder         — Find definitions, calls, imports, usages
├── RenameEngine            — Safe rename (find all references → update → validate)
├── RefactorEngine          — Extract method, inline variable, move symbol
│
├── AIEditor
│   ├── Planner             — Determine relevant files → plan edits
│   ├── PatchGenerator      — Unified Diff ONLY (never rewrite whole files)
│   ├── PatchValidator      — Syntax → Imports → Formatting → StaticAnalysis → Tests → Apply
│   ├── DiffEngine          — Side-by-side, unified, HTML diff
│   ├── PreviewEngine       — Interactive diff preview with approval
│   ├── SafeApply           — Snapshot → Patch → Verify → Commit → RollbackPoint
│   ├── Rollback            — One command: "MJ undo last patch"
│   └── Formatter           — Black, isort, ruff, Prettier, clang-format
│
├── TestRunner              — pytest, unittest, custom, coverage
├── DocumentationGenerator  — README, API, Architecture, Sequence, Dependency, Folder Tree
├── GitManager              — Repository, Commits, Branches, Merge, Conflict, Restore, Diff, Status
│
├── WorkspaceEvents         — Indexed, PatchApplied, TestsPassed, TestsFailed, GitCommit, AnalysisFinished
├── WorkspaceMetrics        — Files, Symbols, GraphNodes, Edges, PatchTime, SearchTime, CacheHits
└── DeveloperMemory         — Phase 3 integration: Workspace, Errors, LastPatch, TODOs, RecentFiles, RecentSymbols
```

### File Structure
```
app/developer/
├── __init__.py                    # Package exports
├── developer_manager.py           # SINGLE PUBLIC API
│
├── workspace_manager.py           # WorkspaceManager orchestrator
├── project_detector.py            # Auto-detect project type
├── language_manager.py            # Language-specific parser routing
│
├── parsers/
│   ├── __init__.py
│   ├── python_parser.py           # AST-based Python parser
│   ├── js_parser.py               # JS parser (regex + future Tree-sitter)
│   ├── ts_parser.py               # TypeScript parser
│   ├── regex_parser.py            # Generic regex fallback
│   └── package_parser.py          # Parse requirements.txt, package.json, pyproject.toml, Cargo.toml, pom.xml
│
├── knowledge/
│   ├── __init__.py
│   ├── knowledge_graph.py         # Graph: Nodes + Edges
│   ├── symbol_graph.py            # Symbol-to-symbol relationships
│   ├── dependency_graph.py        # Multi-language dependency graph
│   └── graph_queries.py           # "Where is login handled?" → flow path
│
├── search/
│   ├── __init__.py
│   ├── code_search.py             # Unified search: regex + AST + semantic + knowledge graph
│   └── symbol_index.py            # All symbols with metadata
│
├── ai_editor/
│   ├── __init__.py
│   ├── planner.py                 # Determine relevant files for edit
│   ├── patch_generator.py         # Unified Diff only
│   ├── patch_validator.py         # Syntax → Imports → Formatting → Analysis → Tests
│   ├── diff_engine.py             # Side-by-side, unified, HTML diff
│   ├── preview_engine.py          # Interactive diff preview
│   ├── safe_apply.py              # Snapshot → Patch → Verify → Commit → Rollback
│   ├── rollback.py                # One-command undo
│   └── formatter.py               # Black, isort, ruff, Prettier, clang-format
│
├── diagnostics/
│   ├── __init__.py
│   ├── syntax_diagnostics.py      # Syntax errors
│   ├── import_diagnostics.py      # Import errors, missing modules, circular deps
│   ├── type_diagnostics.py        # Type mismatches
│   ├── runtime_diagnostics.py     # Potential runtime errors
│   ├── architecture_diagnostics.py # God classes, coupling, cohesion
│   └── performance_diagnostics.py # Complexity hotspots, N+1 patterns
│
├── complexity.py                  # Cyclomatic, Nesting, LOC, Halstead, Maintainability, Duplication
├── architecture.py                # Layers, Reports, Suggestions
├── reference_finder.py            # Find definitions, calls, imports, usages
├── rename_engine.py               # Safe rename
├── refactor_engine.py             # Extract method, inline, move
├── test_runner.py                 # pytest, unittest, coverage
├── documentation.py               # README, API, Architecture, Dependency docs
├── git_manager.py                 # Repository, Commits, Branches, Merge, Conflict
├── workspace_events.py            # Event types for workspace lifecycle
├── workspace_metrics.py           # Track scan times, cache hits, symbol counts
└── workspace_cache.py             # Phase 3 integration: RAM → SQLite → JSON
```

### Implementation Steps

| Step | File | Description |
|------|------|-------------|
| 4.1 | `__init__.py` | Package exports — DeveloperManager as single public API |
| 4.2 | `project_detector.py` | Auto-detect Python/React/Django/Node/Rust/Java/C++/Unity/Flutter |
| 4.3 | `language_manager.py` | Route to correct parser based on file extension |
| 4.4 | `parsers/python_parser.py` | Full AST parser: functions, classes, methods, variables, constants, enums, decorators, imports, docstrings |
| 4.5 | `parsers/js_parser.py` | JS regex parser (future Tree-sitter) |
| 4.6 | `parsers/ts_parser.py` | TypeScript regex parser |
| 4.7 | `parsers/regex_parser.py` | Generic regex-based fallback parser |
| 4.8 | `parsers/package_parser.py` | Parse requirements.txt, package.json, pyproject.toml, Cargo.toml, pom.xml |
| 4.9 | `knowledge/knowledge_graph.py` | Graph: Nodes (Function, Class, Variable, etc.) + Edges (CALLS, IMPORTS, etc.) |
| 4.10 | `knowledge/symbol_graph.py` | Symbol-to-symbol relationship tracking |
| 4.11 | `knowledge/dependency_graph.py` | Multi-language dependency graph with circular detection |
| 4.12 | `knowledge/graph_queries.py` | Flow path queries: "Where is login handled?" |
| 4.13 | `search/symbol_index.py` | Index all symbol types with file+line+references |
| 4.14 | `search/code_search.py` | Unified search: regex + AST + semantic + knowledge graph |
| 4.15 | `workspace_manager.py` | Coordinates indexing, graph building, search, caching |
| 4.16 | `workspace_cache.py` | Phase 3 Memory integration: RAM → SQLite → JSON |
| 4.17 | `reference_finder.py` | Find all references: definitions, calls, imports, usages |
| 4.18 | `rename_engine.py` | Safe rename with reference tracking |
| 4.19 | `refactor_engine.py` | Extract method, inline variable, move symbol |
| 4.20 | `complexity.py` | Cyclomatic, Nesting, LOC, Halstead, Maintainability, Duplication |
| 4.21 | `architecture.py` | Layers, Reports, Suggestions, Hotspots |
| 4.22 | `diagnostics/syntax_diagnostics.py` | Syntax error detection |
| 4.23 | `diagnostics/import_diagnostics.py` | Import errors, missing modules, circular deps |
| 4.24 | `diagnostics/type_diagnostics.py` | Type mismatch detection |
| 4.25 | `diagnostics/runtime_diagnostics.py` | Potential runtime errors |
| 4.26 | `diagnostics/architecture_diagnostics.py` | God classes, coupling, cohesion |
| 4.27 | `diagnostics/performance_diagnostics.py` | Complexity hotspots |
| 4.28 | `ai_editor/planner.py` | Determine relevant files for edit operations |
| 4.29 | `ai_editor/patch_generator.py` | Unified Diff ONLY format |
| 4.30 | `ai_editor/patch_validator.py` | Syntax → Imports → Formatting → Static Analysis → Tests |
| 4.31 | `ai_editor/diff_engine.py` | Side-by-side, unified, HTML diff generation |
| 4.32 | `ai_editor/preview_engine.py` | Interactive diff preview with approval |
| 4.33 | `ai_editor/safe_apply.py` | Snapshot → Patch → Verify → Commit → RollbackPoint |
| 4.34 | `ai_editor/rollback.py` | One-command undo with snapshot restore |
| 4.35 | `ai_editor/formatter.py` | Black, isort, ruff, Prettier, clang-format |
| 4.36 | `test_runner.py` | pytest, unittest, custom, coverage |
| 4.37 | `documentation.py` | README, API, Architecture, Sequence, Dependency docs |
| 4.38 | `git_manager.py` | Repository, Commits, Branches, Merge, Conflict, Restore |
| 4.39 | `workspace_events.py` | Event types for workspace lifecycle |
| 4.40 | `workspace_metrics.py` | Track scan times, cache hits, symbol counts |
| 4.41 | `developer_manager.py` | **SINGLE PUBLIC API** wrapping all modules |
| 4.42 | Integration | Update ToolRegistry, Planner, actions.py, main.py, PLAN.md, TODO.md |

---

### Phase 5 — Vision
**Package:** `app/vision/`

- OCR (PaddleOCR/Tesseract)
- Object Detection (YOLO/Grounding DINO)
- Window Detection (find windows by title/class)
- UI Detection (buttons, text fields, dropdowns)
- Layout Detection (screen regions)
- Screen Understanding (describe screen contents)
- Element Locator (click this button, read that dialog)

---

### Phase 6 — Automation Expansion
**Package:** `app/automation/` (expand)

- Browser (existing)
- Windows (UIAutomation for Windows controls)
- Clipboard (read/write text + images)
- Keyboard (type, hotkeys)
- Mouse (click, drag, scroll)
- Explorer (file operations)
- Email (send/read via IMAP/SMTP)
- Calendar (read/create events)
- GitHub (issues, PRs, repos)
- Terminal (run commands, capture output)
- PowerShell (run scripts)
- Downloads (monitor, organize)

---

### Phase 7 — Model/Provider Managers
**Package:** `app/providers/` (expand)

- **Model Manager:** Routes LLM calls across Groq/Gemini/OpenAI/Claude/Ollama
- **Provider Manager:** Manages STT/TTS/OCR/Embedding/Browser backends
- **Fallback chain:** Automatic failover between providers
- **Load balancing:** Distribute requests across providers
- **Cost tracking:** Track token usage per provider

---

### Phase 8 — Services + Security
**Packages:** `app/services/`, `app/security/`

**Services:**
- Scheduler (cron-like task scheduling)
- Background Tasks (async task queue)
- Notifications (desktop toast, sound)
- Health Monitor (CPU, RAM, disk, network)
- Analytics (usage stats, performance metrics)
- Configuration (dynamic config reload)
- Logging (structured logging with rotation)
- Updater (self-update mechanism)
- Crash Recovery (auto-restart on failure)

**Security:**
- Permission System (fine-grained capability permissions)
- Secret Vault (encrypted storage for API keys/passwords)
- Encryption (AES-256 for sensitive data)
- Authentication (user verification)
- Audit Logs (all destructive actions logged)
- Rate Limiter (prevent abuse)

---

### Phase 9 — Agent System
**Package:** `app/agents/`

- **Agent Router:** Classifies request and routes to appropriate agent
- **Developer Agent:** Code analysis, editing, debugging
- **Browser Agent:** Web automation, scraping, form filling
- **Windows Agent:** OS-level operations
- **Research Agent:** Deep web research with sources
- **Memory Agent:** Memory management and optimization
- **Vision Agent:** Screen understanding and UI interaction
- **Planner Agent:** Complex multi-step task planning
- **Security Agent:** Permission checks, threat detection
- **Automation Agent:** Macros, scheduled tasks, workflows

---

### Phase 10 — Dashboard ⏳ Future
- Web-based UI (FastAPI + React)
- Conversations view
- Memory browser
- Project explorer
- Task queue
- Connected devices
- Settings panel
- Plugin manager

---

### Phase 11 — Cloud Sync ⏳ Future
- Multi-device sync
- Cloud backup
- Remote control API
- Web dashboard
- Device management

---

### Phase 12 — Plugin SDK ⏳ Future
- Tool SDK
- Agent SDK
- Vision SDK
- Voice SDK
- Automation SDK
- Memory SDK

---

### Phase 13 — Final Refactor ⏳ Future
- Reorganize directory structure to match architecture diagram
- Remove compatibility wrappers
- Update all imports
- Final integration testing
- Performance optimization
- Documentation generation

