# Prompt pack

The Covella prompt pack is a set of 31 prompts derived from "AI and the Lottery: Defying Odds with Intelligent Prediction" (Gary Covella, Ph.D.), categorised by what the project can do with each one.

---

## The idea

The prompts are not a to-do list to grind through. They are a map of the project's scope - a way to see what's implemented, what's partially built, and what's aspirational. The runner classifies each prompt into one of three categories:

| Category | Meaning | What the runner does |
|---|---|---|
| Runnable | Backing script exists | Executes it |
| NeedsScript | Not yet implemented | Writes a todo_NN_*.txt stub |
| Advisory | Pure text; no execution | Writes prompt_NN_*.md for pasting into any AI |

Running with different flags tells you different things:

- -Runnable - "what does the project actually do right now"
- -NeedsScript - "what have I not built yet" (the roadmap)
- -Advisory - "what questions should I ask an AI about"

---

## Running it

    cd D:\lotto-wheel-app
    .\venv\Scripts\Activate.ps1

    # Dry preview: to-do list and advisory prompts only
    .\scripts\prompts\Invoke-PromptPack.ps1 -NeedsScript -Advisory

    # Run the executable prompts
    .\scripts\prompts\Invoke-PromptPack.ps1 -Runnable

    # Everything
    .\scripts\prompts\Invoke-PromptPack.ps1 -All

Output lands in reports/prompts/:

    reports/prompts/
      run_YYYY-MM-DD_HHMMSS.log          Timestamped run log
      prompt_02_Folder_structure.md      Advisory prompts (paste-ready)
      prompt_03_Local_vs_Colab.md
      ...
      todo_08_Frequency_hot-cold.txt     Build checklist
      todo_09_Chi_square_uniformity.txt
      ...

The prompt_*.md files are self-contained: each contains a single prompt with header. Copy the body and paste into any AI assistant.

---

## Adding or editing a prompt

The catalog is scripts/prompts/catalog.psd1. Each entry looks like:

    @{ Id = 9; Title = "Chi-square uniformity"; Category = "NeedsScript";
       Dispatch = @{ Type = "PythonModule"; Module = "scripts.analysis.chi_square" } }

Categories and dispatch shapes:

- Runnable + @{ Type = "Script"; Path = "path/to/script.py" } - runs python path/to/script.py
- Runnable + @{ Type = "Shell"; Path = "python -m mypy ." } - runs an arbitrary shell command
- NeedsScript + @{ Type = "PythonModule"; Module = "pkg.mod" } - writes a stub naming the module
- Advisory + Prompt = "..." - writes the prompt as markdown

### Editing safely

Edit the catalog in Notepad, not VS Code. VS Code auto-corrects hyphens between words to em-dash, which breaks PowerShell's Import-PowerShellDataFile. Notepad saves pure ASCII.

If the catalog breaks anyway, normalise it:

    $path = "scripts\prompts\catalog.psd1"
    (Get-Content $path -Raw -Encoding UTF8) `
        -replace [char]0x2014,'-' -replace [char]0x2013,'-' `
        | Set-Content $path -Encoding ASCII

Then verify:

    Import-PowerShellDataFile scripts\prompts\catalog.psd1 | Out-Null
    if ($?) { "catalog OK" }

---

## Working with the runner

The runner is scripts/prompts/Invoke-PromptPack.ps1. It is self-contained; no external dependencies beyond PowerShell and the venv Python.

Its logic:

1. Resolve repo root from $PSScriptRoot
2. Import catalog.psd1
3. Create reports/prompts/ if needed
4. For each entry, dispatch based on Category
5. Write a timestamped log of everything it did

To add a new mode (e.g. -Summary that prints counts only), edit the switch in Invoke-Entry and add a parameter to the top of the script.

---

## Current state

| Category | Count | Notes |
|---|---|---|
| Runnable | 4 | Setup, backfill, repair, tests |
| NeedsScript | 13 | Analysis scripts (chi_square, frequency, etc.) |
| Advisory | 11 | Paste-ready prompts |

The NeedsScript items are the concrete roadmap. Each todo_*.txt in reports/prompts/ names the module you would create to turn it into a Runnable.

Recommended build order for the analysis scripts:

1. scripts/analysis/chi_square.py - smallest, most interpretive value
2. scripts/analysis/frequency.py - feeds every other analysis
3. scripts/analysis/ev_table.py - uses the fixed prize_calculator
4. scripts/analysis/runs_test.py - randomness honesty check

Each is 60-120 lines, reads data/lotto.db via the shared loader, and prints a report. No new dependencies needed (pandas and scipy are already in the venv).

---

## Committing

The catalog and runner are durable artifacts and should be committed. The generated reports/prompts/ content is ephemeral; either commit it as a snapshot or gitignore it:

    reports/prompts/run_*.log
    reports/prompts/todo_*.txt
    reports/prompts/prompt_*.md

Either choice is defensible. Committing snapshots gives you a timeline; gitignoring keeps the repo tidy.