# Task: draft {date} for run {run_id}

The day context below is the complete thread for this day: the current day log (if any), earlier
messages, and the open captures (text, transcripts, images) you have to turn into meals and line items.
Images that belong to captures are attached to this message in order.

## How to work

1. Read every capture. Group items into meals by the times and words the person used
   (breakfast, lunch, dinner, snack — or the meal names already present in the day log).
2. For each item call `product_search` with the words the person used. Prefer a product the person
   already has in the catalogue; a recipe batch counts as a product too.
3. Decide the quantity: label or weight given → exact; whole container → the container's portion;
   otherwise estimate, mark `quantity_estimated` and explain the basis in `rationale`.
4. If the day already has a draft, add only what is new or corrected; do not repeat existing items.
   Follow-up messages such as "the chicken was 300 g" are corrections: put them into the draft as
   the corrected item and say so in `notes` so the reviewer can drop the old one.
5. Call `draft_create` exactly once with:
   - `run_id` = `{run_id}`, `date` = `{date}`
   - `source_captures` = every capture id you used
   - up to three `candidates` per item, `chosen_consumable_id` or `one_off_nutrition_per_100`
   - `training` when the captures state it (rest, strength, martial_arts)
   - `notes` (≤ 5) and `open_questions` for anything the reviewer must decide
6. Stop after `draft_create` succeeds. Your final text reply is a two-sentence summary for the log.

Tenant language: {language}.
