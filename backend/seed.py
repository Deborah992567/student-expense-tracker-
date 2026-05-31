from decimal import Decimal

from sqlalchemy.orm import Session

from backend import models


DEFAULT_CATEGORIES = [
    ("Food", Decimal("0"), "#0f9f9a"),
    ("Transport", Decimal("0"), "#2563eb"),
    ("Books", Decimal("0"), "#7c3aed"),
    ("Rent", Decimal("0"), "#159947"),
    ("Social", Decimal("0"), "#c18400"),
    ("Health", Decimal("0"), "#d0342c"),
]


def seed_user_defaults(db: Session, user: models.User) -> None:
    for name, budget, color in DEFAULT_CATEGORIES:
        db.add(models.Category(user_id=user.id, name=name, budget=budget, color=color))

    db.add(models.Goal(user_id=user.id, name="Emergency fund", target=Decimal("600"), saved=Decimal("0")))
    db.add(models.UserSettings(user_id=user.id, country="United States", savings_currencies=[]))
