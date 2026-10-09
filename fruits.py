"""
fruits.py — 20 fruit cards for Guess Who? (Fruits Edition)

Each entry has:
    name   – display name
    image  – path to the card image (images/fruits/ folder)
    shape  – drawing hint (kept for structural parity with desserts.py;
             not currently read by the renderer, which uses uploaded photos)
    color  – primary RGB fill colour
    accent – secondary / highlight RGB colour
"""

FRUITS = [
    {
        "name":   "Apple",
        "image":  "images/fruits/apple.jpg",
        "shape":  "round",
        "color":  (200,  40,  40),
        "accent": ( 90, 150,  50),
    },
    {
        "name":   "Banana",
        "image":  "images/fruits/banana.jpg",
        "shape":  "long",
        "color":  (240, 210,  60),
        "accent": (160, 130,  30),
    },
    {
        "name":   "Orange",
        "image":  "images/fruits/orange.jpg",
        "shape":  "round",
        "color":  (240, 140,  30),
        "accent": ( 90, 140,  50),
    },
    {
        "name":   "Strawberry",
        "image":  "images/fruits/strawberry.jpg",
        "shape":  "round",
        "color":  (220,  30,  60),
        "accent": ( 80, 160,  60),
    },
    {
        "name":   "Grapes",
        "image":  "images/fruits/grapes.jpg",
        "shape":  "round",
        "color":  (110,  60, 160),
        "accent": ( 80, 150,  60),
    },
    {
        "name":   "Watermelon",
        "image":  "images/fruits/watermelon.jpg",
        "shape":  "round",
        "color":  ( 60, 160,  80),
        "accent": (220,  60,  70),
    },
    {
        "name":   "Pineapple",
        "image":  "images/fruits/pineapple.jpg",
        "shape":  "long",
        "color":  (230, 190,  40),
        "accent": ( 70, 130,  50),
    },
    {
        "name":   "Mango",
        "image":  "images/fruits/mango.jpg",
        "shape":  "round",
        "color":  (240, 160,  40),
        "accent": (200,  70,  40),
    },
    {
        "name":   "Peach",
        "image":  "images/fruits/peach.jpg",
        "shape":  "round",
        "color":  (250, 180, 140),
        "accent": (220, 110,  80),
    },
    {
        "name":   "Pear",
        "image":  "images/fruits/pear.jpg",
        "shape":  "round",
        "color":  (200, 210,  90),
        "accent": (130, 150,  50),
    },
    {
        "name":   "Cherry",
        "image":  "images/fruits/cherry.jpg",
        "shape":  "round",
        "color":  (180,  20,  40),
        "accent": ( 70, 140,  50),
    },
    {
        "name":   "Kiwi",
        "image":  "images/fruits/kiwi.jpg",
        "shape":  "round",
        "color":  (140, 100,  40),
        "accent": (150, 190,  60),
    },
    {
        "name":   "Lemon",
        "image":  "images/fruits/lemon.jpg",
        "shape":  "round",
        "color":  (250, 230,  60),
        "accent": (180, 160,  30),
    },
    {
        "name":   "Blueberry",
        "image":  "images/fruits/blueberry.jpg",
        "shape":  "round",
        "color":  ( 60,  70, 160),
        "accent": (150, 160, 210),
    },
    {
        "name":   "Raspberry",
        "image":  "images/fruits/raspberry.jpg",
        "shape":  "round",
        "color":  (200,  40,  90),
        "accent": ( 80, 150,  60),
    },
    {
        "name":   "Lime",
        "image":  "images/fruits/lime.jpg",
        "shape":  "round",
        "color":  (170, 210,  60),
        "accent": (240, 245, 220),
    },
    {
        "name":   "Papaya",
        "image":  "images/fruits/papaya.jpg",
        "shape":  "long",
        "color":  (240, 140,  60),
        "accent": (230, 100,  60),
    },
    {
        "name":   "Pomegranate",
        "image":  "images/fruits/pomegranate.jpg",
        "shape":  "round",
        "color":  (170,  30,  40),
        "accent": (230, 170,  60),
    },
    {
        "name":   "Avocado",
        "image":  "images/fruits/avocado.jpg",
        "shape":  "round",
        "color":  (110, 140,  60),
        "accent": ( 90,  60,  40),
    },
    {
        "name":   "Dragon Fruit",
        "image":  "images/fruits/dragon_fruit.jpg",
        "shape":  "long",
        "color":  (220,  40, 110),
        "accent": (245, 245, 235),
    },
]