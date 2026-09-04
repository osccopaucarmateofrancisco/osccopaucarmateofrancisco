import re
import sys

PITCH = 16.0  # px per grid cell, derived from the source SVG's own translate values

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

        if n <= 1 or span <= 0:
            # already a single-cell (or zero-distance) move -- keep as is
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
