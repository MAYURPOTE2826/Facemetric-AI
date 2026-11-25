"""Synthetic head scenes for the hairline engine. A scene is a drawn head (hair above a chosen hairline curve, skin below, brows
painted as hair-class blobs like a real segmenter would) with a category mask built from the same drawing and a landmark array
carrying only the points the engine uses. Synthetic scenes prove software behaviour; they say NOTHING about real-photo accuracy."""
import cv2
import numpy as np

BG, HAIR, BODY_SKIN, FACE_SKIN, CLOTHES, OTHER = range(6)
SKIN = (110, 150, 200)       # BGR
DARK = (30, 30, 35)
LIGHT = (140, 170, 205)      # blond: close to the skin colour
W, H, BZ = 700, 900, 300
CX = 350


def smooth(x, a, b):
    t = np.clip((abs(x) - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def straight(u):
    return 0.5


def rounded(u):
    return 0.5 - 0.5 * u * u


def mature(bump):
    return lambda u: 0.5 + bump * smooth(u, 0.15, 0.30)


def asym(left, right):
    return lambda u: 0.5 + (left if u > 0 else right) * smooth(u, 0.15, 0.30)


def landmarks(oy=400):
    p = np.zeros((478, 3), dtype=np.float64)

    def put(i, x, y):
        p[i] = (x, y, 0)
    put(234, CX - 150, oy + 120); put(454, CX + 150, oy + 120)
    put(33, CX - 100, oy + 50); put(263, CX + 100, oy + 50)
    put(9, CX, oy)
    put(70, CX - 95, oy - 25); put(105, CX - 50, oy - 30); put(334, CX + 50, oy - 30); put(300, CX + 95, oy - 25)
    put(1, CX, oy + 100); put(2, CX, oy + 140); put(152, CX, oy + 280); put(10, CX, oy - 140)
    put(468, CX - 50, oy + 50); put(473, CX + 50, oy + 50)
    put(469, CX - 63, oy + 50); put(471, CX - 37, oy + 50); put(474, CX + 37, oy + 50); put(476, CX + 63, oy + 50)
    put(133, CX - 30, oy + 50); put(362, CX + 30, oy + 50)
    return p


def scene(hairline=straight, hair=DARK, skin=SKIN, thickness=0.37, fringe=False, wet=False, light_gain=0, jagged=0.0,
          crop_top=0, scale=1.0, seed=3, oy=400, dx=0.0, dy=0.0, nose_dx=0.0):
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), (200, 195, 190), np.uint8)
    cat = np.zeros((H, W), np.uint8)
    ys, xs = np.mgrid[0:H, 0:W]
    head = ((xs - CX) / 190.0) ** 2 + ((ys - oy) / 420.0) ** 2 <= 1.0
    hl_y = np.zeros(W)
    for x in range(W):
        u = (x - CX) / BZ
        v = 0.08 if fringe else hairline(float(np.clip(u, -0.5, 0.5)))
        if jagged:
            v += jagged * np.sin(x * 0.9) * (1 if (x // 5) % 2 else -1) * rng.uniform(0.6, 1.0)
        hl_y[x] = oy - BZ * v
    hair_top = hl_y - BZ * thickness
    below = ys >= hl_y[None, :]
    hair_m = head & ~below & (ys >= hair_top[None, :])
    bg_in_head = head & ~below & (ys < hair_top[None, :])
    skin_m = head & below & (ys <= oy + 300)
    img[skin_m] = skin
    cat[skin_m] = FACE_SKIN
    img[hair_m] = hair
    cat[hair_m] = HAIR
    img[bg_in_head] = (200, 195, 190)
    cat[bg_in_head] = BG
    for cxb in (CX - 70, CX + 70):  # brows: dark, labelled HAIR (as a real segmenter often does)
        cv2.ellipse(img, (cxb, oy - 25), (35, 9), 0, 0, 360, hair, -1)
        cv2.ellipse(cat, (cxb, oy - 25), (35, 9), 0, 0, 360, HAIR, -1)
    if wet:
        seeds = (rng.random((H, W)) < 0.004).astype(np.uint8)
        streaks = cv2.dilate(seeds, np.ones((3, 9), np.uint8)).astype(bool) & hair_m
        img[streaks] = (250, 250, 250)
    img = cv2.GaussianBlur(img, (0, 0), 1.2).astype(np.float32)
    img += rng.normal(0, 2.5, img.shape)
    if light_gain:
        img = img * light_gain if abs(light_gain) < 3 else img + light_gain
    img = np.clip(img, 0, 255).astype(np.uint8)
    pts = landmarks(oy=oy)
    pts[1, 0] += nose_dx  # head turned: nose tip no longer midway between the cheekbones
    if crop_top:
        img, cat = img[crop_top:], cat[crop_top:]
        pts[:, 1] -= crop_top
    if scale != 1.0 or dx or dy:
        M = np.float32([[scale, 0, dx], [0, scale, dy]])
        size = (int(W * scale + abs(dx) + 5), int(img.shape[0] * scale + abs(dy) + 5))
        img = cv2.warpAffine(img, M, size, flags=cv2.INTER_AREA, borderValue=(200, 195, 190))
        cat = cv2.warpAffine(cat, M, size, flags=cv2.INTER_NEAREST, borderValue=0)
        pts[:, :2] = pts[:, :2] * scale + (dx, dy)
    return img, cat, pts
