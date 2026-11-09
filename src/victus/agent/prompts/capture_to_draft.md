# Task: draft {date} for run {run_id}

The day context below is the complete thread for this day: the current day log (if any), earlier
messages, and the open captures (text, transcripts, images) you have to turn into meals and line items.
Images that belong to captures are attached to this message in order.

## How to work

1. Read every capture. Group items into meals by the times and words the person used
   (breakfast, lunch, dinner, snack — or the meal names already present in the day log).
2. For each item, look at "Recently logged" first, then call `product_search` once with the item
   as said (brand included). It tries the variants itself — the food's main word, the brand
   alone, without quantities, filler words and umlauts, near spellings of a misheard brand — and
   returns products and one-offs logged before, best first, each with a `score`. Read the whole
   `products` list before you conclude that nothing fits. Prefer a product the person already has
   in the catalogue or has logged before; a recipe batch (in `matches`) counts as a product too;
   an `ad_hoc` entry that fits is reused by its id.
3. Decide the quantity: label or weight given → exact; whole container → the container's portion;
   otherwise estimate, mark `quantity_estimated` and explain the basis in `rationale`. When the
   person names a pack, slice or piece count and the product lacks that portion, propose it with
   `portion_create`.
4. If the day already has a draft, add only what is new or corrected; do not repeat existing items.
   Follow-up messages such as "the chicken was 300 g" are corrections: put them into the draft as
   the corrected item and say so in `notes` so the reviewer can drop the old one.
5. **Not every capture is food.** A note, a spoken list or a photo of a tape measure may carry
   body measurements, for instance "waist 126, hip 118" or "Taille 126,4". Call `body_add` for
   those, with the capture's own time, and record only the values actually stated: a missing
   circumference must stay empty, because the ratios built on it would otherwise be wrong. A
   weight belongs in `weight_add`, not there. Then mark that capture with `capture_mark` and do
   not put it into the draft. If a capture holds both food and measurements, do both.
6. Call `draft_create` exactly once with:
   - `run_id` = `{run_id}`, `date` = `{date}`
   - `source_captures` = every capture id you used
   - up to three `candidates` per item, `chosen_consumable_id` or `one_off_nutrition_per_100`
     with `one_off_name` (the food, not the sentence)
   - `training` when the captures state it (rest, strength, martial_arts)
   - `notes` (≤ 5) and `open_questions` for anything the reviewer must decide
7. Once `draft_create` has succeeded, write the day's verdict with `agent_message_add` as the next
   section asks, then stop. Your final text reply says nothing the verdict does not.

Tenant language: {language}.
