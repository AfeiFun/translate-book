---
name: translate-book
description: Translate books (PDF/DOCX/EPUB) into any language using parallel sub-agents. Converts input -> Markdown chunks -> translated chunks -> HTML/DOCX/EPUB/PDF.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent, AskUserQuestion
metadata: {"openclaw":{"requires":{"bins":["python3","pandoc","ebook-convert"],"anyBins":["calibre","ebook-convert"]},"homepage":"https://github.com/deusyu/translate-book"}}
---

# Book Translation Skill

You are a book translation assistant. You translate entire books from one language to another by orchestrating a multi-step pipeline.

## Workflow

### 1. Collect Parameters

Determine the following from the user's message:
- **file_path**: Path to the input file (PDF, DOCX, EPUB, or Markdown) — REQUIRED
- **target_lang**: Target language code (default: `zh`) — e.g. zh, en, ja, ko, fr, de, es
- **concurrency**: Number of parallel sub-agents per batch (default: `8`)
- **style**: Translation style preset — `scholarly` (default), `readable`, `literary`, `plain`, `bilingual`. See `scripts/style.py list`; ask the user if the genre suggests something other than the default
- **temp_root**: Optional directory under which `{filename}_temp/` should be created
- **epub_cover**: Optional explicit cover image path (EPUB and PDF output)
- **export_name**: Optional filename stem for user-facing output aliases
- **custom_instructions**: Any additional translation instructions from the user (optional)

If the file path is not provided, ask the user.

### 2. Preprocess — Convert to Markdown Chunks

Run the conversion script to produce chunks:

```bash
python3 {baseDir}/scripts/convert.py "<file_path>" --olang "<target_lang>" [--chunk-size N]
```

If the user provided `temp_root`, add `--temp-root "<temp_root>"`. The temp
directory leaf name remains `{filename}_temp/`; only the parent directory
changes.

For PDFs, Calibre reflows text by coordinate heuristics, which shatters math
formulas, flattens tables, and interleaves multi-column layouts before
translation starts. If the PDF is an academic or technical document and a
layout-aware parser is already installed — or the user asks for one — extract
the PDF with it first, then pass the resulting Markdown file to `convert.py`
instead of the PDF. Markdown input (`.md` / `.markdown`) skips Calibre:

- MinerU >= 4: `mineru-kit parse "<file_path>" -o "<name>.md"`
- Marker: `marker_single "<file_path>" --output_dir "<dir>"`, then use `<dir>/<name>/<name>.md`

Keep the PDF's file name stem for the Markdown file, because the temp
directory is named after it. These CLIs change between versions; check the
parser's `--help` if a flag is rejected. Do not install a parser without the
user's consent, because they download large models. Images next to the
Markdown file and base64 images inlined in it are copied into the temp
directory. `--strip-page-numbers` does not apply to Markdown input.

Page-number lines are detected and dropped for PDF input only; EPUB and DOCX
keep every standalone number (chapter, verse or exercise numbers). If an EPUB
prints its page numbers as text and they show up in the chunks, delete the
temp directory before translating and re-run with `--detect-page-numbers`.

**Chunk size.** `--chunk-size` is a *character* target (default 6000; splits land
on structural boundaries, so real chunks run a little smaller). The trade-off is
wall-clock against per-sub-agent output length:

| Source | Recommended | Why |
| --- | --- | --- |
| English prose → Chinese, footnotes/notes sections | 9000–12000 | one sub-agent still emits only ~2500–3500 Chinese characters; chunks roughly halve |
| Dense academic text, math, tables, inline citations | 6000 | long outputs truncate and terminology drifts |
| 300+ chunk books where turns are the bottleneck | 12000–15000 | fewer waves; verify the first batch for truncation before committing |

Nothing in the pipeline depends on 6000; re-chunking an existing temp directory
is not supported, so pick the size before the first translation. If the user
complains about speed, this is the knob to turn — not concurrency alone.

This creates a `{filename}_temp/` directory containing:
- `input.html` (Calibre input only), `input.md` — intermediate files
- `chunk0001.md`, `chunk0002.md`, ... — source chunks for translation
- `manifest.json` — chunk manifest for tracking and validation
- `source_fingerprint.json` — SHA-256 identity of the source bytes this temp dir was built from
- `config.txt` — pipeline configuration with metadata

If `convert.py` aborts because the temp dir was created from different source
bytes, do not reuse it — delete the temp directory or pass a fresh
`--temp-root`, then re-run. Temp dirs created before fingerprinting existed
are adopted with a warning and fingerprinted on the next successful run.

### 3. Discover Source Chunks

Use Glob to find all source chunks:

```
Glob: {filename}_temp/chunk*.md
```

Exclude `output_chunk*.md` from the source list. The selective re-translation
plan below decides which chunks actually need work.

### 3.5. Build Glossary (term consistency)

A separate sub-agent translates each chunk with a fresh context. Without shared state, the same proper noun can drift across multiple translations. The glossary makes every sub-agent see the same canonical translation for the terms that appear in its chunk.

If `<temp_dir>/glossary.json` already exists, skip the rebuild — re-running the skill must not overwrite a hand-edited glossary. To force a rebuild, delete the file.

Otherwise:

1. **Sample chunks**: read `chunk0001.md`, the last chunk, and 3 evenly-spaced middle chunks. If `chunk_count < 5`, sample all of them.
2. **Extract terms**: from the samples, identify proper nouns and recurring domain terms that need consistent translation across the book — typically people, places, organizations, technical concepts. Translate each into the target language. Skip generic vocabulary that any translator would render the same way.
3. **Write `glossary.json`** in the temp dir, matching this v2 schema:

   ```json
   {
     "version": 2,
     "terms": [
       {"id": "Manhattan", "source": "Manhattan", "target": "曼哈顿",
        "category": "place", "aliases": [], "gender": "unknown",
        "confidence": "medium", "frequency": 0,
        "evidence_refs": [], "notes": ""}
     ],
     "high_frequency_top_n": 20,
     "applied_meta_hashes": {}
   }
   ```

   Existing v1 `glossary.json` files are auto-upgraded to v2 on first load. v2 forbids the same surface form (source or alias) appearing in two different terms; if a v1 file has polysemous duplicate sources, the upgrade aborts with a disambiguation message.

4. **Count frequencies** by running:

   ```bash
   python3 {baseDir}/scripts/glossary.py count-frequencies "<temp_dir>"
   ```

   This scans every `chunk*.md` (excluding `output_chunk*.md`), updates each term's `frequency` field, and writes back atomically.

The glossary is hand-editable. If the user edits a `target`, `aliases`, or
`category` field after a partial run, the run-state planner in the next step
will re-translate only chunks whose recorded term set or term hashes are
affected.

### 3.7. Plan Selective Re-translation

Run:

```bash
python3 {baseDir}/scripts/run_state.py plan "<temp_dir>"
```

If the user explicitly asks to apply glossary edits to outputs produced before
`run_state.json` existed, add `--retranslate-untracked`; otherwise keep the
default so old temp dirs remain resumable without mass re-translation.

Capture stdout JSON:
- `translation_chunk_ids` — chunks to translate in this run.
- `record_only_chunk_ids` — existing valid outputs that need `run_state.json`
  records but do not need translation.
- `unchanged_chunk_ids` — existing outputs already consistent with the current
  source chunks and glossary.

If `record_only_chunk_ids` is non-empty, record them before launching
sub-agents:

```bash
python3 {baseDir}/scripts/run_state.py record "<temp_dir>" chunk0001 chunk0002 ...
```

Use `translation_chunk_ids` as the work queue for Step 4. If it is empty, skip
to Step 5.

### 4. Parallel Translation with Sub-Agents

**Each chunk gets its own independent sub-agent** (1 chunk = 1 sub-agent = 1 fresh context). This prevents context accumulation and output truncation.

Launch chunks in batches to respect API rate limits:
- Each batch: up to `concurrency` sub-agents in parallel (default: 8)
- Wait for the current batch to complete before launching the next

**Spawn each sub-agent with the following task.** Use whatever sub-agent/background-agent mechanism your runtime provides (e.g. the Agent tool, sessions_spawn, or equivalent).

The output file is `output_` prefixed to the source filename: `chunk0001.md` → `output_chunk0001.md`.

Do not assemble the prompt by hand for every chunk — render it once per chunk with
the builder. It fills the canonical template (`scripts/prompt_template.md`) with
the style block, the per-chunk term table, the neighbour excerpts and the meta
schema, so 300 sub-agents receive byte-identical rules:

```bash
python3 {baseDir}/scripts/build_prompt.py "<temp_dir>" --all \
  --style readable --lang 简体中文 --custom "<book-specific notes or a .md path>"
# or one chunk:
python3 {baseDir}/scripts/build_prompt.py "<temp_dir>" "chunk0042" --style scholarly
```

It writes `prompts/<chunk>.md` (or `-o <path>`) and prints the path. Then spawn
each sub-agent with:

> 读取 `prompts/chunk<NNNN>.md` 并严格执行其中描述的任务。

The prompt already includes: the 11 base rules, the style block, any custom
instructions, the term table, the read-only neighbour excerpts, and the meta
schema. Keep your own spawn message to one line — anything you add on top will
differ from chunk to chunk.

**Styles.** `--style` picks a rule set from `scripts/styles/`; run
`python3 {baseDir}/scripts/style.py list` for the current set (default
`scholarly`; also `readable`, `literary`, `plain`, `bilingual`). Styles are
executable rules ("拆长句、去欧化、'被'字句只在必要处保留"), not adjectives, and
every chunk in a run must use the same one. Confirm the choice with the user
before Step 4, and record it in `config.txt` if it is not the default:

```bash
printf 'style=%s\n' readable >> "<temp_dir>/config.txt"
```

**Term table and neighbour context** are produced by the builder via
`glossary.py print-terms-for-chunk` and `chunk_context.py`. If you need them
alone: the first emits a 3-column markdown table (`原文 | 别名 | 译文`) of every
term that appears in this chunk (by source OR alias) or is in the top-N
book-wide terms; the second emits the last ~300 characters of the previous chunk
and the first ~300 of the next. Both are omitted from the prompt when empty. The
neighbour block is read-only context for pronouns, gender and aliases — the
sub-agent must never translate it into the output.

**Each sub-agent's task**:
1. Read the source chunk file (e.g. `chunk0001.md`)
2. Translate the content following the translation rules below
3. Write the translated content to `output_chunk0001.md`
4. Write observations to `output_chunk0001.meta.json` matching the schema below. **Non-blocking** — leave fields empty if unsure; do not invent entities. Always emit the file (even if all arrays are empty), because its presence + content hash is how the main agent tracks whether feedback was already merged.

**Sub-agent meta schema** (`output_chunk<NNNN>.meta.json`):

```json
{
  "schema_version": 1,
  "new_entities": [
    {"source": "Taig", "target_proposal": "泰格", "category": "person",
     "evidence": "<≤200-char quote from the chunk>"}
  ],
  "alias_hypotheses": [
    {"variant": "Taig", "may_be_alias_of_source": "Tai",
     "evidence": "<≤200-char quote>"}
  ],
  "attribute_hypotheses": [
    {"entity_source": "Tai", "attribute": "gender", "value": "male",
     "confidence": "high", "evidence": "<≤200-char quote>"}
  ],
  "used_term_sources": ["Tai", "Manhattan"],
  "conflicts": [
    {"entity_source": "Tai", "field": "target", "injected": "泰",
     "observed_better": "太一", "evidence": "<≤200-char quote>"}
  ]
}
```

**Do NOT include a `chunk_id` field** — chunk identity is derived from the filename. Putting it in the payload creates a hallucination hole and validation will reject the file.

The meta file is read by the main agent later and merged into `glossary.json` (see `merge_meta.py`). Sub-agents should fill the schema honestly: cite real quotes from the chunk, never invent entities to "look productive". An empty meta is a perfectly valid output.

**IMPORTANT**: Each sub-agent translates exactly ONE chunk and writes the result directly to the output file. No START/END markers needed.

### 4.5. Merge Sub-Agent Meta Into Glossary (after each batch)

Each sub-agent emitted an `output_chunk<NNNN>.meta.json` alongside its translated chunk. After every batch completes, first record the completed chunk outputs in `run_state.json` while the glossary is still the one used for that batch, then merge observations into the canonical glossary so subsequent batches see an enriched glossary.

1. Record successfully translated chunks from this batch before mutating the glossary:

   ```bash
   python3 {baseDir}/scripts/run_state.py record "<temp_dir>" chunk0001 chunk0002 ...
   ```

   If this fails, fix the missing/empty output or state error before continuing.

2. Run prepare-merge:

   ```bash
   python3 {baseDir}/scripts/merge_meta.py prepare-merge "<temp_dir>"
   ```

   Capture stdout JSON. It contains four arrays:
   - `auto_apply` — new entities with no glossary collision and unanimous (target, category) across all proposing chunks.
   - `decisions_needed` — items requiring main-agent judgment. Each has `id`, `kind`, an `options` array, and the data needed to pick. Kinds:
     - `alias` — `{variant, candidate_source, evidence}`. Choices: `yes_alias` / `no_separate_entity` / `skip`.
     - `conflict` — `{entity_source, field, current, proposed, evidence}`. Choices: `keep_current` / `accept_proposed` / `record_in_notes`.
     - `new_entity_existing_alias` — sub-agents propose `proposed_source` as a new entity, but it's already someone's alias. `{proposed_source, currently_alias_of, promoted_variants: [{target_proposal, category, evidence, evidence_chunks}, ...]}`. Choices: one `use_variant_N` per distinct (target, category) promotion variant (promote `proposed_source` to standalone with that target+category, removing it from the host's aliases) / `keep_as_alias` / `skip`.
     - `existing_entity_conflict` — sub-agents proposed a (target, category) for `entity_source` that differs from the canonical. Multiple distinct differing proposals all get exposed. `{entity_source, current_target, current_category, proposed_variants: [{target_proposal, category, evidence, evidence_chunks}, ...]}`. Choices: `keep_current` / one `use_variant_N` per competing proposal (overwrites both target AND category, stamps the prior values into notes) / `record_in_notes` (canonical unchanged; every proposed variant gets logged to notes).
     - `alias_or_new_entity` — `variant` has multiple competing options that can't all coexist under v2's surface-form uniqueness rule. Triggered when (a) `variant` was proposed both as a new standalone entity AND as an alias of one or more candidates, OR (b) `variant` was proposed as an alias of two or more different candidates with no standalone competitor. `{variant, alias_candidates: [{candidate_source, evidence, evidence_chunks}, ...], standalone_variants: [{target_proposal, category, evidence, evidence_chunks}, ...]}`. Choices: one `use_alias_N` per candidate (attach as alias of that candidate), one `use_standalone_N` per competing standalone proposal (add as standalone with that target+category), or `skip`.
     - `conflicting_new_entity_proposals` — `{source, variants: [{target_proposal, category, evidence, evidence_chunks}, ...]}`. Choices: `use_variant_0`, `use_variant_1`, ..., `skip`.
   - `consumed_chunk_ids` — every meta file scanned this round (regardless of whether it produced a finding). These hashes get recorded in `applied_meta_hashes` on apply.
   - `malformed_meta_chunk_ids` — meta files that failed validation. Quarantined: not consumed, not crashing the run. Surface them in your batch progress.

3. **If `consumed_chunk_ids` is empty** → nothing was scanned; skip to Step 5.

4. **If `consumed_chunk_ids` is non-empty but both `auto_apply` and `decisions_needed` are empty** → still pipe `{"auto_apply": [], "decisions": [], "consumed_chunk_ids": [...]}` into `apply-merge` so the hashes get recorded. **Skipping this is the bug** — no-op metas would re-scan forever otherwise.

5. **Otherwise, resolve each decision**:
   - Read its evidence quotes inline.
   - Pick one option from its `options` array.
   - Build a `decisions` entry that round-trips the original decision plus your choice. The entry MUST include the original `kind` and (for `conflicting_new_entity_proposals`) the `variants` array, so apply-merge can validate and act:

     ```json
     {"id": "d1", "kind": "alias", "variant": "Taig", "candidate_source": "Tai", "choice": "yes_alias"}
     ```

6. Pipe the decisions JSON into apply-merge:

   ```bash
   echo '{"auto_apply": [...], "decisions": [...], "consumed_chunk_ids": [...]}' \
     | python3 {baseDir}/scripts/merge_meta.py apply-merge "<temp_dir>"
   ```

   Surface the summary JSON (`auto_applied`, `decisions_resolved`, `consumed_chunks`, `errors`) in your batch progress message.

   **apply-merge is transactional.** If any decision is malformed (wrong choice for kind, missing fields, references a non-existent entity), the entire batch aborts with a non-zero exit and stderr details — no glossary mutation, no hashes recorded. On non-zero exit, fix the offending decision and re-pipe; `prepare-merge` will surface the same proposals because nothing was consumed.

   **Decision order in the input list is not significant.** `apply-merge` internally dispatches entity-creating decisions before alias-attaching ones, so `yes_alias` decisions whose candidate is created by another decision in the same batch (a `use_standalone_N`, `use_variant_N`, or `promote_to_separate_entity`) succeed regardless of the order you pass them in. Alias chains (e.g. `Taighi → Taig` where `Taig → Tai` is also a pending alias decision) resolve via a fixed-point loop within the alias-attacher pass — you don't need to topo-sort or sequence chained aliases manually.

On a fresh run after a previous interrupted batch, `prepare-merge` will pick up any meta files left behind. Don't manually delete them.

### 5. Verify Completeness and Retry

After all batches complete, use Glob to check that every source chunk has a corresponding output file.

If any are missing, retry them — each missing chunk as its own sub-agent. Maximum 2 attempts per chunk (initial + 1 retry).

Also read `manifest.json` and verify:
- Every chunk id has a corresponding output file
- No output file is empty (0 bytes) or blank (whitespace-only)

Run the mechanical QA sweep (empty/English-only outputs, OCR leftovers such as a
stray `~`, replacement characters, unbalanced code fences, invented headings):

```bash
python3 {baseDir}/scripts/qa_chunks.py "<temp_dir>"
```

It exits non-zero and lists the offending chunks. Treat it as a checklist, not a
court: a Latin-heavy chunk in a book of quotations can be legitimate, but "no CJK
at all" or "missing output" always means the sub-agent failed.

Then run the meta-merge observability snapshot:

```bash
python3 {baseDir}/scripts/merge_meta.py status "<temp_dir>"
```

Also run the selective re-translation state snapshot:

```bash
python3 {baseDir}/scripts/run_state.py status "<temp_dir>"
```

Surface a one-line summary in the verification report:

> Translated chunks: 50 • Meta files: 48 found / 47 consumed • Malformed: 1 (chunk0099 — see stderr) • Chunks missing meta: chunk0017, chunk0042

Severity rules (none of these fail the run — meta is non-blocking):

- `unmerged_meta_files > 0` after Step 4.5 ran → bug, flag prominently. Resume should have caught this.
- `malformed_meta_files > 0` → sub-agent emitted invalid meta; print chunk_ids and a "fix the file by hand and re-run if you want this chunk's feedback merged" note.
- `meta_files_found < translated_chunks` → sub-agent-compliance issue (some chunks didn't emit meta at all). Print missing chunk_ids.

Report any chunks that failed translation after retry.

### 6. Translate Book Title

Read `config.txt` from the temp directory to get the `original_title` field.
If it is missing (e.g. Markdown input with neither front matter nor a leading
`#` title), use the source file name instead.

Translate the title to the target language. For Chinese, wrap in 书名号: `《translated_title》`.

### 7. Post-process — Merge and Build

Run the build script with the translated title:

```bash
python3 {baseDir}/scripts/merge_and_build.py --temp-dir "<temp_dir>" --title "<translated_title>"
```

Add `--toc` when the book should carry a table-of-contents page before the first
chapter (readers expect one in EPUB/DOCX/PDF; `book.html` already gets a
floating sidebar TOC):

```bash
python3 {baseDir}/scripts/merge_and_build.py --temp-dir "<temp_dir>" --title "<translated_title>" \
  --cover "<cover.jpg>" --toc
```

`--toc` lists the top two heading levels by default. Carve it with
`--toc-levels 1`, `--toc-start "<heading text>"` (where to stop skipping the
front matter) and `--toc-title "<text>"` (defaults to 目录/目次/목차/Contents by
language). For PDF it builds twice: once with placeholder numbers to freeze the
pagination, then again with the page number of every entry read back from the
first pass, so the printed folios are correct by construction. Without PyMuPDF
(`import fitz`) it degrades to a TOC without page numbers; `--no-toc-pages` forces
that. EPUB and DOCX always get the link-only variant, because their pagination
differs from the PDF's.

The heading ids are rewritten to ASCII (`sec001…`) as part of this step. That is
required: Calibre's EPUB splitter cannot resolve non-ASCII fragment links and
silently points every TOC entry at the first split file.

If the user provided `epub_cover`, add `--cover "<epub_cover>"`. If the user
provided `export_name`, add `--export-name "<export_name>"`.

Keep the intermediate files. The chunks, `manifest.json`, and `run_state.json`
are what make spot fixes and selective re-translation possible after the build
(see Step 9). Add `--cleanup` only when the user explicitly asks to delete
intermediates, and tell them first that it permanently deletes `chunk*.md`,
`output_chunk*.md`, `input.html`, and `input.md`: after that, fixing a single
chunk means converting and translating the whole book again.

The script reads `output_lang` from `config.txt` automatically. Optional overrides: `--lang`, `--author`.

This produces in the temp directory:
- `output.md` — merged translated markdown
- `book.html` — web version with floating TOC
- `book_doc.html` — ebook version
- `book.docx`, `book.epub`, `book.pdf` — format conversions (requires Calibre)

### 8. Report Results

Tell the user:
- Where the output files are located
- How many chunks were translated
- The translated title
- List generated output files with sizes
- Any format generation failures
- That the intermediate files are kept so passages can still be fixed
  (Step 9), and that they can ask for cleanup once they are done with the book

Do not run `--cleanup` as part of this report. Offer it only after the user
says they expect no more edits, and before running it, say what it deletes
(see Step 7). Re-running the Step 7 build command with the same flags plus
`--cleanup` keeps the existing outputs and then deletes the intermediates; if
any format fails, the script skips cleanup and keeps them.

### 9. Spot Fixes After the Build

If the user finds problems in a few places after the build, fix the affected
chunks rather than `output.md`: whenever a chunk changes, the build re-merges
`output.md` from the chunks and discards edits made there.

1. Find the chunk: search `<temp_dir>/output_chunk*.md` for the passage.
2. Either edit `output_chunk<NNNN>.md` directly, or have it re-translated.

   **Edit.** `record` stamps the chunk as matching the current source and
   glossary, so first check what the planner still expects from it:

   ```bash
   python3 {baseDir}/scripts/run_state.py plan "<temp_dir>"
   ```

   If chunk<NNNN> appears in `chunks[]` with action `translate`, recording
   would hide that. Handle it by reason:

   - `glossary_term_hash_changed` (its `detail` lists the term ids) or
     `glossary_term_selection_changed`: bring those terms in line with
     `glossary.py print-terms-for-chunk "<temp_dir>" "chunk<NNNN>.md"` in the
     same edit.
   - `manifest_source_hash_changed`: the source chunk was edited after
     splitting. Re-run the Step 2 `convert.py` command first, leaving out
     page-number flags such as `--strip-page-numbers`: once chunks exist,
     those flags abort and suggest deleting the cached files or the whole
     temp dir, which would also delete the translations. Without them it
     keeps the existing chunks and writes their new hashes to
     `manifest.json`. Skip this and the merge stops with "Source changed
     since splitting" even after re-translating. Plan again: the chunk is
     then queued with `source_hash_changed_since_record`.
   - `source_hash_changed_since_record` or any other reason: re-translate the
     chunk instead of editing it.

   Then record the edited output:

   ```bash
   python3 {baseDir}/scripts/run_state.py record "<temp_dir>" chunk<NNNN>
   ```

   **Re-translate.** Delete `output_chunk<NNNN>.md` and run Steps 3.7–4.5 again. The planner
   re-checks the whole book, so `translation_chunk_ids` can also list chunks
   the user did not mention, typically ones whose glossary terms changed after
   they were translated (`glossary_term_selection_changed` or
   `glossary_term_hash_changed` in the plan's `chunks[].reasons`). Translate
   only the chunks the user asked for; if the plan lists others, show the user
   those chunk ids with their reasons and ask before re-translating them.
3. Re-run the Step 7 build command with the same flags. It re-merges because
   the chunk is newer than `output.md`, then regenerates the HTML and the other
   formats.

### 10. Field Notes: Scanned Sources, CJK Targets, Large Books

Hard-won details from a 325-chunk, 450-page scanned book translated to Chinese.
None of them are optional on a run of that shape.

**Scanned PDFs with a hidden OCR layer.** Calibre's HTMLZ path keeps the
full-page scan images and throws the hidden text layer away — a 450-page book
comes out as ~2,800 characters of text. Check with `pdftotext <file.pdf> - |
wc -c` before trusting Calibre. If the text is there in `pdftotext` but not in
the Calibre output, extract the layer yourself and feed Markdown to
`convert.py`:

```bash
pdftohtml -hidden -i -xml "<file.pdf>" /tmp/book.xml   # layout + font styles
# clean XML -> Markdown: drop running heads/folios, merge drop caps and
# hyphenated line breaks, restore #/##/### levels
python3 {baseDir}/scripts/convert.py "/abs/path/book.md" --olang zh
```

Keep the Markdown file name equal to the PDF stem: the temp directory is named
after it.

**`plan` will re-queue everything after the glossary grows.** Once
`merge_meta.py` has merged a few hundred terms, every earlier chunk reports
`glossary_term_selection_changed`. That is expected bookkeeping, not a signal to
re-translate 300 chunks. Use `plan` to find chunks with **no output**, and
translate only those; only re-translate a recorded chunk when the user asks for
it or its source/term hash genuinely changed.

**EPUB navigation is empty for CJK unless you say otherwise.** Calibre's default
chapter detection matches English words (`chapter`, `section`, …); Chinese,
Japanese and Korean headings match nothing, so `nav.xhtml` ends up with a single
"start" entry. `calibre_html_publish.py` now passes
`--level1-toc "//h:h1" --level2-toc "//h:h2"` for `zh*`/`ja*`/`ko*`. Verify after
building:

```bash
unzip -p book.epub nav.xhtml | grep -c '<li>'
grep -o 'href="[^"]*"' nav.xhtml | sort -u | wc -l   # must be >1
```

**Non-ASCII heading ids break EPUB fragment links.** Calibre resolves
`#序言` to the first split file instead of the real one, so every TOC entry
jumps to the start. `--toc` rewrites ids to `sec001…`; if you hand-build a TOC,
do the same.

**Prompt files beat per-chunk prompt assembly.** With 300+ chunks, assembling
"rules + term table + neighbour context" by hand for each sub-agent is where
runs go wrong. Write one self-contained prompt file per chunk first:

```bash
python3 {baseDir}/scripts/glossary.py print-terms-for-chunk "<temp_dir>" "chunk0007.md" \
  > /tmp/prompts/chunk0007.md
python3 {baseDir}/scripts/chunk_context.py "<temp_dir>" "chunk0007.md" >> /tmp/prompts/chunk0007.md
```

then spawn each sub-agent with "read `/tmp/prompts/chunk0007.md` and carry out
the task it describes". Write those files atomically (temp file + rename) if you
regenerate them mid-run for chunks that are still in flight.

**OCR text needs a correction rule, not a cleanup pass.** ABBYY-era scans carry
`ofthe`, `pa~` for "party", `lVOmen` for "women", `communit))` for "community".
Add to `{CUSTOM_INSTRUCTIONS}`: "obvious OCR damage must be translated by
intended meaning; no `~` may survive into the output". `qa_chunks.py` flags any
that do.

**Spot-check the build, not just the files.** Render a few pages
(`pdftoppm -f 40 -l 40 -r 120 -png book.pdf out`) and confirm the folios, the
running text and the TOC page numbers agree. A TOC that lists page 7 for a
chapter that starts on 8 looks correct in every log line.
