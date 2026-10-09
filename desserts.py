"""
desserts.py — 20 dessert cards for Guess Who? (Dessert Edition)

Each entry has:
    name   – display name
    image  – path to the card image (images/ folder)
    shape  – drawing hint used by DessertCard._draw_dessert_art:
             "round" | "cone" | "rect" | "layered"
    color  – primary RGB fill colour
    accent – secondary / highlight RGB colour
"""

DESSERTS = [
    {
        "name":   "Apple Pie",
        "image":  "images/desserts/apple_pie.png",
        "shape":  "rect",
        "color":  (210, 130,  50),
        "accent": (240, 190, 100),
    },
    {
        "name":   "Brittle",
        "image":  "images/desserts/brittle.png",
        "shape":  "rect",
        "color":  (190, 120,  40),
        "accent": (230, 170,  60),
    },
    {
        "name":   "Brownies",
        "image":  "images/desserts/brownies.png",
        "shape":  "rect",
        "color":  ( 80,  45,  20),
        "accent": ( 50,  25,  10),
    },
    {
        "name":   "Cannoli",
        "image":  "images/desserts/cannoli.png",
        "shape":  "rect",
        "color":  (240, 210, 170),
        "accent": (200, 100,  60),
    },
    {
        "name":   "Chocolate Cake",
        "image":  "images/desserts/chocolate_cake.png",
        "shape":  "layered",
        "color":  ( 60,  30,  10),
        "accent": (180,  80,  40),
    },
    {
        "name":   "Churros",
        "image":  "images/desserts/churros.png",
        "shape":  "rect",
        "color":  (210, 150,  60),
        "accent": (170, 100,  30),
    },
    {
        "name":   "Cookies",
        "image":  "images/desserts/cookies.png",
        "shape":  "round",
        "color":  (210, 160,  80),
        "accent": (120,  70,  20),
    },
    {
        "name":   "Croissant",
        "image":  "images/desserts/croissant.png",
        "shape":  "rect",
        "color":  (220, 160,  60),
        "accent": (180, 120,  40),
    },
    {
        "name":   "Cupcake",
        "image":  "images/desserts/cupcake.png",
        "shape":  "round",
        "color":  (240, 180, 200),
        "accent": (255, 240, 220),
    },
    {
        "name":   "Donut",
        "image":  "images/desserts/donut.png",
        "shape":  "round",
        "color":  (230, 170, 100),
        "accent": (255, 100, 140),
    },
    {
        "name":   "Ice Cream",
        "image":  "images/desserts/ice_cream.png",
        "shape":  "cone",
        "color":  (255, 230, 200),
        "accent": (210, 160,  80),
    },
    {
        "name":   "Jell-O",
        "image":  "images/desserts/jello.png",
        "shape":  "rect",
        "color":  (200,  80, 200),
        "accent": (240, 130, 240),
    },
    {
        "name":   "Macarons",
        "image":  "images/desserts/macarons.png",
        "shape":  "round",
        "color":  (255, 170, 200),
        "accent": (220, 130, 170),
    },
    {
        "name":   "Mochi",
        "image":  "images/desserts/mochi.png",
        "shape":  "round",
        "color":  (255, 220, 240),
        "accent": (210, 180, 220),
    },
    {
        "name":   "Mooncake",
        "image":  "images/desserts/mooncake.png",
        "shape":  "round",
        "color":  (200, 140,  60),
        "accent": (160, 100,  30),
    },
    {
        "name":   "Muffin",
        "image":  "images/desserts/muffin.png",
        "shape":  "round",
        "color":  (180, 130,  70),
        "accent": (230, 170,  90),
    },
    {
        "name":   "Pudding",
        "image":  "images/desserts/pudding.png",
        "shape":  "round",
        "color":  (240, 210, 150),
        "accent": (210, 160,  80),
    },
    {
        "name":   "Tarts",
        "image":  "images/desserts/tarts.png",
        "shape":  "round",
        "color":  (220, 170,  80),
        "accent": (180, 100,  50),
    },
    {
        "name":   "Trifle",
        "image":  "images/desserts/trifle.png",
        "shape":  "layered",
        "color":  (255, 230, 220),
        "accent": (200,  80,  80),
    },
    {
        "name":   "Waffle",
        "image":  "images/desserts/waffle.png",
        "shape":  "rect",
        "color":  (220, 170,  80),
        "accent": (180, 120,  40),
    },
]