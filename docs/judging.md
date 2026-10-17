# Judging and participant credit

Each accepted work has four criteria in the inclusive range 0-10 and a total in
0-40. NaN, infinity, missing criteria and out-of-range values are rejected before
mutating the result. Fractional scores use the next level's lower bound:
White starts at 0, Orange at 11, Green at 19, Red at 26, Black at 33 and Gold at 39.
For example 18.5 is Orange, while 19 is Green. A zero-point accepted result is
still evaluated and counts as one evaluated work.

The admin workflow records evaluation history and uses the latest decision for
the displayed submission result. The averaging utility computes an arithmetic
mean across recorded evaluations when explicitly invoked; it is not an automatic
multi-judge consensus policy.

Replacing an accepted score updates participant points by the difference between
old and new integer totals. Repeating the same decision does not add credit.
Rejecting a previously accepted work removes its credit and evaluated-work count.
The stored total can remain available for audit even when status is rejected.

Leaderboard positions are deterministic: points descending, then user ID
ascending. Banned accounts are excluded from the active leaderboard. The full
participant export remains an administrative record and includes those accounts.
