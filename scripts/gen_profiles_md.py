import argparse
import json
from collections import OrderedDict

parser = argparse.ArgumentParser(
    description='Generate a Markdown benchmark report from a profiles JSON file.')
parser.add_argument('input', help='Path to the profiles JSON file to parse.')
parser.add_argument('-o', '--output', default='profile_benchmarks.md',
                    help='Path to the Markdown file to write (default: profile_benchmarks.md).')
args = parser.parse_args()

with open(args.input) as f:
    d = json.load(f)
runs = d['runs']

METRICS = OrderedDict([
    ('ttft_ms', 'TTFT — time to first text (ms)'),
    ('ttfo_ms', 'TTFO — time to first output (ms)'),
    ('ttfa_ms', 'TTFA — time to first audio (ms)'),
    ('tpot_estimate_ms', 'TPOT — time per output token (ms)'),
    ('text_gap_ms', 'Text inter-chunk gap (ms)'),
    ('audio_gap_ms', 'Audio inter-chunk gap (ms)'),
    ('e2e_ms', 'End-to-end latency (ms)'),
])

def fmt(x):
    if x is None:
        return '—'
    return f'{x:,.1f}'

# group runs by profile, keep load order by concurrency
by_profile = OrderedDict()
for run in runs:
    by_profile.setdefault(run['profile'], []).append(run)
for p in by_profile:
    by_profile[p].sort(key=lambda r: r['concurrency'])

out = []
out.append('# Routing Profile Benchmark — Two Load Levels\n')
out.append(f"**Model:** `{d['model']}`  ")
out.append(f"**Endpoint:** `{d['endpoint']}`  ")
out.append(f"**Modalities:** {', '.join(d['modalities'])}  ")
out.append(f"**Profiles tested:** {len(by_profile)} &nbsp;·&nbsp; **Total runs:** {len(runs)}\n")

out.append('Each profile was benchmarked at two concurrency levels (the "two loads"). '
           'Latency metrics are reported as **mean / p50 / p99** in milliseconds.\n')

# Table of contents
out.append('## Profiles\n')
for p in by_profile:
    anchor = p.lower()
    out.append(f'- [{p}](#{anchor})')
out.append('')

for prof, pruns in by_profile.items():
    out.append(f'\n## {prof}\n')
    scorer = pruns[0]['scorer']
    out.append(f'**Scorer:** `{scorer}`\n')

    # Run summary table
    out.append('### Run summary\n')
    out.append('| Load (concurrency) | Iterations | Duration (s) | Valid | Failed | Missing output |')
    out.append('|---|---|---|---|---|---|')
    for r in pruns:
        out.append(f"| {r['concurrency']} | {r['iterations']} | {r['duration_seconds']:.2f} | "
                   f"{r['valid_responses']} | {r['failed_responses']} | {r['missing_output_responses']} |")
    out.append('')

    # Routing distribution
    out.append('### Pod routing distribution\n')
    pods = []
    for r in pruns:
        pods.extend(r['routing'].keys())
    pods = list(dict.fromkeys(pods))
    header = '| Load (concurrency) | ' + ' | '.join(f'`{p}`' for p in pods) + ' |'
    out.append(header)
    out.append('|' + '---|' * (len(pods) + 1))
    for r in pruns:
        cells = ' | '.join(str(r['routing'].get(p, 0)) for p in pods)
        out.append(f"| {r['concurrency']} | {cells} |")
    out.append('')

    # Metrics table: one block per load
    out.append('### Latency metrics (mean / p50 / p99 ms)\n')
    header = '| Metric | ' + ' | '.join(f'Load {r["concurrency"]}' for r in pruns) + ' |'
    out.append(header)
    out.append('|' + '---|' * (len(pruns) + 1))
    for mkey, mlabel in METRICS.items():
        cells = []
        for r in pruns:
            m = r['metrics'].get(mkey, {})
            cells.append(f"{fmt(m.get('mean'))} / {fmt(m.get('p50'))} / {fmt(m.get('p99'))}")
        out.append(f'| {mlabel} | ' + ' | '.join(cells) + ' |')
    out.append('')

with open(args.output, 'w') as f:
    f.write('\n'.join(out) + '\n')

print(f'Wrote {args.output},', len(out), 'lines')
