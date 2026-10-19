#!/usr/bin/env python3
"""Render top/bottom PNGs (3D raytrace) and layout-view SVGs (2D, PCB
editor look: viewed side's copper frontmost, other layers behind) of the
board for visual review, plus out/index.html, the dashboard that
`proj up bluebuzz` serves. Lifted from simple_earring/scripts/render.py."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "bluebuzz.kicad_pcb"

def _copper_layers():
    """Copper layer names F->B for the configured stackup (4 or 6)."""
    from circuit import load_design
    n = load_design()["board"]["layers"]
    return ["F.Cu"] + [f"In{i}.Cu" for i in range(1, n - 1)] + ["B.Cu"]


_COPPER = _copper_layers()

# layers listed back-to-front; kicad-cli draws them in list order
LAYOUT_VIEWS = {
    "top": (",".join(_COPPER[::-1] + ["F.Silkscreen", "Edge.Cuts"]), False),
    "bottom": (",".join(_COPPER + ["B.Silkscreen", "Edge.Cuts"]), True),
}

# individual copper layers (all drawn from the top, unmirrored, so the
# transparent PNGs stack in register in the grid and the layer viewer)
LAYER_STACK = [(ly, ly.split(".")[0].lower()) for ly in _COPPER]

INDEX_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>bluebuzz renders</title>
<style>
  body { background:#1a1a1e; color:#ddd; font-family:sans-serif; margin:1rem; }
  h1 { font-size:1.1rem; font-weight:600; }
  h2 { font-size:.95rem; font-weight:600; color:#bbb; margin:1.4rem 0 .5rem; }
  .row { display:flex; flex-wrap:wrap; gap:1rem; }
  figure { margin:0; }
  figcaption { text-align:center; padding:.3rem; color:#aaa; font-size:.85rem; }
  img { max-width:min(46vw,900px); height:auto; border-radius:8px; background:#26262c; }
  #ts { color:#777; font-size:.8rem; }
  #viewer { display:flex; gap:1rem; align-items:flex-start; }
  #panel { padding:12px; min-width:210px; background:#26262e; border-radius:8px; }
  .lay { display:flex; align-items:center; gap:8px; padding:5px 2px; }
  .lay .sw { width:14px; height:14px; border-radius:3px; }
  #stack { position:relative; }
  #stack img { position:absolute; inset:0; width:100%%; height:100%%;
               max-width:none; pointer-events:none; border-radius:0;
               background:none; }
  #stack img.base { position:relative; display:block; width:auto; height:auto;
                    max-width:min(66vw,1100px); background:#fff;
                    border-radius:8px; }
  label { user-select:none; }
  input[type=range] { width:100%%; }
  .hint { color:#888; font-size:.75rem; margin-top:10px; }
</style></head><body>
<h1>bluebuzz — latest outputs <span id="ts"></span>
  &nbsp;·&nbsp; <a href="../" style="color:#fc6;font-size:.9rem">project status</a></h1>
<div class="row">
  <figure><img class="rf" id="ptop" src="render_place_top.png"><figcaption>placement preview front (unrouted, updates right after place)</figcaption></figure>
  <figure><img class="rf" id="pbot" src="render_place_bottom.png"><figcaption>placement preview back (unrouted)</figcaption></figure>
</div>
<div class="row">
  <figure><img class="rf" id="rtop" src="render_top.png"><figcaption>front, routed</figcaption></figure>
  <figure><img class="rf" id="rbot" src="render_bottom.png"><figcaption>back, routed</figcaption></figure>
</div>
<div class="row">
  <figure><img class="rf" id="laytop" src="layout_top.png"><figcaption>layout top (F.Cu over In1/In2/B.Cu)</figcaption></figure>
  <figure><img class="rf" id="laybot" src="layout_bottom.png"><figcaption>layout bottom, mirrored (B.Cu over In2/In1/F.Cu)</figcaption></figure>
</div>
<h2>Schematic</h2>
<div class="row">
  <div style="font-size:.9rem">
    <a href="bluebuzz.svg" style="color:#8bf">open schematic (SVG, zoomable)</a>
    &nbsp;·&nbsp;
    <a href="bluebuzz-schematic.pdf" style="color:#8bf">PDF</a>
    <div style="color:#888;margin-top:.3rem">
      generated from scripts/circuit.py and wired by gen_schematic.py
    </div>
  </div>
</div>
<h2>Copper layers</h2>
<div class="row">
  <figure><img class="rf" id="grid" src="layout_layers.png" style="max-width:min(92vw,1400px)"><figcaption>individual copper layers (top view)</figcaption></figure>
</div>
<h2>Layer stack viewer</h2>
<div id="viewer">
  <div id="panel">
    <div id="layers"></div>
    <div style="margin-top:12px">others opacity
      <input type="range" id="dim" min="0" max="100" value="25">
    </div>
    <div class="hint">radio = selected layer (always opaque)<br>
         checkbox = layer visible at all<br>
         slider = opacity of visible, unselected layers<br>
         all layers drawn from the top, unmirrored</div>
  </div>
  <div id="stack">
    <img class="base rf" id="img_edge" src="layer_edge.png">
%s
  </div>
</div>
<script>
const LAYERS = %s;
const dim = document.getElementById('dim');
const box = document.getElementById('layers');
const state = {sel: LAYERS[0][1], vis: Object.fromEntries(
    LAYERS.map(l => [l[1], true]))};
for (const [name, slug, color] of LAYERS) {
  const row = document.createElement('div');
  row.className = 'lay';
  row.innerHTML = `<input type="radio" name="sel" id="r_${slug}">` +
    `<input type="checkbox" id="v_${slug}" checked>` +
    `<span class="sw" style="background:${color}"></span>` +
    `<label for="r_${slug}">${name}</label>`;
  box.appendChild(row);
  row.querySelector(`#r_${slug}`).onchange = () => { state.sel = slug; apply(); };
  row.querySelector(`#v_${slug}`).onchange = e => {
    state.vis[slug] = e.target.checked; apply(); };
}
document.getElementById('r_' + state.sel).checked = true;
dim.oninput = apply;
function apply() {
  for (const [, slug] of LAYERS) {
    const img = document.getElementById('img_' + slug);
    img.style.display = state.vis[slug] ? '' : 'none';
    img.style.opacity = (slug === state.sel) ? 1 : dim.value / 100;
  }
}
apply();
function refresh() {
  const t = Date.now();
  for (const img of document.querySelectorAll('img.rf')) {
    img.src = img.src.split('?')[0] + '?' + t;
  }
  document.getElementById('ts').textContent =
    '(auto-refresh ' + new Date().toLocaleTimeString() + ')';
}
setInterval(refresh, 15000);
refresh();
</script>
<h2>Interactive 3D board</h2>
<div id="three" style="width:min(94vw,1400px);height:640px;background:#222228;
     border-radius:8px;overflow:hidden"></div>
<div class="hint" style="color:#888;font-size:.75rem;margin-top:6px">
  drag = orbit, wheel = zoom, right-drag = pan (board.glb regenerates each build)</div>
<script type="importmap">
{"imports": {"three": "./vendor/three.module.js"}}
</script>
<script type="module">
import * as THREE from 'three';
import { TrackballControls } from './vendor/TrackballControls.js';
import { GLTFLoader } from './vendor/GLTFLoader.js';
const el = document.getElementById('three');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x222228);
const cam = new THREE.PerspectiveCamera(
    40, el.clientWidth / el.clientHeight, 0.001, 10);
const renderer = new THREE.WebGLRenderer({antialias: true});
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(el.clientWidth, el.clientHeight);
el.appendChild(renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff, 1.0));
const d1 = new THREE.DirectionalLight(0xffffff, 2.2);
d1.position.set(1, 1, 2); scene.add(d1);
const d2 = new THREE.DirectionalLight(0xffffff, 1.0);
d2.position.set(-1, -0.5, -2); scene.add(d2);
// TrackballControls (not Orbit): no pole clamp, so the board can be
// tumbled continuously end over end
const controls = new TrackballControls(cam, renderer.domElement);
controls.rotateSpeed = 4.0;
controls.zoomSpeed = 1.4;
controls.panSpeed = 0.6;
controls.dynamicDampingFactor = 0.12;
new GLTFLoader().load('board.glb?' + Date.now(), g => {
  const obj = g.scene;
  const box = new THREE.Box3().setFromObject(obj);
  obj.position.sub(box.getCenter(new THREE.Vector3()));
  scene.add(obj);
  const r = box.getSize(new THREE.Vector3()).length();
  cam.position.set(0, r * 0.55, r * 0.8);
  cam.near = r / 1000; cam.far = r * 20;
  cam.updateProjectionMatrix();
  controls.update();
});
(function loop() {
  requestAnimationFrame(loop);
  controls.update();
  renderer.render(scene, cam);
})();
window.addEventListener('resize', () => {
  cam.aspect = el.clientWidth / el.clientHeight;
  cam.updateProjectionMatrix();
  renderer.setSize(el.clientWidth, el.clientHeight);
  controls.handleResize();
});
</script>
</body></html>
"""


def main():
    ok = True
    # --placement: quick post-place preview (no routing yet) -> separate
    # files so the routed renders aren't clobbered mid-build
    placement = "--placement" in sys.argv
    prefix = "render_place_" if placement else "render_"
    for side in ("top", "bottom"):
        out = ROOT / "out" / f"{prefix}{side}.png"
        r = subprocess.run(
            ["kicad-cli", "pcb", "render", "--side", side,
             "--quality", "high", "--zoom", "0.9",
             "-o", str(out), str(PCB)],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            ok = False
        else:
            print(f"wrote {out}")
    if placement:
        sys.exit(0 if ok else 1)
    # layout views: kicad-cli only exports vector formats for layer views,
    # so export SVG then rasterize to a PNG matching the 3D render size
    # (board centered on white); the intermediate SVG is removed
    try:
        from PIL import Image
        size = Image.open(ROOT / "out" / f"{prefix}top.png").size
    except Exception:
        size = (1568, 872)
    for side, (layers, mirror) in LAYOUT_VIEWS.items():
        svg = ROOT / "out" / f"layout_{side}.svg"
        cmd = ["kicad-cli", "pcb", "export", "svg", "--mode-single",
               "--layers", layers, "--page-size-mode", "2",
               "--exclude-drawing-sheet", "-o", str(svg), str(PCB)]
        if mirror:
            cmd.insert(cmd.index("-o"), "--mirror")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            ok = False
            continue
        out = ROOT / "out" / f"layout_{side}.png"
        wh = f"{size[0]}x{size[1]}"
        r = subprocess.run(
            ["magick", "-density", "600", "-background", "white",
             str(svg), "-resize", wh, "-gravity", "center",
             "-extent", wh, "-alpha", "remove", "-alpha", "off",
             "-depth", "8", str(out)],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            ok = False
        else:
            svg.unlink()
            print(f"wrote {out}")

    # ---- individual copper layers: transparent PNGs on the shared canvas
    # (page-size-mode 2 crops every export to the board bbox, so all
    # layers land in register), then a labeled 2x2 grid + stack viewer
    wh = f"{size[0]}x{size[1]}"
    for name, slug in LAYER_STACK + [("Edge.Cuts", "edge")]:
        svg = ROOT / "out" / f"layer_{slug}.svg"
        r = subprocess.run(
            ["kicad-cli", "pcb", "export", "svg", "--mode-single",
             "--layers", name, "--page-size-mode", "2",
             "--exclude-drawing-sheet", "-o", str(svg), str(PCB)],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            ok = False
            continue
        out = ROOT / "out" / f"layer_{slug}.png"
        r = subprocess.run(
            ["magick", "-density", "600", "-background", "none",
             str(svg), "-resize", wh, "-gravity", "center",
             "-extent", wh, f"png32:{out}"],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            ok = False
        else:
            svg.unlink()
            print(f"wrote {out}")

    try:
        from PIL import Image, ImageDraw
        edge = Image.open(ROOT / "out" / "layer_edge.png").convert("RGBA")
        tw, th = size[0] // 2, size[1] // 2
        rows = (len(LAYER_STACK) + 1) // 2
        grid = Image.new("RGB", (tw * 2, th * rows), "white")
        draw = ImageDraw.Draw(grid)
        try:
            from PIL import ImageFont
            font = ImageFont.load_default(size=24)
        except Exception:
            font = None
        for i, (name, slug) in enumerate(LAYER_STACK):
            tile = Image.new("RGBA", size, "white")
            tile.alpha_composite(edge)
            tile.alpha_composite(
                Image.open(ROOT / "out" / f"layer_{slug}.png").convert("RGBA"))
            tile = tile.resize((tw, th), Image.LANCZOS).convert("RGB")
            x, y = (i % 2) * tw, (i // 2) * th
            grid.paste(tile, (x, y))
            draw.text((x + 10, y + 8), name, fill="#222", font=font)
        gout = ROOT / "out" / "layout_layers.png"
        grid.save(gout)
        print(f"wrote {gout}")
    except Exception as e:
        print(f"layer grid failed: {e}")
        ok = False

    # dashboard: everything on one page (served from out/, e.g. :8618),\n    # auto-refreshing, with the copper-stack viewer embedded
    # swatches: sampled from each exported layer PNG so they always match
    # kicad-cli's theme, whatever the layer count
    def swatch(slug):
        try:
            from PIL import Image
            im = Image.open(ROOT / "out" / f"layer_{slug}.png")
            im = im.convert("RGBA").resize((128, 128))
            counts = {}
            for r, g, b, a in im.getdata():
                if a > 200:
                    counts[(r, g, b)] = counts.get((r, g, b), 0) + 1
            if counts:
                r, g, b = max(counts, key=counts.get)
                return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            pass
        return "#888888"
    imgs = "\n".join(
        f'    <img class="rf" id="img_{slug}" src="layer_{slug}.png">'
        for _, slug in LAYER_STACK)
    layers_js = "[" + ", ".join(
        f'["{name}", "{slug}", "{swatch(slug)}"]'
        for name, slug in LAYER_STACK) + "]"
    # interactive 3D: board GLB + vendored three.js for the page viewer
    r = subprocess.run(
        ["kicad-cli", "pcb", "export", "glb", "-f", "--subst-models",
         "--include-tracks", "--include-pads", "--include-zones",
         "--include-silkscreen", "--include-soldermask",
         "-o", str(ROOT / "out" / "board.glb"), str(PCB)],
        capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        ok = False
    else:
        print(f"wrote {ROOT / 'out' / 'board.glb'}")
    import shutil
    shutil.copytree(ROOT / "web" / "vendor", ROOT / "out" / "vendor",
                    dirs_exist_ok=True)

    index = ROOT / "out" / "index.html"
    index.write_text(INDEX_HTML % (imgs, layers_js))
    print(f"wrote {index}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
