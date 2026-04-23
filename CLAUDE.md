# IIT Hawk Chatbot — Codebase Cleanup

This folder (`Prototype_restructured/`) is a working copy of the original `Prototype/` folder.
The goal is to clean it up in two phases. Do them in order — verify Phase 1 before starting Phase 2.

---

# PHASE 1 — Structural Reorganization

Reorganize files so the folder structure tells the project's story clearly to a stranger.

## Target structure

```
Prototype_restructured/
├── api_app.py                      ← entry point, stays at root
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env
├── README.md
├── data_sources/                   ← NEW empty folder: placeholder for data source links Excel
├── scrapers/                       ← calendar_scraper.py stays here
├── chunking/                       ← move calendar_chunks.py here from scrapers/
├── data/                           ← 4 files only (see renames below)
├── mappings/                       ← unchanged
├── indexing/                       ← was index/
├── search/                         ← 4 search files + reranker.py (moved from utils/)
├── router/
│   ├── router.py
│   ├── calendar_router.py
│   └── prototypes/                 ← was questions/
├── core/
│   └── pipeline.py                 ← was ui/app_with_clarification_memory.py
├── utilities/                      ← merged common/ + config subfolder
│   └── config/                     ← router_config.json + documents_topics.json
├── cli/                            ← unchanged
├── evaluation/                     ← unchanged
└── frontend/                       ← NEW empty folder: placeholder for other group's frontend
```

## Step 1 — Create new directories

```bash
mkdir -p core utilities/config router/prototypes data_sources chunking indexing frontend
touch core/__init__.py utilities/__init__.py router/prototypes/__init__.py
```

## Step 2 — Move and rename files

| From | To |
|---|---|
| `ui/app_with_clarification_memory.py` | `core/pipeline.py` |
| `common/es_client.py` | `utilities/es_client.py` |
| `common/embedding_model.py` | `utilities/embedding_model.py` |
| `common/slot_filling.py` | `utilities/slot_filling.py` |
| `common/clarification_options.py` | `utilities/clarification_options.py` |
| `common/query_augmentation.py` | `utilities/query_augmentation.py` |
| `common/search_utils.py` | `utilities/search_utils.py` |
| `common/tuition_fee_kind.py` | `utilities/tuition_fee_kind.py` |
| `utils/reranker.py` | `search/reranker.py` |
| `config/router_config.json` | `utilities/config/router_config.json` |
| `config/documents_topics.json` | `utilities/config/documents_topics.json` |
| `questions/*.py` (all 5) | `router/prototypes/` |
| `index/*.py` (all 4) | `indexing/` |
| `scrapers/calendar_chunks.py` | `chunking/calendar_chunks.py` |
| `data/Unstructured chunks.json` | `data/unstructured_chunks.json` |
| `data/Contacts data.csv` | `data/contacts_data.csv` |

## Step 3 — Delete unused files and now-empty folders

| What | Reason |
|---|---|
| `ui/design_app.py` | Streamlit comparison app, replaced by real frontend |
| `ui/calendar_app.py` | Dev-only Streamlit demo |
| `ui/contacts_app.py` | Dev-only Streamlit demo |
| `ui/documents_app.py` | Dev-only Streamlit demo |
| `ui/tuition_app.py` | Dev-only Streamlit demo |
| `ui/feedback/` | Runtime log, not code |
| `ui_utils/` | Only supported dropped Streamlit apps |
| `debugging/` | Empty |
| `tests/` | Empty |
| `data/unused_data/` | Explicitly unused intermediate files |
| `nohup.out` | Server log file, not code |
| `ui/` | Empty after moves above |
| `common/` | Empty after moves to utilities/ |
| `utils/` | Empty after reranker move |
| `config/` | Empty after moves to utilities/config/ |
| `questions/` | Empty after moves to router/prototypes/ |
| `index/` | Empty after moves to indexing/ |

## Step 4 — Update imports

### `api_app.py`
```python
# Before → After
from ui.app_with_clarification_memory import (...)  →  from core.pipeline import (...)
from common.clarification_options import options_cache  →  from utilities.clarification_options import options_cache
from common.slot_filling import CONTACT_DEPT_PICKER_OPTIONS  →  from utilities.slot_filling import CONTACT_DEPT_PICKER_OPTIONS
from common.es_client import es  →  from utilities.es_client import es
```

### `core/pipeline.py`
```python
import common.slot_filling as _slot_mod  →  import utilities.slot_filling as _slot_mod
```
(All router and search imports in this file stay unchanged)

### `search/*.py` (all 4 files)
```python
from common.es_client import es  →  from utilities.es_client import es
from common.embedding_model import model_large  →  from utilities.embedding_model import model_large
from common.query_augmentation import expand_query  →  from utilities.query_augmentation import expand_query
from common.search_utils import clean_query, rrf_fuse  →  from utilities.search_utils import clean_query, rrf_fuse
from common.slot_filling import <x>_query_validation  →  from utilities.slot_filling import <x>_query_validation
from common.tuition_fee_kind import ...  →  from utilities.tuition_fee_kind import ...  # tuition_search.py only
from utils.reranker import rerank_chunks  →  from search.reranker import rerank_chunks
```

### `router/router.py`
```python
from questions.calendar_questions import CALENDAR_PROTOTYPES   →  from router.prototypes.calendar_questions import CALENDAR_PROTOTYPES
from questions.contact_questions import CONTACTS_PROTOTYPES    →  from router.prototypes.contact_questions import CONTACTS_PROTOTYPES
from questions.documents_questions import DOCUMENTS_PROTOTYPES →  from router.prototypes.documents_questions import DOCUMENTS_PROTOTYPES
from questions.tuition_questions import TUITION_PROTOTYPES     →  from router.prototypes.tuition_questions import TUITION_PROTOTYPES
from questions.ood_questions import OOD_PROTOTYPES             →  from router.prototypes.ood_questions import OOD_PROTOTYPES
from common.embedding_model import model_large                 →  from utilities.embedding_model import model_large
```

### `router/calendar_router.py`
```python
from common.es_client import es  →  from utilities.es_client import es
from common.clarification_options import options_cache  →  from utilities.clarification_options import options_cache
```

### `indexing/*.py`
- `from mappings import` stays unchanged (mappings is still at root)
- In `indexing/documents_index.py`: `"Unstructured chunks.json"` → `"unstructured_chunks.json"`
- In `indexing/contacts_index.py`: `"Contacts data.csv"` → `"contacts_data.csv"` (if referenced)

### `cli/documents_cli.py`
```python
from common.embedding_model import model_large  →  from utilities.embedding_model import model_large
```

## Step 5 — Verify Phase 1

```bash
source venv/bin/activate
uvicorn api_app:app --host 0.0.0.0 --port 8000

# In another terminal:
curl http://localhost:8000/health
# Expected: {"status":"ok","model":"chatbot_b"}

curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"prompt":"when is spring break"}'
# Expected: a real answer with no ImportError
```

**Do NOT proceed to Phase 2 until both curl commands succeed.**

---

# PHASE 2 — Code-Level Cleanup

Clean inside the files. Do not change behavior, function signatures, or public interfaces.

## Rules
- Remove dead code: commented-out blocks, unused functions, unreachable branches
- Remove unused imports
- Remove debug print statements and excessive logging noise
- Remove multi-line docstrings that describe obvious behavior — one short line max, or none
- Remove inline comments that only say what the code does (trust named identifiers)
- Do NOT add features, refactor logic, or change behavior
- Do NOT change function signatures — `api_app.py` imports specific names from `core/pipeline.py`

## Priority files (most clutter — do these first)

1. **`core/pipeline.py`** — largest file, grown organically over many iterations.
   Likely has: old commented blocks, redundant conditionals, debug prints, leftover Streamlit-era code.

2. **`api_app.py`** — verbose inline comments throughout; the Streamlit shim block at the top is over-explained.

3. **`search/tuition_search.py`** — complex retry logic with heavy inline commentary.

4. **`search/documents_search.py`**, **`search/contacts_search.py`**, **`search/calendar_search.py`**
   — repeated patterns; check for unused imports and redundant comments.

5. **`router/router.py`** — check for dead branches and over-commented routing logic.

6. **`utilities/slot_filling.py`** — validation functions likely have heavy inline explanation.

## What NOT to touch
- `evaluation/` — test scripts, leave as-is
- `mappings/` — schema definitions, leave as-is
- `indexing/` — one-time setup scripts, leave as-is
- `router/prototypes/` — prototype question lists, leave as-is
- `data/` — JSON/CSV data files, not code

## Verify after Phase 2
Run the same curl commands as Phase 1 verification. API must still return real answers.
