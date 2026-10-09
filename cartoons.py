"""
cartoons.py — 20 cartoon character cards for Guess Who? (Cartoons Edition)

Each entry has:
    name   – display name
    image  – path to the card image (images/cartoons/ folder)
    shape  – drawing hint (kept for structural parity with desserts.py;
             not currently read by the renderer, which uses uploaded photos)
    color  – primary RGB fill colour
    accent – secondary / highlight RGB colour

Note: these are widely recognised characters from a mix of studios/eras,
picked for variety the same way desserts.py mixes cuisines. The actual
card art comes from the uploaded photos in images/cartoons/ — missing
images just fall back to the game's built-in placeholder card art.
"""

CARTOONS = [
    {
        "name":   "Mickey Mouse",
        "image":  "images/cartoons/mickey_mouse.jpg",
        "shape":  "round",
        "color":  ( 30,  30,  30),
        "accent": (255, 199,   4),
    },
    {
        "name":   "SpongeBob SquarePants",
        "image":  "images/cartoons/spongebob.jpg",
        "shape":  "rect",
        "color":  (253, 240,   1),
        "accent": (200,  50,  50),
    },
    {
        "name":   "Bugs Bunny",
        "image":  "images/cartoons/bugs_bunny.jpg",
        "shape":  "round",
        "color":  (180, 180, 185),
        "accent": (245, 245, 245),
    },
    {
        "name":   "Homer Simpson",
        "image":  "images/cartoons/homer_simpson.jpg",
        "shape":  "round",
        "color":  (252, 212,  25),
        "accent": (100, 171, 217),
    },
    {
        "name":   "Scooby-Doo",
        "image":  "images/cartoons/scooby_doo.jpg",
        "shape":  "round",
        "color":  (185, 121,  15),
        "accent": ( 55, 170, 180),
    },
    {
        "name":   "Tom",
        "image":  "images/cartoons/tom.jpg",
        "shape":  "round",
        "color":  ( 70,  85, 106),
        "accent": (218, 203, 208),
    },
    {
        "name":   "Jerry",
        "image":  "images/cartoons/jerry.jpg",
        "shape":  "round",
        "color":  (197, 131,  55),
        "accent": (250, 239, 194),
    },
    {
        "name":   "Donald Duck",
        "image":  "images/cartoons/donald_duck.jpg",
        "shape":  "round",
        "color":  (245, 245, 245),
        "accent": (255, 185,   2),
    },
    {
        "name":   "Daffy Duck",
        "image":  "images/cartoons/daffy_duck.jpg",
        "shape":  "round",
        "color":  ( 30,  30,  30),
        "accent": (246, 167,   2),
    },
    {
        "name":   "Pikachu",
        "image":  "images/cartoons/pikachu.jpg",
        "shape":  "round",
        "color":  (252, 220,  39),
        "accent": (200,  60,  50),
    },
    {
        "name":   "Fred Flintstone",
        "image":  "images/cartoons/fred_flintstone.jpg",
        "shape":  "round",
        "color":  (239, 126,  24),
        "accent": ( 60, 110, 190),
    },
    {
        "name":   "Garfield",
        "image":  "images/cartoons/garfield.jpg",
        "shape":  "round",
        "color":  (254, 164,   8),
        "accent": ( 60,  50,  40),
    },
    {
        "name":   "Winnie the Pooh",
        "image":  "images/cartoons/winnie_the_pooh.jpg",
        "shape":  "round",
        "color":  (230, 170,  40),
        "accent": (200,  50,  50),
    },
    {
        "name":   "Bart Simpson",
        "image":  "images/cartoons/bart_simpson.jpg",
        "shape":  "round",
        "color":  (254, 212,  30),
        "accent": (242,  78,  43),
    },
    {
        "name":   "Ben Tennyson",
        "image":  "images/cartoons/ben_tennyson.jpg",
        "shape":  "round",
        "color":  ( 85, 100,  35),
        "accent": (245, 245, 245),
    },
    {
        "name":   "Courage",
        "image":  "images/cartoons/courage.jpg",
        "shape":  "round",
        "color":  (249, 158, 237),
        "accent": ( 80,  30,  20),
    },
    {
        "name":   "Shaggy Rogers",
        "image":  "images/cartoons/shaggy.jpg",
        "shape":  "round",
        "color":  (177, 187,  28),
        "accent": (180,  83,  64),
    },
    {
        "name":   "Phineas Flynn",
        "image":  "images/cartoons/phineas.jpg",
        "shape":  "round",
        "color":  (240, 160,   1),
        "accent": (230,  70,  40),
    },
    {
        "name":   "Blossom",
        "image":  "images/cartoons/blossom.jpg",
        "shape":  "round",
        "color":  (243,  89,  63),
        "accent": (240, 140, 170),
    },
    {
        "name":   "Dexter",
        "image":  "images/cartoons/dexter.jpg",
        "shape":  "round",
        "color":  (245, 245, 245),
        "accent": (243, 157,  36),
    },
]