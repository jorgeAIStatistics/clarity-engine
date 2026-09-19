"""Stub. No graph neural network is trained, and this module refuses to pretend otherwise.

The gate is in ml/export.py and its result is written into every dated manifest, so the claim is
checkable rather than asserted. On 2026-09-19 it reads:

    entities             174 / 200
    linked findings       95 / 200   <- not 154: that total counts findings with no entity edge
    baseline exists      yes (ml/gap_ranker.py + docs/gap-queue.md)
    passes               false

The middle number is the one that matters and the one most easily fudged. A finding with
provenance='cited' is stored and carries no ABOUT edge, because it is a number the paper quoted
from somewhere else; counting it would let the gate pass on evidence the graph does not hold.

When the gate does pass, the comparison is fixed in advance: predict a held-out RELATED_TO edge, or
"utility-evidence likely vs association-only", split BY PAPER AND BY ENTITY so a model cannot be
scored on findings from a study it trained on, against ml/gap_ranker.py on the same split. If it
does not beat that baseline it does not ship, and nothing it predicts is ever care advice — the
output is a suggestion about which entity to read next.
"""

GATE = {"entities_required": 200, "linked_findings_required": 200}


def train(*_args, **_kwargs):
    raise RuntimeError(
        "The GNN gate has not passed: 174 entities and 95 linked findings against 200 and 200. "
        "Run `python -m ml.export` and read gnn_gate in the dated manifest."
    )
