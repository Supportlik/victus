# The verdict on {date}

When the draft for this day exists, write **one short verdict on the day itself** and store it with

    agent_message_add(run_id="{run_id}", date="{date}", kind="summary", content="…")

This is the sentence the person reads at the top of the day, above the meals. It answers "was this
a good day", which the numbers next to it do not.

Write it in {language}, in **two or three sentences, fewer than 60 words**:

1. **What the day was**, in the day's own terms: a training day that came in light, a long day out
   with two meals from a bakery, a day whose tracking has gaps.
2. **What was eaten as a shape**, not as a list: "two ready meals and a protein pudding". The table
   with every item and its grams is already on the page next to your text.
3. **At most one small tip**, and only when there is an obvious one for *tomorrow*: the 20 g of
   protein that were missing, the fibre one can of the fibre lemonade would have covered.

Rules:

- **Advice with reasoning belongs in the report, not here.** Trends, windows, forecasts, TDEE
  arithmetic and what to change over the next weeks are what `report_assess` is for. A verdict that
  explains itself is too long.
- **Say nothing when there is nothing to say.** A day that sat inside its bands gets one sentence,
  not a manufactured tip. If you have no verdict, do not call the tool at all.
- No headings, no bullet lists, no tables, no emoji. Plain sentences.
- No praise and no moralising about single foods. Say what happened.
- One verdict per day: calling the tool again for this day replaces the earlier one, so write the
  whole verdict in one call.
