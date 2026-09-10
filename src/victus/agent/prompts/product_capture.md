# Product capture {capture_id} (run {run_id})

This capture is about **one product**, not a day. Read the nutrition label in the image or the
correction in the transcript and propose the product's values.

Steps:
1. Compare what you can read with the product JSON below. Only values that are legible count.
2. Call `product_propose` once with `product_id`, `changes` (per 100 g or 100 ml: kcal, protein,
   carbs, fat, fiber, salt; name, brand, ean or reference_unit when they differ), `capture_id`
   "{capture_id}", `source` "label photo, capture {capture_id}" and a one-sentence `rationale`
   in {language}.
3. If the label states a portion (e.g. "1 slice = 25 g"), add it with `portion_create`. If a
   portion already on the product contradicts the label, correct it with `portion_update` rather
   than adding a second one, and use `portion_delete` with a `reason` for one that cannot exist.
4. If nothing is legible or the capture is not about this product, call `capture_mark` with
   status `failed` and explain in one sentence. Then stop.

Do not call `product_update`; a person approves your proposal in the app.
