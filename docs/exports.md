# Excel exports

An administrator can request `/export excel` or use the export menu action. The
workbook contains participants, submissions, leaderboard and evaluation history.
Fractional criteria and totals remain numeric values. Participant points remain
integers under the current scoring rule. Formula-like nicknames and comments are
written as literal text rather than executable spreadsheet formulas.

Default filenames include a timestamp and a random identifier, so simultaneous
requests do not share an output. The exporter writes a temporary file beside the
destination, closes the workbook and replaces the destination only after success.
A failed write preserves an older destination and removes its temporary file.

The Telegram handler removes the generated workbook after a successful upload.
If upload fails, a completed workbook can remain in the working directory; inspect
and remove it manually according to your retention policy. Export files contain
participant data and are excluded from version control.

To inspect the output without Telegram, use the integration tests with their
in-memory SQLite fixtures:

```bash
python -m unittest tests.test_scoring -v
```
