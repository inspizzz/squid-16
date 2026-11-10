#!/usr/bin/env python3
"""Route hardware/limpet16.kicad_pcb.

A small self-contained grid router (A* on a 0.0625 mm grid, with rip-up and
re-route) so the board can be rebuilt from design.py with nothing but KiCad
installed. It is deliberately conservative: every track and via keeps more
than the design-rule clearance, and KiCad's own DRC is the judge of the
result (see scripts/check.sh).

Layers: F.Cu, In2.Cu and B.Cu carry signals, In1.Cu is a solid ground plane.
Ground pads get a via into the plane or join a ground track that has one.

    python3 scripts/gen_pcb.py && python3 scripts/route.py
"""
import heapq
import math
import os
import sys

import numpy as np
import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design as d
import gen_pcb

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PCB = os.path.join(HW, "limpet16.kicad_pcb")
# NOTE: the result is not the same on every rebuild. Each board that
# gen_pcb.py writes routes a little differently (the cause has not been pinned
# down; parts are now read in reference order below, which may or may not be
# all of it), and not every attempt ends with everything connected: of three
# full attempts on the committed design, one did. The committed .kicad_pcb is
# that one. If this script reports unrouted connections, run gen_pcb.py and
# this script again, or nudge a part in design.py.
OUT_PCB = os.environ.get("LIMPET_ROUTE_OUT", PCB)   # where to save (default: in place)

G = 0.0625                      # grid pitch, mm
HALF = d.BOARD_DIAMETER / 2
N = int(round(2 * (HALF + 0.5) / G)) + 1
OFF = (N - 1) / 2               # grid index of the board centre
LAYERS = [pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
NL = len(LAYERS)

CLR = 0.127                     # net-class clearance
SLOP = 0.045                    # grid quantisation allowance
W_SIG, W_PWR = 0.15, 0.20
VIA_D, VIA_DRILL = 0.5, 0.3
EDGE = 0.3
VIA_COST = 28.0                 # in grid steps
RIP_COST = 40.0                 # per grid step through somebody else's track
MAX_RIPS = 250                  # per phase
PHASES = 5
FREEZE_AFTER = 6              # rip-ups before a net becomes immovable
FREE, BLOCK = -1, -2

MM = pcbnew.FromMM


def to_idx(v):
    return int(round(v / G + OFF))


def to_mm(i):
    return (i - OFF) * G


class Maps:
    """trk[l,y,x]: -1 free, -2 blocked for everyone, else the only net allowed.
    via[y,x]: -1 where a via may be centred, else blocked."""

    X = Y = None

    def __init__(self):
        if Maps.X is None:
            ys, xs = np.mgrid[0:N, 0:N]
            Maps.X = (xs - OFF) * G
            Maps.Y = (ys - OFF) * G
            Maps.R = np.hypot(Maps.X, Maps.Y)
        self.trk = np.full((NL, N, N), FREE, dtype=np.int32)
        self.via = np.full((N, N), FREE, dtype=np.int32)
        self.trk[:, Maps.R > HALF - EDGE - W_PWR / 2 - SLOP] = BLOCK
        self.via[Maps.R > HALF - EDGE - VIA_D / 2 - SLOP] = BLOCK
        # straight edge under the USB-C socket
        self.trk[:, Maps.Y < d.BOARD_FLAT_Y + EDGE + W_PWR / 2 + SLOP] = BLOCK
        self.via[Maps.Y < d.BOARD_FLAT_Y + EDGE + VIA_D / 2 + SLOP] = BLOCK
        # no copper at all under the module's antenna
        mx, my = d.MODULE_XY
        ant = Maps.Y > my + d.MODULE_ANTENNA_FROM_CENTRE - 0.3
        self.trk[:, ant] = BLOCK
        self.via[ant] = BLOCK
        # Top-layer tracks may run under the module body (it is solder-masked
        # underneath, as on Espressif's own boards) but not under its centre
        # ground pad, which is handled as an ordinary pad.
        Maps.UNDER = np.zeros_like(ant)

    def copy(self):
        m = Maps.__new__(Maps)
        m.trk = self.trk.copy()
        m.via = self.via.copy()
        return m

    @staticmethod
    def _claim(arr, mask, net):
        cur = arr[mask]
        arr[mask] = np.where((cur == FREE) | (cur == net), net, BLOCK)

    def _window(self, x0, y0, x1, y1, pad):
        ix0, ix1 = max(0, to_idx(x0 - pad) - 1), min(N, to_idx(x1 + pad) + 2)
        iy0, iy1 = max(0, to_idx(y0 - pad) - 1), min(N, to_idx(y1 + pad) + 2)
        return slice(iy0, iy1), slice(ix0, ix1)

    def add_box(self, layers, cx, cy, w, h, ang, net):
        """Rectangle w x h centred on cx,cy and turned by ang degrees."""
        pad = W_SIG / 2 + CLR + SLOP
        vpad = VIA_D / 2 + CLR + SLOP
        r = math.hypot(w, h) / 2
        sy, sx = self._window(cx - r, cy - r, cx + r, cy + r, vpad)
        dist = box_distance(self.X[sy, sx], self.Y[sy, sx], cx, cy, w, h, ang)
        for l in layers:
            self._claim(self.trk[l][sy, sx], dist < pad, net)
        self.via[sy, sx][dist < vpad] = BLOCK

    def add_disc(self, layers, cx, cy, r, net, extra=0.0):
        pad = W_SIG / 2 + CLR + SLOP + extra
        vpad = VIA_D / 2 + CLR + SLOP + extra
        sy, sx = self._window(cx - r, cy - r, cx + r, cy + r, vpad)
        dist = np.hypot(self.X[sy, sx] - cx, self.Y[sy, sx] - cy) - r
        for l in layers:
            self._claim(self.trk[l][sy, sx], dist < pad, net)
        self.via[sy, sx][dist < vpad] = BLOCK

    def add_seg(self, l, ax, ay, bx, by, w, net):
        pad = w / 2 + W_SIG / 2 + CLR + SLOP
        vpad = w / 2 + VIA_D / 2 + CLR + SLOP
        sy, sx = self._window(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by), vpad)
        X, Y = self.X[sy, sx], self.Y[sy, sx]
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy
        t = np.clip(((X - ax) * vx + (Y - ay) * vy) / L2, 0, 1) if L2 else 0
        dist = np.hypot(X - (ax + t * vx), Y - (ay + t * vy))
        self._claim(self.trk[l][sy, sx], dist < pad, net)
        self.via[sy, sx][dist < vpad] = BLOCK


def box_distance(X, Y, cx, cy, w, h, ang):
    """Distance from points to a rotated rectangle (0 inside)."""
    a = math.radians(ang)
    u = (X - cx) * math.cos(a) + (Y - cy) * math.sin(a)
    v = -(X - cx) * math.sin(a) + (Y - cy) * math.cos(a)
    return np.hypot(np.maximum(np.abs(u) - w / 2, 0), np.maximum(np.abs(v) - h / 2, 0))


MOVES = ((0, 1, 1.0), (0, -1, 1.0), (1, 0, 1.0), (-1, 0, 1.0),
         (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142))


class Router:
    def __init__(self, board):
        self.b = board
        self.netid = {}
        self.pads = {}           # net -> [(layer idx, inside(), centre, label)]
        self.copper = {}         # net -> {"t": [(l,ax,ay,bx,by,w)], "v": [(x,y)]}
        self.fixed = set()       # nets that may not be ripped up
        self.pinned = set()      # nets frozen as soon as they are routed
        self.failed = []
        self.rips = 0
        self.budget = MAX_RIPS
        self.ripcount = {}       # net id -> times ripped (makes it dearer to rip again)
        self.pwr = set(d.POWER_NETS)
        self.base = Maps()       # pads only
        self._load()
        # applied after the pads so the module's own centre pad is covered too
        self.base.trk[0][Maps.UNDER] = BLOCK
        self.pre = self._refn_spines()   # hand-placed copper: net -> [(l,ax,ay,bx,by,w)]
        for name, segs in self.pre.items():
            for l, ax, ay, bx, by, w in segs:
                self.base.add_seg(l, ax, ay, bx, by, w, self.netid[name])
        # nets with many pads are expensive to re-route, so dearer to rip up
        self.weight = {self.netid[n]: 1.0 + 0.25 * len(p) for n, p in self.pads.items()}
        self.rebuild()

    # ------------------------------------------------------------ board import
    def _load(self):
        o = d.ORIGIN
        for fp in sorted(self.b.GetFootprints(), key=lambda f: f.GetReference()):
            for pad in fp.Pads():
                name = pad.GetNetname()
                net = self.netid.setdefault(name, len(self.netid)) if name else BLOCK
                c = pad.GetPosition()
                cx, cy = pcbnew.ToMM(c.x) - o[0], o[1] - pcbnew.ToMM(c.y)
                if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    # a bare hole: nothing may come near it on any layer
                    hole = pcbnew.ToMM(pad.GetDrillSize().x) / 2
                    self.base.add_disc(range(NL), cx, cy, hole, BLOCK, extra=0.25 - CLR)
                    continue
                if not pad.IsOnCopperLayer():
                    continue                      # paste-only apertures
                if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                    raise SystemExit(f"{fp.GetReference()}: plated through-hole pads are not supported")
                on_back = pad.IsOnLayer(pcbnew.B_Cu)
                l = 2 if on_back else 0
                size = pad.GetSize(pcbnew.B_Cu if on_back else pcbnew.F_Cu)
                w, h = pcbnew.ToMM(size.x), pcbnew.ToMM(size.y)
                if pad.GetShape(pcbnew.B_Cu if on_back else pcbnew.F_Cu) == pcbnew.PAD_SHAPE_CIRCLE:
                    self.base.add_disc([l], cx, cy, w / 2, net)
                    inside = lambda X, Y, cx=cx, cy=cy, r=w / 2: np.hypot(X - cx, Y - cy) < r - 0.1
                else:
                    ang = pad.GetOrientationDegrees()
                    self.base.add_box([l], cx, cy, w, h, ang, net)
                    inside = lambda X, Y, cx=cx, cy=cy, w=w, h=h, ang=ang: \
                        box_distance(X, Y, cx, cy, w - 0.12, h - 0.12, ang) == 0
                if name:
                    self.pads.setdefault(name, []).append(
                        (l, inside, (cx, cy), f"{fp.GetReference()}.{pad.GetNumber()}"))

    def _refn_spines(self):
        """All sixteen negative inputs share one net. Joining them underneath
        each converter, inside its ring of pads, leaves the outside free for
        the sixteen positive inputs to fan out."""
        segs = []
        k = 1.6                                  # spine distance from the chip centre
        for ref, (cx, cy) in d.ADC_XY.items():
            pts = [c for l, _, c, lbl in self.pads["REFN"] if lbl.startswith(ref + ".")]
            side = [c for c in pts if abs(c[0] - cx) > abs(c[1] - cy)]
            sx = cx + math.copysign(k, side[0][0] - cx)
            segs.append((0, sx, cy - k, sx, cy + k, W_SIG))
            for px, py in pts:
                if abs(px - cx) > abs(py - cy):
                    segs.append((0, px, py, sx, py, W_SIG))
                else:
                    ey = cy + math.copysign(k, py - cy)
                    segs.append((0, px, py, px, ey, W_SIG))
                    segs.append((0, px, ey, sx, ey, W_SIG))
        return {"REFN": segs}

    def rebuild(self):
        """Recompute the obstacle maps from pads plus all committed copper.
        self.hard holds only what cannot be ripped up."""
        self.hard = self.base.copy()
        for name in self.fixed:
            self._paint(self.hard, name)
        self.m = self.hard.copy()
        for name in self.copper:
            if name not in self.fixed:
                self._paint(self.m, name)

    def _paint(self, m, name):
        net = self.netid[name]
        c = self.copper.get(name)
        if not c:
            return
        for l, ax, ay, bx, by, w in c["t"]:
            m.add_seg(l, ax, ay, bx, by, w, net)
        for x, y in c["v"]:
            m.add_disc(range(NL), x, y, VIA_D / 2, net)

    def _cells(self, l, inside, net):
        ok = inside(Maps.X, Maps.Y) & (self.m.trk[l] == net)
        ys, xs = np.nonzero(ok)
        return [(l, int(y), int(x)) for y, x in zip(ys, xs)]

    # ------------------------------------------------------------------- A*
    def _search(self, net, sources, targets, to_via=False, relaxed=False):
        """Cheapest path from any source cell to any target cell. With to_via
        the search also ends at the first spot where a via fits (returns
        (path, True)). relaxed lets the path cross rippable copper at a price."""
        trk, via = self.m.trk, self.m.via
        htrk, hvia = self.hard.trk, self.hard.via
        tset = set(targets) if targets else set()
        if tset:
            ty = np.array([t[1] for t in tset]); tx = np.array([t[2] for t in tset])
            tcy, tcx = float(ty.mean()), float(tx.mean())
            trad = float(np.hypot(ty - tcy, tx - tcx).max())
            h = lambda y, x: max(0.0, math.hypot(y - tcy, x - tcx) - trad)
        else:
            h = lambda y, x: 0.0

        under = Maps.UNDER

        def via_ok(y, x):
            """0 = fine, >0 = extra cost (relaxed), -1 = impossible."""
            ks = range(1, NL) if under[y, x] else range(NL)
            if via[y, x] == FREE and all(trk[k, y, x] in (FREE, net) for k in ks):
                return 0.0
            if relaxed and hvia[y, x] == FREE and \
                    all(htrk[k, y, x] in (FREE, net) for k in ks):
                return RIP_COST * 6
            return -1.0

        def rip_price(v):
            if v < 0:
                return RIP_COST * 4
            return RIP_COST * (1 + 2 * self.ripcount.get(int(v), 0)) * self.weight.get(int(v), 1.0)

        dist, prev, pq = {}, {}, []
        for s in sources:
            dist[s] = 0.0
            heapq.heappush(pq, (h(s[1], s[2]), 0.0, s))
        while pq:
            _, g, cur = heapq.heappop(pq)
            if g > dist.get(cur, 1e18):
                continue
            l, y, x = cur
            if cur in tset:
                return self._trace(prev, cur), False
            if to_via and g > 0 and via_ok(y, x) == 0.0:
                return self._trace(prev, cur), True
            lw = 1.6 if l == 2 else 1.0     # electrode side: short hops only
            for dy, dx, c in MOVES:
                ny, nx = y + dy, x + dx
                if not (1 <= ny < N - 1 and 1 <= nx < N - 1):
                    continue
                v = trk[l, ny, nx]
                if v == FREE or v == net:
                    ng = g + c * lw
                elif relaxed and htrk[l, ny, nx] in (FREE, net):
                    ng = g + c * lw + rip_price(v)
                else:
                    continue
                nn = (l, ny, nx)
                if ng < dist.get(nn, 1e18):
                    dist[nn] = ng; prev[nn] = cur
                    heapq.heappush(pq, (ng + h(ny, nx), ng, nn))
            if not to_via:
                extra = via_ok(y, x)
                if extra >= 0:
                    for k in range(NL):
                        if k != l:
                            nn = (k, y, x)
                            ng = g + VIA_COST + extra
                            if ng < dist.get(nn, 1e18):
                                dist[nn] = ng; prev[nn] = cur
                                heapq.heappush(pq, (ng + h(y, x), ng, nn))
        return None

    @staticmethod
    def _trace(prev, cur):
        path = [cur]
        while cur in prev:
            cur = prev[cur]
            path.append(cur)
        return path[::-1]

    # ---------------------------------------------------------------- rip-up
    def _blockers(self, name, path, end_via):
        """Nets whose copper sits too close to this (relaxed) path."""
        net = self.netid[name]
        pts = {l: [] for l in range(NL)}
        vias = []
        for i, (l, y, x) in enumerate(path):
            if self.m.trk[l, y, x] not in (FREE, net):
                pts[l].append((to_mm(x), to_mm(y)))
            if i + 1 < len(path) and path[i + 1][0] != l:
                vias.append((to_mm(x), to_mm(y)))
        if end_via:
            vias.append((to_mm(path[-1][2]), to_mm(path[-1][1])))
        out = set()
        margin = CLR + SLOP + 2 * G
        for other, c in self.copper.items():
            if other == name or other in self.fixed:
                continue
            hit = False
            for l, ax, ay, bx, by, w in c["t"]:
                cand = [(p, w / 2 + W_PWR / 2 + margin) for p in pts[l]] + \
                       [(p, w / 2 + VIA_D / 2 + margin) for p in vias]
                for (px, py), lim in cand:
                    vx, vy = bx - ax, by - ay
                    L2 = vx * vx + vy * vy
                    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L2)) if L2 else 0.0
                    if math.hypot(px - ax - t * vx, py - ay - t * vy) < lim:
                        hit = True
                        break
                if hit:
                    break
            if not hit:
                allp = [p for l in range(NL) for p in pts[l]]
                for vx_, vy_ in c["v"]:
                    if any(math.hypot(px - vx_, py - vy_) < VIA_D / 2 + W_PWR / 2 + margin for px, py in allp) or \
                            any(math.hypot(px - vx_, py - vy_) < VIA_D + margin for px, py in vias):
                        hit = True
                        break
            if hit:
                out.add(other)
        return out

    def _connect(self, name, sources, targets, ripped, to_via=False):
        """Strict search; if that fails and rip-up budget remains, find the
        cheapest path through other nets, pull those nets off the board and
        try again. Returns (path, ended_at_new_via) or None."""
        net = self.netid[name]
        for _ in range(4):
            res = self._search(net, sources, targets, to_via)
            if res is not None:
                return res
            if self.rips >= self.budget:
                return None
            res = self._search(net, sources, targets, to_via, relaxed=True)
            if res is None:
                return None
            blk = self._blockers(name, *res)
            if not blk:
                return None
            for bname in blk:
                self.copper.pop(bname, None)
                ripped.add(bname)
                self.rips += 1
                bid = self.netid[bname]
                self.ripcount[bid] = self.ripcount.get(bid, 0) + 1
            self.rebuild()
        return None

    # ------------------------------------------------------------- committing
    def _commit(self, name, path, end_via=False):
        net = self.netid[name]
        w = W_PWR if name in self.pwr else W_SIG
        c = self.copper.setdefault(name, {"t": [], "v": []})
        i = 0
        while i < len(path) - 1:
            l, y, x = path[i]
            l2, y2, x2 = path[i + 1]
            if l2 != l:
                self._via(name, x, y)
                i += 1
                continue
            dy, dx = y2 - y, x2 - x
            j = i + 1
            while j + 1 < len(path) and path[j + 1][0] == l and \
                    (path[j + 1][1] - path[j][1], path[j + 1][2] - path[j][2]) == (dy, dx):
                j += 1
            ax, ay, bx, by = to_mm(x), to_mm(y), to_mm(path[j][2]), to_mm(path[j][1])
            c["t"].append((l, ax, ay, bx, by, w))
            for m in (self.m,) + ((self.hard,) if name in self.fixed else ()):
                m.add_seg(l, ax, ay, bx, by, w, net)
            i = j
        if end_via:
            self._via(name, path[-1][2], path[-1][1])
        return set(path)

    def _via(self, name, x, y):
        net = self.netid[name]
        self.copper.setdefault(name, {"t": [], "v": []})["v"].append((to_mm(x), to_mm(y)))
        for m in (self.m,) + ((self.hard,) if name in self.fixed else ()):
            m.add_disc(range(NL), to_mm(x), to_mm(y), VIA_D / 2, net)

    # ---------------------------------------------------------------- nets
    def route_net(self, name):
        """Returns the set of nets that had to be ripped up to make room."""
        net = self.netid[name]
        ripped = set()
        self.copper.pop(name, None)
        # A net that keeps getting pulled up is frozen once re-routed, so the
        # others have to find a way round it; this is what makes the loop end.
        if self.ripcount.get(net, 0) >= FREEZE_AFTER or name in self.pinned:
            self.fixed.add(name)
        self.rebuild()
        terms = list(self.pads[name])
        mx = sum(t[2][0] for t in terms) / len(terms)
        my = sum(t[2][1] for t in terms) / len(terms)
        terms.sort(key=lambda t: math.hypot(t[2][0] - mx, t[2][1] - my))
        first = terms[0]
        tree = set(self._cells(first[0], first[1], net))
        done_c = [first[2]]
        todo = terms[1:]
        later, retried = [], set()
        while todo:
            todo.sort(key=lambda t: min(math.hypot(t[2][0] - c[0], t[2][1] - c[1]) for c in done_c))
            l, inside, c, lbl = todo.pop(0)
            cells = self._cells(l, inside, net)
            res = self._connect(name, cells, tree, ripped) if cells and tree else None
            if res is None:
                # try once more at the end, when the rest of the net is in place
                if lbl not in retried:
                    retried.add(lbl)
                    later.append((l, inside, c, lbl))
                else:
                    self.failed.append((name, lbl))
                if not todo and later:
                    todo, later = later, []
                continue
            tree |= self._commit(name, res[0]) | set(cells)
            done_c.append(c)
            if not todo and later:
                todo, later = later, []
        return ripped

    def route_ground(self):
        """Ground is never ripped up once placed."""
        name = "GND"
        net = self.netid[name]
        self.fixed.add(name)
        self.rebuild()
        ripped = set()
        tree = set()
        for l, inside, c, lbl in self.pads[name]:
            cells = self._cells(l, inside, net)
            if cells and tree & set(cells):
                continue
            res = self._connect(name, cells, tree, ripped, to_via=True) if cells else None
            if res is None:
                self.failed.append((name, lbl))
                continue
            path, new_via = res
            tree |= self._commit(name, path, end_via=new_via)
            if new_via:
                _, y, x = path[-1]
                tree |= {(k, y, x) for k in range(NL)}
        return ripped

    def run(self, order):
        queue = list(order)
        for phase in range(PHASES):
            while queue:
                name = queue.pop(0)
                self.failed = [f for f in self.failed if f[0] != name]
                ripped = self.route_ground() if name == "GND" else self.route_net(name)
                if ripped:
                    print(f"  {name}: ripped up {', '.join(sorted(ripped))}")
                for r in sorted(ripped):
                    if r not in queue:
                        queue.append(r)
            bad = []
            for f in self.failed:
                if f[0] != "GND" and f[0] not in bad:
                    bad.append(f[0])
            print(f"phase {phase + 1}: {len(bad)} nets incomplete, {self.rips} rip-ups so far")
            if not bad:
                break
            # thaw everything, lift the ground tracks and vias (they are cheap
            # to redo and may be what is in the way), and let the unfinished
            # nets have another go with a fresh budget; ground goes back last
            self.fixed = set()
            self.copper.pop("GND", None)
            self.failed = [f for f in self.failed if f[0] != "GND"]
            self.ripcount = {}
            self.budget = self.rips + MAX_RIPS
            queue = bad + ["GND"]

    # ------------------------------------------------------------- writing
    def write(self):
        b, o = self.b, d.ORIGIN
        P = lambda x, y: pcbnew.VECTOR2I(MM(o[0] + x), MM(o[1] - y))
        nt = nv = 0
        everything = [(n, c["t"], c["v"]) for n, c in self.copper.items()] + \
                     [(n, segs, []) for n, segs in self.pre.items()]
        for name, tracks, vias in everything:
            ni = b.FindNet(name)
            for l, ax, ay, bx, by, w in tracks:
                t = pcbnew.PCB_TRACK(b)
                t.SetStart(P(ax, ay)); t.SetEnd(P(bx, by))
                t.SetWidth(MM(w)); t.SetLayer(LAYERS[l]); t.SetNet(ni)
                b.Add(t); nt += 1
            for x, y in vias:
                v = pcbnew.PCB_VIA(b)
                v.SetPosition(P(x, y))
                v.SetViaType(pcbnew.VIATYPE_THROUGH)
                v.SetWidth(pcbnew.F_Cu, MM(VIA_D))
                v.SetDrill(MM(VIA_DRILL))
                v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                v.SetNet(ni)
                b.Add(v); nv += 1
        return nt, nv


def net_order(r):
    """Short local nets first, long buses later, ground last."""
    def span(name):
        cs = [c for _, _, c, _ in r.pads[name]]
        xs = [c[0] for c in cs]; ys = [c[1] for c in cs]
        return (max(xs) - min(xs)) + (max(ys) - min(ys))
    names = [n for n in r.pads if n != "GND" and len(r.pads[n]) > 1]
    first = ["REFN"] + [n for n in names if n.startswith(("CAP_", "REFIN_"))]
    # the USB pair has to cross over between the socket's pads, and the clock
    # sits in the tightest spot: both go in while the board is still empty
    first += [n for n in ("USB_DP", "USB_DN", "OSC_OUT", "ADC_CLK") if n in names]
    ins = sorted([n for n in names if n.startswith("IN")], key=span)
    els = sorted([n for n in names if n.startswith("EL")], key=span)
    pwr = [n for n in ("AVDD", "DVDD", "+5V", "+3V3") if n in names]
    rest = sorted([n for n in names if n not in first + ins + els + pwr], key=span)
    return first + ins + pwr + rest + els + ["GND"]


def main():
    board = pcbnew.LoadBoard(PCB)
    for t in list(board.GetTracks()):
        board.Remove(t)
    for z in list(board.Zones()):
        if z.GetZoneName() != "GND_PLANE":
            board.Remove(z)
    r = Router(board)
    order = net_order(r)
    r.run(order)
    nt, nv = r.write()

    # ground pours on the outer layers, stitched by the ground vias
    gnd = board.FindNet("GND")
    for layer, nm in ((pcbnew.F_Cu, "GND_TOP"), (pcbnew.B_Cu, "GND_BOTTOM")):
        gen_pcb.add_zone(board, layer, gnd, nm, HALF + 1)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(OUT_PCB, board)
    if OUT_PCB == PCB:
        gen_pcb.write_project()
    print(f"{nt} track segments, {nv} vias, {r.rips} rip-ups")
    gnd_left = [f for f in r.failed if f[0] == "GND"]
    if gnd_left:
        print("ground pads left to the copper pour (check.sh confirms they are joined):",
              " ".join(f[1] for f in gnd_left))
    bad = [f for f in r.failed if f[0] != "GND"]
    if bad:
        print("NOT ROUTED:")
        for f in bad:
            print("  ", *f)
        sys.exit(1)
    print("all signal connections routed")


if __name__ == "__main__":
    main()
