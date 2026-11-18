# 6. A model may draft the shift handover; code checks every number

## Context

Laser teams spend time at the end of each shift writing what happened into the electronic logbook. A language
model writes that note well, and it also writes a wrong number fluently.

## Decision

`lbp/elog/handover.py` collects the facts the data store can prove for a shift. A model drafts the note from
those facts when a key is configured; a template drafts it otherwise. Before anything posts, `check` reads every
number and shot id in the draft and refuses the note if one is not in the facts.

## Consequences

The model never decides what is true about a shift. The evaluation measures the checker, not the model: correct
drafts pass, and drafts with planted errors (a changed count, a moved decimal, an invented shot id, a number
from another shift) are stopped. A paraphrase that writes a number in words is not checked; that limit is
stated in the README.
