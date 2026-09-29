#!/usr/bin/env python3
"""Read-only Claude Code spend scanner. Stdlib only.

It reads only token-usage counts, model ids, timestamps, record types, message and
request ids (for de-duplication), the names and ids of SendMessage tool calls, project
folder names, and each sub-agent's type and short description from its .meta.json; it
never prints message text, sends nothing off the machine, and writes nothing (stdout only).

Prices every assistant call found in transcript JSONL files (main sessions and
sub-agent threads), de-duplicates, and prints aggregates plus project directory
names and short sub-agent descriptions (from each .meta.json). It never prints
message content. Redact project names and descriptions before sharing output.
Dollars are API list-price equivalents (relative usage on a subscription).

  scan_spend.py --days 7
  scan_spend.py --root ~/.claude --since 2026-09-24 --until "2026-09-28 18:30"
  scan_spend.py --compare 2026-09-20 2026-09-24 2026-09-24 2026-09-28
"""
import argparse, collections, datetime as dt, glob, json, os, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = dt.datetime.now().astimezone().tzinfo
BUCKETS = [("<50K", 50e3), ("50-150K", 150e3), ("150-300K", 300e3), ("300K+", float("inf"))]


def parse_when(s):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt).replace(tzinfo=LOCAL)
        except ValueError:
            pass
    sys.exit("bad date %r (use YYYY-MM-DD or 'YYYY-MM-DD HH:MM', local time)" % s)


def load_prices(path):
    with open(path) as f:
        p = json.load(f)
    return p


def price_for(model, prices):
    """Return (price, how). how = "exact", "fallback" (family substring, may be wrong for
    older models) or None (unpriced: no sourced price, tokens still counted)."""
    m = (model or "").lower()
    if m.endswith("[1m]"):
        m = m[:-4]
    P = prices["models"]
    if P.get(m):
        return P[m], "exact"
    for k in prices.get("unpriced_families", []):
        if k in m:
            return None, None
    for k in prices["match_order"]:
        if k in m:
            ref = P.get(prices["families"][k])
            return (ref, "fallback") if ref else (None, None)
    return None, None


def cost_parts(c, price):
    return {
        "input": c["inp"] * price["input"] / 1e6,
        "output": c["out"] * price["output"] / 1e6,
        "cache_write_5m": c["cw5"] * price["cache_write_5m"] / 1e6,
        "cache_write_1h": c["cw1"] * price["cache_write_1h"] / 1e6,
        "cache_read": c["cr"] * price["cache_read"] / 1e6,
    }


def find_files(roots, t0):
    seen, files = set(), []
    for r in roots:
        proj = os.path.join(r, "projects")
        base = proj if os.path.isdir(proj) else r
        for f in glob.glob(os.path.join(base, "**", "*.jsonl"), recursive=True):
            rp = os.path.realpath(f)
            if rp in seen:
                continue
            seen.add(rp)
            try:
                if os.path.getmtime(rp) < t0.timestamp():
                    continue
            except OSError:
                continue
            files.append((base, f))
    return files


def load(roots, t0, t1):
    calls, compacts, resumes, spawn_seen, thread_first = {}, [], 0, set(), {}
    files = find_files(roots, t0)
    for base, f in files:
        rel = os.path.relpath(f, base).split(os.sep)
        project = rel[0]
        sub = "subagents" in rel
        sid = rel[1] if sub else rel[-1][:-6]
        thread = f
        atype = desc = None
        if sub:
            mp = f[:-6] + ".meta.json"
            try:
                with open(mp) as mf:
                    meta = json.load(mf)
                atype, desc = meta.get("agentType"), meta.get("description")
            except (OSError, ValueError):
                pass
        with open(f, errors="replace") as fh:
            for line in fh:
                is_a = '"assistant"' in line
                if not is_a and "compact_boundary" not in line:
                    continue
                try:
                    d = json.loads(line)
                    T = dt.datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00"))
                except (ValueError, KeyError, TypeError, AttributeError):
                    continue
                if is_a and d.get("type") == "assistant" and not str((d.get("message") or {}).get("model", "")).startswith("<"):
                    if thread not in thread_first or T < thread_first[thread]:
                        thread_first[thread] = T
                if not (t0 <= T < t1):
                    continue
                if d.get("type") == "system" and d.get("subtype") == "compact_boundary":
                    compacts.append(T)
                    continue
                if d.get("type") != "assistant":
                    continue
                m = d.get("message") or {}
                u = m.get("usage") or {}
                key = (m.get("id") or d["uuid"], d.get("requestId"))
                cc = u.get("cache_creation") or {}
                c5, c1 = cc.get("ephemeral_5m_input_tokens"), cc.get("ephemeral_1h_input_tokens")
                if c5 is None and c1 is None:
                    c5, c1 = u.get("cache_creation_input_tokens", 0) or 0, 0
                new = dict(project=project, sid=sid, thread=thread, sub=sub, atype=atype,
                           desc=desc, T=T, model=m.get("model") or "",
                           inp=u.get("input_tokens", 0) or 0, out=u.get("output_tokens", 0) or 0,
                           cw5=c5 or 0, cw1=c1 or 0, cr=u.get("cache_read_input_tokens", 0) or 0)
                old = calls.get(key)
                if old:  # streamed messages repeat: keep the max of each counter
                    for x in ("inp", "out", "cw5", "cw1", "cr"):
                        old[x] = max(old[x], new[x])
                else:
                    calls[key] = new
                for b in m.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "SendMessage":
                        if b.get("id") not in spawn_seen:
                            spawn_seen.add(b.get("id"))
                            resumes += 1
    return list(calls.values()), compacts, resumes, len(files), thread_first


def summarize(calls, compacts, resumes, prices, t0, t1, thread_first):
    S = dict(total=0.0, n=0, tokens=0, parts=collections.Counter(), by=collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0.0, 0])),
             threads=collections.defaultdict(lambda: dict(cost=0.0, n=0, desc=None, atype=None, sub=False, project=None)),
             first={}, unpriced=collections.defaultdict(lambda: [0, 0]), fallback=collections.Counter())
    for c in sorted(calls, key=lambda c: c["T"]):
        if not (t0 <= c["T"] < t1):
            continue
        price, how = price_for(c["model"], prices)
        ctx = c["inp"] + c["cw5"] + c["cw1"] + c["cr"]
        S["n"] += 1
        S["tokens"] += ctx + c["out"]
        if not price:
            if c["model"].startswith("<"):  # harness-synthetic messages carry no usage
                continue
            u = S["unpriced"][c["model"] or "?"]
            u[0] += 1; u[1] += ctx + c["out"]
            continue
        if how == "fallback":
            S["fallback"][c["model"]] += 1
        fam = c["model"] or "?"
        parts = cost_parts(c, price)
        usd = sum(parts.values())
        S["total"] += usd
        S["parts"].update(parts)
        atype = c["atype"] or ("sidechain" if c["sub"] else "main")
        bucket = next(n for n, hi in BUCKETS if ctx < hi)
        for dim, k in (("model", fam), ("agent type", atype), ("project", c["project"]), ("context", bucket), ("day", c["T"].astimezone().strftime("%Y-%m-%d"))):
            r = S["by"][dim][k]
            r[0] += 1; r[1] += usd; r[2] += ctx + c["out"]
        t = S["threads"][c["thread"]]
        t["cost"] += usd; t["n"] += 1; t["sub"] = c["sub"]; t["atype"] = atype; t["project"] = c["project"]
        t["desc"] = t["desc"] or c["desc"]
        # Fixed per-spawn overhead: count only threads whose FIRST call is inside this window
        # (skips resumed main sessions and threads that began before --since).
        if thread_first.get(c["thread"], t0) >= t0:
            S["first"].setdefault(c["thread"], (atype, ctx))
    S["compacts"] = sum(1 for T in compacts if t0 <= T < t1)
    S["resumes"] = resumes
    return S


def money(x):
    return "$%s" % format(round(x), ",")


def table(title, rows, total, limit=15):
    print("\n## %s" % title)
    print("%-44s %8s %12s %10s %6s" % ("", "calls", "tokens", "USD", "share"))
    for k, (n, usd, tok) in sorted(rows.items(), key=lambda kv: -kv[1][1])[:limit]:
        print("%-44s %8d %12s %10s %5.1f%%" % (str(k)[-44:], n, format(tok, ","), money(usd), 100 * usd / total if total else 0))


def report(S, top, label=""):
    print("# Spend%s" % label)
    print("total %s | %s API calls | %.2fB tokens" % (money(S["total"]), format(S["n"], ","), S["tokens"] / 1e9))
    if S["fallback"]:
        print("WARNING: priced by FAMILY FALLBACK (no exact price in prices.json; older or newer models can differ, treat their $ as approximate):")
        for mdl, n in S["fallback"].most_common():
            print("  %s (%d calls)" % (mdl, n))
    if S["unpriced"]:
        print("UNPRICED (no sourced price; tokens counted, $ unknown, NOT in the total):")
        for mdl, (n, tok) in S["unpriced"].items():
            print("  %s: %d calls, %s tokens, $ unknown" % (mdl, n, format(tok, ",")))
    print("cost split: " + ", ".join("%s %s" % (k, money(v)) for k, v in S["parts"].items()))
    for dim in ("model", "agent type", "context", "project", "day"):
        table(dim, S["by"][dim], S["total"])
    print("\n## top %d threads by cost" % top)
    for path, t in sorted(S["threads"].items(), key=lambda kv: -kv[1]["cost"])[:top]:
        d = (t["desc"] or ("main session" if not t["sub"] else "(no description)"))[:70]
        print("%10s %5d calls  %-16s %s" % (money(t["cost"]), t["n"], (t["atype"] or "")[:16], d))
    per = collections.defaultdict(list)
    for atype, ctx in S["first"].values():
        per[atype].append(ctx)
    print("\n## median first-call context per agent type (= per-spawn fixed overhead; threads whose first call is inside the window only)")
    for atype, v in sorted(per.items(), key=lambda kv: -len(kv[1]))[:15]:
        print("%-24s %8s tokens  (%d threads)" % (atype, format(int(statistics.median(v)), ","), len(v)))
    print("\ncompactions: %d | SendMessage calls (includes resumes of finished workers): %d" % (S["compacts"], S["resumes"]))


def compare(A, B, la, lb):
    print("# Compare  A=%s  B=%s" % (la, lb))
    def row(name, a, b, fmt=lambda x: "%.2f" % x):
        ds = "%8.1f%%" % (100 * (b - a) / a) if a else "%9s" % "n/a"
        print("%-34s %14s %14s %s" % (name, fmt(a), fmt(b), ds))
    print("%-34s %14s %14s %9s" % ("", "A", "B", "change"))
    row("total USD", A["total"], B["total"], money)
    row("calls", A["n"], B["n"], lambda x: format(int(x), ","))
    row("USD per call", A["total"] / max(A["n"], 1), B["total"] / max(B["n"], 1), lambda x: "$%.4f" % x)
    row("tokens per call", A["tokens"] / max(A["n"], 1), B["tokens"] / max(B["n"], 1), lambda x: format(int(x), ","))
    for dim in ("model", "agent type", "context"):
        print("\n-- %s (share of USD)" % dim)
        keys = set(A["by"][dim]) | set(B["by"][dim])
        for k in sorted(keys, key=lambda k: -(A["by"][dim].get(k, [0, 0])[1] + B["by"][dim].get(k, [0, 0])[1]))[:10]:
            a = A["by"][dim].get(k, [0, 0, 0])[1]; b = B["by"][dim].get(k, [0, 0, 0])[1]
            print("%-30s A %5.1f%% %9s | B %5.1f%% %9s" % (k[-30:], 100 * a / A["total"] if A["total"] else 0, money(a), 100 * b / B["total"] if B["total"] else 0, money(b)))
    def med(S):
        per = collections.defaultdict(list)
        for at, ctx in S["first"].values():
            per[at].append(ctx)
        return {k: statistics.median(v) for k, v in per.items()}
    ma, mb = med(A), med(B)
    print("\n-- median first-call context (per-spawn overhead)")
    for k in sorted(set(ma) & set(mb)):
        print("%-24s A %8s | B %8s" % (k[:24], format(int(ma[k]), ","), format(int(mb[k]), ",")))
    print("\ncompactions A %d B %d | SendMessage calls A %d B %d" % (A["compacts"], B["compacts"], A["resumes"], B["resumes"]))
    print("Note: compare per-call and per-agent-type figures; raw totals depend on how much work each window contained.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", action="append", help="Claude config dir (repeatable). Default: $CLAUDE_CONFIG_DIR or ~/.claude")
    ap.add_argument("--since"); ap.add_argument("--until")
    ap.add_argument("--days", type=float, help="window = last N days (ignored if --since given)")
    ap.add_argument("--compare", nargs=4, metavar=("A_SINCE", "A_UNTIL", "B_SINCE", "B_UNTIL"))
    ap.add_argument("--top", type=int, default=10, help="top N threads (default 10)")
    ap.add_argument("--prices", default=os.path.join(HERE, "prices.json"))
    a = ap.parse_args()
    roots = [os.path.expanduser(r) for r in (a.root or [os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"])]
    roots = [os.path.expanduser(r) for r in roots]
    prices = load_prices(a.prices)
    print("prices as_of %s (verify on the vendor pricing page). Dollar figures are API list-price equivalents; on a subscription read them as relative usage, not a bill." % prices["as_of"])
    now = dt.datetime.now(LOCAL)
    if a.compare:
        w = [parse_when(x) for x in a.compare]
        lo, hi = min(w[0], w[2]), max(w[1], w[3])
    else:
        hi = parse_when(a.until) if a.until else now + dt.timedelta(minutes=1)
        lo = parse_when(a.since) if a.since else hi - dt.timedelta(days=a.days or 7)
    calls, compacts, resumes, nf, tfirst = load(roots, lo, hi)
    print("scanned %d transcript files, %d unique calls" % (nf, len(calls)))
    if a.compare:
        A = summarize(calls, compacts, resumes, prices, w[0], w[1], tfirst)
        B = summarize(calls, compacts, resumes, prices, w[2], w[3], tfirst)
        compare(A, B, "%s..%s" % (a.compare[0], a.compare[1]), "%s..%s" % (a.compare[2], a.compare[3]))
    else:
        report(summarize(calls, compacts, resumes, prices, lo, hi, tfirst), a.top, " %s .. %s" % (lo.strftime("%Y-%m-%d %H:%M"), hi.strftime("%Y-%m-%d %H:%M")))


if __name__ == "__main__":
    main()
