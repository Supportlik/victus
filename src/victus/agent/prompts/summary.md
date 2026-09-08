# Run summary format

The run summary is Markdown the person reads in the app or in a chat. It is assembled by the
runner, not by the model; this file documents the shape so both runners produce the same page.

```
## Drafts {first_day} - {last_day} (run {run_short}, {n_days} days, {n_captures} captures, {cost} USD)

### {date} . draft . {kcal} kcal . protein {protein} g . {n_estimates} estimates
| Meal | Item | Quantity | kcal | Confidence | Draft |
|---|---|---|---|---|---|
| ... |
- {finding or note}
- ? {open question}

**Check-up (14 d):** {checkup markdown}

Approve? Reply "approve {date}" or give corrections (e.g. "chicken 300 g").
```

Rules:

- One section per drafted day, oldest first; skipped days get one line with the reason
  (locked by another run, no captures, budget exhausted, model refused).
- Estimated quantities are flagged on the quantity cell; confidence is shown with two decimals.
- Open questions from the draft are listed under the day as bullets starting with "?".
- The check-up block is the built-in `checkup` report for the last 14 days.
- Finish with the approval hint; the person answers in the same chat or in the app.
