"""Write the toy dataset: coloured shapes to try CARA without downloading anything (`quickstart.sh --toy`).

Each query is a shape in a colour; a tenth of its candidates match both, the rest are random.
The embeddings are the downscaled pixels (encoder `pixels`), so the toy study needs no model.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

SHAPES = ("ellipse", "rectangle", "triangle")
CARA_YAML = """\
name: Toy shapes
encoder: pixels
labels:
  - {name: Relevant, short: "✓", grade: 1, colour: "#2ecc71"}
  - {name: Not Relevant, short: "✗", grade: 0, colour: "#e74c3c"}
  - {name: Unsure, short: "?", grade: null, colour: "#f1c40f"}
pool: {source: file, k: null}
grouping: {method: agglomerative, max_size: 16}
demo: true
"""


def draw(shape: str, colour: tuple[int, int, int], rng: np.random.Generator) -> Image.Image:
    """Return a 160 × 120 image with one filled shape at a random position."""
    img = Image.new("RGB", (160, 120), "white")
    x, y = rng.integers(10, 50, size=2)
    box = (int(x), int(y), int(x) + 90, int(y) + 60)
    draw = ImageDraw.Draw(img)
    if shape == "triangle":
        draw.polygon([(box[0], box[3]), (box[2], box[3]), ((box[0] + box[2]) // 2, box[1])], fill=colour)
    else:
        getattr(draw, shape)(box, fill=colour)
    return img


def main() -> None:
    """Write the images, `embeddings.npz`, `queries.jsonl`, `cara.yaml` and `dataset.yaml` to the folder."""
    parser = argparse.ArgumentParser(description="Write a synthetic dataset to smoke-test the app.")
    parser.add_argument("out", type=Path)
    parser.add_argument("--queries", type=int, default=3)
    parser.add_argument("--candidates", type=int, default=120)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    (args.out / "images").mkdir(parents=True, exist_ok=True)
    palette = [tuple(int(v) for v in rng.integers(0, 256, size=3)) for _ in range(8)]
    images: dict[str, Image.Image] = {}
    lines = []
    for q in range(args.queries):
        shape, colour = SHAPES[q % len(SHAPES)], palette[q % len(palette)]
        images[f"images/q{q}.png"] = draw(shape, colour, rng)
        candidates = []
        for c in range(args.candidates):
            is_match = c < args.candidates // 10
            cand_shape = shape if is_match else str(rng.choice(SHAPES))
            cand_colour = colour if is_match else palette[int(rng.integers(len(palette)))]
            image = f"images/q{q}_c{c}.png"
            images[image] = draw(cand_shape, cand_colour, rng)
            candidates.append({"doc_id": f"q{q}_c{c}", "image": image})
        rng.shuffle(candidates)
        lines.append(json.dumps({"query_id": f"q{q}", "image": f"images/q{q}.png", "candidates": candidates}))

    for image, img in images.items():
        img.save(args.out / image)
    ids = list(images)
    emb_nd = np.stack([np.asarray(images[i].resize((16, 12)), dtype=np.float32).ravel() / 255 for i in ids])
    np.savez(args.out / "embeddings.npz", ids=np.array(ids), emb_nd=emb_nd - emb_nd.mean(axis=0))
    (args.out / "queries.jsonl").write_text("\n".join(lines) + "\n")
    (args.out / "cara.yaml").write_text(CARA_YAML)
    (args.out / "dataset.yaml").write_text("name: Toy shapes\ndescription: Synthetic shapes to try CARA.\n")


if __name__ == "__main__":
    main()
