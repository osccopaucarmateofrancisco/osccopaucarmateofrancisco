import re
import sys

PITCH = 16.0  # px per grid cell, derived from the source SVG's own translate values

def clamp_above_grid(content):
    """Platane/snk's solver sometimes routes the snake's rest pose (and a couple of
    turn maneuvers) through the row directly above the visible calendar grid
    (y = -16px, i.e. one cell-pitch above row 0). Visually this reads as the snake
    'escaping' the grid. Snap any such translate(...,-16px) back down to row 0 --
    this covers both the @keyframes stops and the static .s.sN{...} fallback rule,
    since both use the same translate(Xpx,Ypx) syntax."""
    return re.sub(r'(translate\([-\d.]+px,)-16px\)', r'\g<1>0px)', content)

def uniform_segment_size(content):
    """Platane/snk tapers the snake's body: the head <rect> is drawn larger than the
    tail segments (different x/y/width/height/rx/ry per class), so the tail looks
    like it doesn't fully fill its cell. Make every segment use the head's (s0's)
    geometry so all segments render as identical, fully-colored squares."""
    pattern = re.compile(
        r'<rect class="s s(\d+)" x="([-\d.]+)" y="([-\d.]+)" '
        r'width="([-\d.]+)" height="([-\d.]+)" rx="([-\d.]+)" ry="([-\d.]+)"/>'
    )
    matches = list(pattern.finditer(content))
    if not matches:
        return content
    # use the first segment declared (the head, s0) as the canonical full-size square
    _, x0, y0, w0, h0, rx0, ry0 = matches[0].groups()

    def replace(m):
        idx = m.group(1)
        return f'<rect class="s s{idx}" x="{x0}" y="{y0}" width="{w0}" height="{h0}" rx="{rx0}" ry="{ry0}"/>'

    return pattern.sub(replace, content)

def fmt(p):
    # format percentage compactly, matching source style closely enough (up to 2 decimals)
    s = f"{p:.3f}".rstrip('0').rstrip('.')
    if s == '' or s == '-0':
        s = '0'
    return s

def parse_stops(body):
    """body is the inside of an @keyframes block (without the wrapping curly braces
    of the whole rule, i.e. starts right after 'sN{' and before the final matching '}')."""
    # entries look like: "12.34%,56.78%{transform:translate(Xpx,Ypx)}"
    pattern = re.compile(r'([\d.,%]+)\{transform:translate\(([-\d.]+)px,([-\d.]+)px\)\}')
    stops = []
    for m in pattern.finditer(body):
        pct_list = [float(p) for p in m.group(1).replace('%', '').split(',')]
        x = float(m.group(2))
        y = float(m.group(3))
        stops.append((pct_list, x, y))
    return stops

def discretize(stops):
    """Given ordered stops (list of (pct_list, x, y)), return new stop list where any
    transition spanning more than one grid cell (16px) on a single axis is expanded
    into a chain of quick snap + hold sub-steps, one per intermediate cell."""
    new_stops = []
    for i, (pct_list, x, y) in enumerate(stops):
        # always keep the first declared percentage of every original stop as an anchor
        first_pct = pct_list[0]
        if i == 0:
            new_stops.append(([first_pct] + pct_list[1:], x, y))
            continue

        prev_pct_list, px, py = stops[i - 1][0], stops[i - 1][1], stops[i - 1][2]
        prev_end_pct = prev_pct_list[-1]  # the time the previous value was last held at
        span = first_pct - prev_end_pct
        dx = x - px
        dy = y - py
        dist = max(abs(dx), abs(dy))
        n = round(dist / PITCH) if dist > 0 else 0

        if n <= 1 or span <= 0 or (dx != 0 and dy != 0):
            # already a single-cell (or zero-distance) move, or a diagonal
            # decorative detour that isn't a straight grid-aligned glide --
            # leave it exactly as declared rather than guessing at sub-steps
            new_stops.append(([first_pct] + pct_list[1:], x, y))
            continue

        # multi-cell straight glide -> convert into n quick snap+hold hops
        snap_dur = min(0.15, span / n * 0.4)
        snap_dur = max(snap_dur, 0.02)
        hold_dur = (span - n * snap_dur) / (n - 1) if n > 1 else 0
        if hold_dur < 0:
            # not enough time budget for the requested snap speed -- fall back to
            # evenly spaced snaps with no hold (still discrete steps, just back-to-back)
            snap_dur = span / n
            hold_dur = 0

        t = prev_end_pct
        step_x = dx / n
        step_y = dy / n
        for cell in range(1, n + 1):
            t_snap_end = t + snap_dur
            vx = px + step_x * cell
            vy = py + step_y * cell
            if cell < n:
                t_hold_end = t_snap_end + hold_dur
                new_stops.append(([t_snap_end, t_hold_end], vx, vy))
                t = t_hold_end
            else:
                # last hop must land exactly on the original declared percentage(s)
                new_stops.append(([first_pct] + pct_list[1:], x, y))
                t = first_pct
    return new_stops

def stops_to_css(stops):
    parts = []
    for pct_list, x, y in stops:
        pct_str = ','.join(fmt(p) + '%' for p in pct_list)
        parts.append(f"{pct_str}{{transform:translate({fmt(x)}px,{fmt(y)}px)}}")
    return ''.join(parts)

def extract_block_span(content, name):
    idx = content.index('@keyframes ' + name + '{')
    start = idx + len('@keyframes ' + name)  # points at '{'
    depth = 0
    for i in range(start, len(content)):
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
            if depth == 0:
                return idx, i + 1, content[start + 1:i]  # inner body without outer braces
    raise ValueError(f"unbalanced braces for {name}")

def process(content):
    content = uniform_segment_size(content)
    content = clamp_above_grid(content)
    names = sorted(set(re.findall(r'@keyframes (s\d+)\{', content)))
    for name in names:
        block_start, block_end, body = extract_block_span(content, name)
        stops = parse_stops(body)
        if not stops:
            continue
        new_stops = discretize(stops)
        new_body = stops_to_css(new_stops)
        new_rule = '@keyframes ' + name + '{' + new_body + '}'
        content = content[:block_start] + new_rule + content[block_end:]
    return content

if __name__ == '__main__':
    inp, outp = sys.argv[1], sys.argv[2]
    src = open(inp, encoding='utf-8').read()
    out = process(src)
    open(outp, 'w', encoding='utf-8').write(out)
    print("done ->", outp)
