#!/usr/bin/env bash
# Apply three README.md fixes:
#   1. Pipeline example – replace source_from_db with fetch_all_draws
#   2. Wheel guarantees – single1/single2: 3/3 → 4/4
#   3. Python version  – 3.10+ → 3.12+
set -euo pipefail

FILE="README.md"

if [ ! -f "$FILE" ]; then
    echo "Error: $FILE not found."
    exit 1
fi

echo "=== Backing up $FILE as ${FILE}.bak ==="
cp "$FILE" "${FILE}.bak"

changes=0

# -------------------------------------------------------------------
# Fix 1 – Pipeline example code block
# -------------------------------------------------------------------
echo "=== Fix 1: Pipeline example (fetch_all_draws) ==="

# Only attempt if the old pattern still exists
if grep -qF "source_from_db" "$FILE"; then
    python3 -c "
import re

with open('$FILE') as f:
    content = f.read()

old = '''\`\`\`bash
python3 -c \"\"
from steps.historical import run as s1
from steps.frequency import run as s2
from steps.decay import run as s3
from steps.bayesian_fusion_with_mechanics import run as s4
from steps.clustering import run as s5
from steps.monte_carlo import run as s6
from steps.redundancy import run as s7
from steps.markov import run as s8
from steps.entropy import run as s9
from steps.generate_ticket import run as s12

from pipeline import run_pipeline, source_from_db

state = run_pipeline([
    source_from_db,
    s1, s2, s3, s4, s5, s6, s7, s8, s9, s12,
])
print('Ticket:', state['ticket_lines'])
\"\"
\`\`\`'''

new = '''\`\`\`python
from database import fetch_all_draws
from pipeline import run_pipeline
from steps.historical import run as s1
from steps.frequency import run as s2
from steps.decay import run as s3
from steps.bayesian_fusion_with_mechanics import run as s4
from steps.clustering import run as s5
from steps.monte_carlo import run as s6
from steps.redundancy import run as s7
from steps.markov import run as s8
from steps.entropy import run as s9
from steps.generate_ticket import run as s12

steps = [s1, s2, s3, s4, s5, s6, s7, s8, s9, s12]
state = {\"past_results\": fetch_all_draws()}
state = run_pipeline(steps, state)
print(\"Ticket:\", state[\"ticket_lines\"])
\`\`\`'''

content = content.replace(old, new)
with open('$FILE', 'w') as f:
    f.write(content)
print('Pipeline example updated.')
"
    changes=$((changes + 1))
else
    echo "Already applied (source_from_db not found)."
fi

# -------------------------------------------------------------------
# Fix 2 – Wheel guarantees (3/3 → 4/4)
# -------------------------------------------------------------------
echo "=== Fix 2: Wheel guarantees (3/3 → 4/4) ==="

for wheel in single1 single2; do
    if grep -q "| $wheel | 10 numbers | 20 | 3/3 (100%)" "$FILE"; then
        sed -i "s/| $wheel | 10 numbers | 20 | 3\/3 (100%)/| $wheel | 10 numbers | 20 | 4\/4 (100%)/" "$FILE"
        echo "  $wheel: updated to 4/4 (100%)."
        changes=$((changes + 1))
    else
        echo "  $wheel: already 4/4 (or pattern not found)."
    fi
done

# -------------------------------------------------------------------
# Fix 3 – Python version (3.10+ → 3.12+)
# -------------------------------------------------------------------
echo "=== Fix 3: Python version (3.10+ → 3.12+) ==="

if grep -q -- "- Python 3.10+" "$FILE"; then
    sed -i 's/- Python 3\.10+/- Python 3.12+/' "$FILE"
    echo "Python version updated."
    changes=$((changes + 1))
else
    echo "Already applied (or pattern not found)."
fi

# -------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------
echo ""
echo "=== Summary ==="
if [ "$changes" -gt 0 ]; then
    echo "$changes fix(es) applied. Original backed up as ${FILE}.bak."
    diff --color=always "$FILE.bak" "$FILE" | tail -20
else
    echo "All fixes were already applied. No changes made."
    rm -f "${FILE}.bak"
fi
