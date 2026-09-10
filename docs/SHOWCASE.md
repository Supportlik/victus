# Showcase

A tour of the web app, one screen at a time. Every picture comes from a demo tenant filled by
`scripts/demo_seed.py`: the food, the weights and the body measurements are invented, and no real
photograph or voice note is used. [`docs/media/README.md`](media/README.md) says how the set is
reproduced when the interface changes.

## The day

A day is the unit of work. The target bands sit above the meals, so the answer to "how am I
doing" is on the same screen as the food that answers it; each band shows the minimum, the
optimal range and the maximum for that day's training type, and the marker says where the day
stands. Nutrients are computed from the products the lines point to — a corrected label fixes
every day that used it — while the amounts are frozen at the moment of logging.

![The day: bands above, meals below, the thread beside them](media/day-light.jpg)

The thread on the right is how the day talks back. Text, a voice note or a photograph each
become a capture; the agent reads them on its next run and answers here.

The same day in the dark scheme. Light and dark follow the device unless a person pins one,
and there are six palettes to pin them in — the choice is per browser, not per account:

![The same day in the dark scheme](media/day-dark.jpg)

And at phone width, where the rail becomes a bottom bar and the two columns stack — the day's
own controls, then the bands, then the meals, and the thread last:

![The day at phone width](media/day-phone.jpg)

## Logging an item

Search a product, give the amount, pick the unit — the item lands and the bands move with it.
Piece weights are portions on the product, so "1 piece (M)" is logged without weighing anything:

![Searching a product, picking a portion, the item lands in the meal](media/log-item.gif)

## The question a portion answers

A unit the product has no portion for is not refused and not guessed: the app asks once what
one of them weighs, saves it with the product, and the unit works from then on.

![Choosing a unit with no portion asks what one of them weighs, once](media/size-question.gif)

## The catalogue

A product's nutrients are stated per 100 g or 100 ml, once — there is no per-portion nutrition
and no second row for a second size. The source column carries both halves of where a number
stands: a badge saying whether it came off a label or is still an estimate, and the text of
where it came from.

![The product catalogue, nutrients per 100 g and where each came from](media/products.jpg)

A product page shows the values, whether a density exists (and what it would let you convert),
the label photos and notes still waiting for the agent, and every day this product was eaten:

![A product page: values, label captures, and where you ate this](media/product.jpg)

Portions live only here, and only in the unit the product's nutrients are stated in. One per
unit can be the default, which decides what "2 piece" means when a day does not say which size:

![The portions of a product, in grams, one of them the default](media/portions.jpg)

## The check-up

"Am I on track?" is a report, not a hard-coded page: a YAML document rendered to JSON for the
web, Markdown for a chat, or SVG. Weight, intake, the rolling TDEE and the macros share one
time axis. The reference TDEE says which window it was taken from, and the table below grades
every window beside it — 7 to 90 days, with the coverage each is based on — so a number resting
on 38 % of a quarter is marked as such instead of being read as a measurement.

![The check-up: weight, intake, TDEE windows and how reliable each is](media/reports-checkup.jpg)

The body block shows the classes in the unit a person can act on. A BMI of 27.1 means little on
its own, so the table also carries the kilograms each class begins at and how far away it is:

![The body block: BMI, waist ratios, and what each class means in kilograms](media/reports-body.jpg)
