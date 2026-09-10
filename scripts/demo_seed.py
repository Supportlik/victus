"""Fill a tenant with invented data, so the app can be shown without showing anyone.

Every screenshot and recording in `docs/media/` comes from a tenant built by this script.
That is the point of it: the pictures can be retaken when the interface changes instead of
rotting, and nothing about a real person's food, weight or body ever reaches them (R48).

    victus tenant create --slug demo --name Demo
    victus user create --tenant demo --email demo@example.invalid   # prints a recovery code
    victus token create --tenant demo --name seed --scopes read,write,approve
    python scripts/demo_seed.py --base http://127.0.0.1:8020/api/v1 --token vct_…

The seed ends on the day it runs, so the report opens on data rather than on an empty
window; `--today` pins it when a picture has to be reproduced exactly.

The numbers are made up but they hang together: the days add up to what the bands say, the
weights fall at a rate the forecast can work with, and the one estimate and the one open
question are there because a screenshot of a perfect day teaches nothing.
"""

from __future__ import annotations

import argparse
import json
import random
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

#: The seed ends on the day it runs, so a report opens on data instead of on an empty
#: window. Pass --today to pin it when a screenshot has to be reproduced exactly.
TODAY = date.today()
DAYS = 34

#: A small catalogue: enough for a search to have something to rank, and for a day to look
#: like someone's actual food rather than three rows of "Product 1".
PRODUCTS: list[dict] = [
    # name, kcal, protein, carbs, fat, fiber, salt, portions
    {
        "name": "Skyr natural (Arla)",
        "brand": "Arla",
        "kcal": 63,
        "protein": 11,
        "carbs": 3.7,
        "fat": 0.2,
        "fiber": 0,
        "salt": 0.1,
        "portions": [{"unit_code": "tub", "label": "tub", "amount": 400, "is_default": True}],
    },
    {
        "name": "Egg (hen's egg)",
        "kcal": 156,
        "protein": 12.9,
        "carbs": 0.9,
        "fat": 11.3,
        "fiber": 0,
        "salt": 0.35,
        "portions": [
            {"unit_code": "piece", "label": "S", "amount": 43},
            {"unit_code": "piece", "label": "M", "amount": 47},
            {"unit_code": "piece", "label": "L", "amount": 56, "is_default": True},
            {"unit_code": "piece", "label": "XL", "amount": 65},
        ],
    },
    {
        "name": "Oat porridge, dry",
        "kcal": 372,
        "protein": 13.5,
        "carbs": 58.7,
        "fat": 7,
        "fiber": 10,
        "salt": 0.01,
    },
    {
        "name": "Raspberries (fresh or frozen)",
        "kcal": 34,
        "protein": 1.2,
        "carbs": 4.8,
        "fat": 0.3,
        "fiber": 6.5,
        "salt": None,
    },
    {
        "name": "Chicken breast, raw",
        "kcal": 106,
        "protein": 24,
        "carbs": 0,
        "fat": 1.2,
        "fiber": 0,
        "salt": 0.09,
    },
    {
        "name": "Basmati rice, cooked",
        "kcal": 130,
        "protein": 2.7,
        "carbs": 28,
        "fat": 0.3,
        "fiber": 0.4,
        "salt": None,
    },
    {
        "name": "Broccoli, steamed",
        "kcal": 35,
        "protein": 2.4,
        "carbs": 3.1,
        "fat": 0.4,
        "fiber": 3.3,
        "salt": 0.03,
    },
    {
        "name": "Olive oil",
        "kcal": 884,
        "protein": 0,
        "carbs": 0,
        "fat": 100,
        "fiber": 0,
        "salt": None,
        "reference_unit": "ml",
        "density_g_per_ml": 0.92,
        "portions": [
            {
                "unit_code": "tbsp",
                "label": "tbsp",
                "amount": 15,
                "amount_unit": "ml",
                "is_default": True,
            }
        ],
    },
    {
        "name": "Rye bread, whole grain",
        "kcal": 214,
        "protein": 6.5,
        "carbs": 36,
        "fat": 1.7,
        "fiber": 8.2,
        "salt": 1.1,
        "portions": [{"unit_code": "slice", "label": "slice", "amount": 45, "is_default": True}],
    },
    {
        "name": "Gouda, mature (48 % f.i.d.m.)",
        "kcal": 380,
        "protein": 25,
        "carbs": 0,
        "fat": 31,
        "fiber": 0,
        "salt": 1.9,
        "portions": [{"unit_code": "slice", "label": "slice", "amount": 25, "is_default": True}],
    },
    {
        "name": "Protein shake, whey (powder)",
        "brand": "Foodspring",
        "kcal": 373,
        "protein": 80,
        "carbs": 4.5,
        "fat": 3.5,
        "fiber": 1,
        "salt": 0.5,
        "portions": [{"unit_code": "scoop", "label": "scoop", "amount": 30, "is_default": True}],
    },
    {
        "name": "Semi-skimmed milk (1.5 %)",
        "kcal": 47,
        "protein": 3.4,
        "carbs": 4.8,
        "fat": 1.5,
        "fiber": 0,
        "salt": 0.1,
        "reference_unit": "ml",
        "density_g_per_ml": 1.03,
        "portions": [
            {
                "unit_code": "glass",
                "label": "glass",
                "amount": 250,
                "amount_unit": "ml",
                "is_default": True,
            }
        ],
    },
    {
        "name": "Banana",
        "kcal": 89,
        "protein": 1.1,
        "carbs": 20.2,
        "fat": 0.3,
        "fiber": 2.6,
        "salt": None,
        "portions": [{"unit_code": "piece", "label": "piece", "amount": 120, "is_default": True}],
    },
    {
        "name": "Almonds",
        "kcal": 579,
        "protein": 21,
        "carbs": 6.9,
        "fat": 50,
        "fiber": 12.5,
        "salt": 0.01,
        "portions": [
            {"unit_code": "handful", "label": "handful", "amount": 25, "is_default": True}
        ],
    },
    {
        "name": "Lentil bolognese (batch cooked)",
        "kcal": 118,
        "protein": 7.4,
        "carbs": 14.6,
        "fat": 2.9,
        "fiber": 5.1,
        "salt": 0.6,
        "portions": [
            {"unit_code": "portion", "label": "portion", "amount": 350, "is_default": True}
        ],
    },
    {
        "name": "Dark chocolate, 70 %",
        "kcal": 598,
        "protein": 7.8,
        "carbs": 45.9,
        "fat": 42.6,
        "fiber": 10.9,
        "salt": 0.02,
        "portions": [{"unit_code": "bar", "label": "bar", "amount": 100, "is_default": True}],
    },
    {
        "name": "Sparkling water",
        "kcal": 0,
        "protein": 0,
        "carbs": 0,
        "fat": 0,
        "fiber": 0,
        "salt": None,
        "reference_unit": "ml",
        "portions": [
            {
                "unit_code": "bottle",
                "label": "bottle",
                "amount": 750,
                "amount_unit": "ml",
                "is_default": True,
            }
        ],
    },
]

#: A day is built from one of these shapes, so the week has variety without being random.
SHAPES: list[dict] = [
    {
        "training": "rest",
        "meals": [
            (
                "Breakfast",
                [
                    ("Skyr natural (Arla)", 1, "tub"),
                    ("Raspberries (fresh or frozen)", 150, "g"),
                    ("Oat porridge, dry", 50, "g"),
                ],
            ),
            (
                "Lunch",
                [("Lentil bolognese (batch cooked)", 1, "portion"), ("Olive oil", 1, "tbsp")],
            ),
            (
                "Dinner",
                [
                    ("Rye bread, whole grain", 2, "slice"),
                    ("Gouda, mature (48 % f.i.d.m.)", 2, "slice"),
                    ("Egg (hen's egg)", 2, "piece"),
                ],
            ),
        ],
    },
    {
        "training": "strength",
        "meals": [
            (
                "Breakfast",
                [
                    ("Oat porridge, dry", 80, "g"),
                    ("Semi-skimmed milk (1.5 %)", 250, "ml"),
                    ("Banana", 1, "piece"),
                ],
            ),
            (
                "After training",
                [
                    ("Protein shake, whey (powder)", 1, "scoop"),
                    ("Semi-skimmed milk (1.5 %)", 300, "ml"),
                ],
            ),
            (
                "Dinner",
                [
                    ("Chicken breast, raw", 200, "g"),
                    ("Basmati rice, cooked", 220, "g"),
                    ("Broccoli, steamed", 200, "g"),
                    ("Olive oil", 1, "tbsp"),
                ],
            ),
        ],
    },
    {
        "training": "martial_arts",
        "meals": [
            (
                "Breakfast",
                [("Rye bread, whole grain", 2, "slice"), ("Egg (hen's egg)", 3, "piece")],
            ),
            (
                "Lunch",
                [
                    ("Chicken breast, raw", 180, "g"),
                    ("Basmati rice, cooked", 200, "g"),
                    ("Broccoli, steamed", 150, "g"),
                ],
            ),
            (
                "Evening",
                [
                    ("Skyr natural (Arla)", 1, "tub"),
                    ("Almonds", 1, "handful"),
                    ("Dark chocolate, 70 %", 20, "g"),
                ],
            ),
        ],
    },
    {
        "training": "rest",
        "meals": [
            ("Breakfast", [("Skyr natural (Arla)", 1, "tub"), ("Banana", 1, "piece")]),
            ("Lunch", [("Lentil bolognese (batch cooked)", 1, "portion")]),
            (
                "Dinner",
                [
                    ("Chicken breast, raw", 150, "g"),
                    ("Broccoli, steamed", 250, "g"),
                    ("Olive oil", 1, "tbsp"),
                    ("Rye bread, whole grain", 1, "slice"),
                ],
            ),
            ("Late", [("Dark chocolate, 70 %", 25, "g")]),
        ],
    },
]


class Api:
    def __init__(self, base: str, token: str) -> None:
        self.base = base.rstrip("/")
        self.token = token

    def __call__(self, method: str, path: str, body: object | None = None) -> object:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Authorization", "Bearer " + self.token)
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raise SystemExit(f"{method} {path} -> {e.code}: {e.read().decode()[:400]}") from e


def seed_products(api: Api) -> dict[str, int]:
    ids: dict[str, int] = {}
    for spec in PRODUCTS:
        portions = spec.pop("portions", [])
        fields = {
            "reference_amount": 100.0,
            "reference_unit": "g",
            "source": "invented for the demo tenant",
            "verified": True,
            **spec,
        }
        product = api("POST", "/products", fields)
        assert isinstance(product, dict)
        ids[str(spec["name"])] = int(product["id"])
        for portion in portions:
            api(
                "POST",
                f"/products/{product['id']}/portions",
                {
                    "amount_unit": "g",
                    "is_default": False,
                    "weight_source": "weighed",
                    **portion,
                },
            )
        spec["portions"] = portions  # leave the table as it was, for a second run
    return ids


def seed_days(api: Api, products: dict[str, int]) -> None:
    """A month of days: the last one open, the rest closed, one estimate, one gap."""
    rng = random.Random(20260615)
    for offset in range(DAYS, -1, -1):
        day = TODAY - timedelta(days=offset)
        shape = SHAPES[offset % len(SHAPES)]
        api(
            "POST",
            f"/days/{day.isoformat()}",
            {
                "reliable": True,
                "training_type": shape["training"],
            },
        )
        for name, items in shape["meals"]:
            meal = api("POST", f"/days/{day.isoformat()}/meals", {"name": name})
            assert isinstance(meal, dict)
            for product_name, amount, unit in items:
                # one item a fortnight is an estimate: a screenshot of a day with no
                # uncertainty in it says nothing about how uncertainty is shown
                estimated = offset % 14 == 3 and product_name.startswith("Chicken")
                api(
                    "POST",
                    f"/meals/{meal['id']}/line-items",
                    {
                        "consumable_id": products[product_name],
                        "amount": amount * (1 + rng.uniform(-0.05, 0.05) if unit == "g" else 1),
                        "unit_code": unit,
                        "estimated": estimated,
                        "amount_estimated": estimated,
                    },
                )
        if offset > 0:
            api("POST", f"/days/{day.isoformat()}/close")


def seed_weights(api: Api) -> None:
    """A downward trend with the noise a real scale has, so the forecast has work to do."""
    rng = random.Random(4711)
    start = 92.4
    for offset in range(DAYS + 1, -1, -1):
        day = TODAY - timedelta(days=offset)
        if offset % 7 == 4:
            continue  # a scale nobody stood on: coverage is part of what the report judges
        trend = start - (DAYS + 1 - offset) * 0.085
        api(
            "POST",
            "/weight",
            {
                "measured_at": datetime.combine(day, datetime.min.time())
                .replace(hour=7, minute=12)
                .isoformat()
                + "Z",
                "kg": round(trend + rng.uniform(-0.45, 0.45), 1),
                "source": "manual",
            },
        )


def seed_body(api: Api) -> None:
    for offset, waist, hip, belly in ((DAYS, 104.5, 108.0, 110.2), (4, 99.8, 105.1, 104.6)):
        day = TODAY - timedelta(days=offset)
        api(
            "POST",
            "/body-measurements",
            {
                "measured_at": datetime.combine(day, datetime.min.time())
                .replace(hour=8)
                .isoformat()
                + "Z",
                "waist_cm": waist,
                "hip_cm": hip,
                "belly_cm": belly,
                "chest_cm": 106.0,
                "neck_cm": 40.5,
                "thigh_cm": 61.0,
                "arm_cm": 35.5,
                "source": "manual",
            },
        )


def _band(low: float, opt_low: float, opt_high: float, target: float, high: float) -> dict:
    return {"min": low, "opt_min": opt_low, "opt_max": opt_high, "target": target, "max": high}


def seed_settings(api: Api) -> None:
    """Goal, corridor and one band per kind of day, so a day has something to be judged against."""
    start = (TODAY - timedelta(days=DAYS + 1)).isoformat()
    bands = [
        {
            "name": "Rest day",
            "training_type": "rest",
            "valid_from": start,
            "kcal": _band(1700, 1700, 2200, 2100, 2200),
            "protein": _band(120, 150, 185, 165, 200),
            "carbs": _band(120, 150, 210, 180, 240),
            "fat": _band(45, 55, 75, 65, 85),
            "fiber": _band(25, 32, 40, 35, 50),
            "salt": _band(4, 5, 7, 6, 12),
        },
        {
            "name": "Strength day",
            "training_type": "strength",
            "valid_from": start,
            "kcal": _band(1900, 2000, 2500, 2400, 2600),
            "protein": _band(140, 170, 205, 185, 220),
            "carbs": _band(180, 210, 280, 250, 300),
            "fat": _band(45, 55, 75, 65, 85),
            "fiber": _band(25, 32, 40, 35, 50),
            "salt": _band(4, 6, 8, 7, 12),
        },
        {
            "name": "Martial arts day",
            "training_type": "martial_arts",
            "valid_from": start,
            "kcal": _band(2000, 2100, 2600, 2500, 2700),
            "protein": _band(140, 170, 205, 185, 220),
            "carbs": _band(200, 230, 300, 270, 330),
            "fat": _band(45, 55, 75, 65, 85),
            "fiber": _band(25, 32, 40, 35, 50),
            "salt": _band(4, 6, 9, 8, 13),
        },
    ]
    api(
        "PUT",
        "/settings",
        {
            "data": {
                "goal": {"weight_kg": 82.0, "date": (TODAY + timedelta(days=120)).isoformat()},
                "kcal_per_kg": 7700.0,
                "calorie_corridor": {"min": 1700, "max": 2600},
                "target_bands": bands,
                "body": {"height_cm": 182.0, "sex": "m", "birth_date": "1990-04-11"},
                "regional": {"timezone": "Europe/Berlin", "locale": "en-GB"},
            }
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8020/api/v1")
    parser.add_argument("--token", required=True)
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        help="Last day of the seed (default: today). Pin it to reproduce a screenshot.",
    )
    args = parser.parse_args()
    if args.today:
        global TODAY
        TODAY = args.today
    api = Api(args.base, args.token)

    print("settings…")
    seed_settings(api)
    print("products…")
    products = seed_products(api)
    print(f"  {len(products)} products")
    print("weights…")
    seed_weights(api)
    print("body measurements…")
    seed_body(api)
    print(f"days ({DAYS + 1})…")
    seed_days(api, products)
    print(f"\ndone: {TODAY.isoformat()} is the open day")


if __name__ == "__main__":
    main()
