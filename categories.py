"""
categories.py — central registry of playable card categories.

Each category maps to its card list (see desserts.py / fruits.py /
cartoons.py for the per-card format: name, image, shape, color, accent).

This is the single place game_engine.py and main.py go to answer
"what cards am I playing with, and what do I call this category on screen".
Bot-mode trait data (used for the bot's yes/no answers) lives separately in
bot.py, keyed by the same category key — see bot.CATEGORY_TRAITS.
"""

from desserts import DESSERTS
from fruits   import FRUITS
from cartoons import CARTOONS

DEFAULT_CATEGORY = "desserts"

CATEGORIES = {
    "desserts": {
        "label":    "Desserts",
        "singular": "dessert",
        "cards":    DESSERTS,
    },
    "fruits": {
        "label":    "Fruits",
        "singular": "fruit",
        "cards":    FRUITS,
    },
    "cartoons": {
        "label":    "Cartoon Characters",
        "singular": "cartoon character",
        "cards":    CARTOONS,
    },
}

# Stable, ordered list of (key, label) for building UI pickers
CATEGORY_ORDER = ["desserts", "fruits", "cartoons"]


def get_cards(category_key):
    """Return the card list for a category key, falling back to desserts."""
    return CATEGORIES.get(category_key, CATEGORIES[DEFAULT_CATEGORY])["cards"]


def get_label(category_key):
    """Return the display label, e.g. 'Cartoon Characters'."""
    return CATEGORIES.get(category_key, CATEGORIES[DEFAULT_CATEGORY])["label"]


def get_singular(category_key):
    """Return the singular form used in prompts, e.g. 'cartoon character'."""
    return CATEGORIES.get(category_key, CATEGORIES[DEFAULT_CATEGORY])["singular"]


def is_valid_category(category_key):
    return category_key in CATEGORIES