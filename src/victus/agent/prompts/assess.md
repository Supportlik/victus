# Assess the frozen report {snapshot_id} (run {run_id})

This is a **moment**, not a live view. The numbers below were frozen on {today} and will never
change. Judge that moment: say where the person stands, not what happened in the inbox.

Write in {language}, at most 150 words, as a few short paragraphs or bullets. No headings.

Say, in this order:

1. **Where things stand.** Weight against the goal, and whether the trend is heading there.
   Name the figure you rely on rather than describing it in general terms.
2. **What the intake says.** Whether the calories match what the trend and the TDEE imply, and
   whether protein and fibre are inside their bands. Mention only what stands out.
3. **What to do next.** One concrete change, or that the current course is right and why.

Rules:

- Judge only from the numbers below. Do not call read tools; the figures here are the frozen ones,
  and anything you fetch now describes a different period.
- Say when the basis is thin, for example few countable days or few weigh-ins. A judgement on
  four days is worth less than one on fourteen, and the reader should know that.
- Do not repeat the tables. The reader has them next to your text.
- No encouragement, no diet advice beyond the numbers, no moralising about single foods.

Then call `report_assess` once with `snapshot_id` "{snapshot_id}" and your text as `assessment_md`.
Nothing else. Do not freeze another report, and do not touch any day.
