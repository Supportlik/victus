# How the pictures were made

Every image in this folder comes from a tenant built by `scripts/demo_seed.py`. Nothing in
them is real: the food, the weights and the body measurements are invented, and no product
photograph or voice note of a real person is used (SPEC R48). That is what makes them
retakeable — when the interface changes, the set is reshot from the same seed instead of
being left to rot.

## Reproducing the set

```sh
# 1. a throwaway database and a tenant
export VICTUS_CONFIG_FILE=victus.yaml     # sqlite:///demo.db, storage in ./blobs
victus migrate
victus tenant create demo --name Demo
victus user create --tenant demo --email demo@example.invalid --name Demo   # prints a recovery code
victus token create --tenant demo --name seed --scopes read,write,approve

# 2. the data: a month of days, weights, body measurements, 17 products
victus serve --host 127.0.0.1 --port 8020 &
python scripts/demo_seed.py --base http://127.0.0.1:8020/api/v1 --token vct_…

# 3. the app against it
cd web && VICTUS_API_PORT=8020 npx ng serve --port 4210 --host 127.0.0.1
```

The seed ends on the day it runs, so a report opens on data rather than on an empty window.
Pass `--today 2026-06-15` to pin it when a picture has to be reproduced exactly.

## Signing in

The app is passkey-only, and a recovery session may do nothing but register a passkey — so
there is no way to script a login. For a throwaway demo database, sign in with the recovery
code the CLI printed and then lift the restriction on that one session:

```sh
sqlite3 demo.db "UPDATE session SET user_agent = replace(user_agent, 'recovery:', '')"
```

That marker is the whole mechanism: `is_recovery_session()` reads it off the user agent. Do
this on a demo database and nowhere else. The proper answer is the virtual authenticator the
test plan describes for `T-E2E-001`, which is not written yet.

## What each frame shows

| File | Route | Notes |
|---|---|---|
| `day-light.jpg` | `/days/<a closed strength day>` | Bands, three meals, the thread beside them |
| `day-dark.jpg` | the same day | The same page in the dark scheme |
| `reports-checkup.jpg` | `/reports`, period 14 days | Tiles, the one time axis, the TDEE windows |
| `reports-body.jpg` | `/reports`, scrolled to Body | The BMI scale with its classes as kilograms |
| `products.jpg` | `/products` | The catalogue and a proposal waiting to be decided |
| `day-phone.jpg` | `/days/<the same day>` at 420 px | The day and its navigation at phone width |
| `log-item.gif` | `/days/<an open day>` | Search a product, pick a portion, the item lands |
| `size-question.gif` | the same day | A unit the product has no portion for, asked once |

Screenshots come out of the browser as JPEG, which is why they are not PNG. Recordings are
kept to the seconds that carry the point; a recording that shows a static screen should have
been a still.
