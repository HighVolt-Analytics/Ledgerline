"""Named thresholds for bank transaction matching (Phase 3).

Scoring formula is documented in the Bank Feeds plan and must be reviewed
before bank_match_service implements it. Do not change band cutoffs inline
in the matcher — edit these constants only.
"""

from __future__ import annotations

# High bar for initial rollout; lower after observing real match data.
AUTO_MATCH_CONFIDENCE_THRESHOLD = 0.95

# Inclusive lower bound for writing a suggested match row.
SUGGESTED_MATCH_CONFIDENCE_THRESHOLD = 0.60

# Candidate search window around bank txn_date vs payment.paid_date /
# collection.received_date (or scheduled/due when paid/received is null).
MATCH_DATE_WINDOW_DAYS = 7
