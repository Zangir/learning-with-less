"""Audit requested source-position cuts without substituting terminal group states."""
from collections import Counter, defaultdict
from pathlib import Path
import csv, hashlib, json

ROOT = Path(__file__).resolve().parents[3]
OLD = ROOT/'T-008/r2/december'
OUT = ROOT/'T-008/r3/participant'
REQUEST = ROOT/'T-009/r3'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    events = list(map(json.loads, (OLD/'identity_candidate_events.v2.jsonl').read_text().splitlines()))
    initial = json.loads((OLD/'identity_candidate_initial.v2.json').read_text())
    anchors = json.loads((OUT/'snapshot_local_checkpoints.json').read_text())['checkpoints']
    replay = list(map(json.loads, (OUT/'replayed_top20.jsonl').read_text().splitlines()))
    after = list(csv.DictReader((REQUEST/'q16_required_cuts.csv').open()))
    before = list(csv.DictReader((REQUEST/'q16_before_insertion_cuts.csv').open()))
    wanted_after = {int(r['source_last_row_0based']) for r in after}
    wanted_before = {int(r['source_reference_row_0based']) for r in before}
    state = {}
    volumes = Counter()
    counts = Counter()
    for order in initial['orders']:
        key = order['local_order_token']
        level = (order['side'], order['price_units_1e8_usd'])
        quantity = order['quantity_units_1e8_btc']
        state[key] = (level, quantity)
        volumes[level] += quantity
        counts[level] += 1
    measured = {}
    last_by_level_time = {}
    for event in events:
        level = (event['side'], event['price_units_1e8_usd'])
        last_by_level_time[(level, event['candidate_group_time_ns'])] = event['source_diff_row_0based']
    for event in events:
        ordinal = event['source_diff_row_0based']
        level = (event['side'], event['price_units_1e8_usd'])
        if ordinal in wanted_before:
            measured[('before', ordinal)] = (counts[level], volumes[level])
        token = event['local_order_token']
        old_level, old_quantity = state.get(token, (level, 0))
        assert old_level == level
        if old_quantity > 0:
            counts[level] -= 1
            volumes[level] -= old_quantity
        quantity = event['quantity_after_units_1e8_btc']
        if event['kind'] == 'remove': state.pop(token, None)
        else: state[token] = (level, quantity)
        if quantity > 0:
            counts[level] += 1
            volumes[level] += quantity
        if ordinal in wanted_after:
            measured[('after', ordinal)] = (counts[level], volumes[level])
    details = []
    stats = Counter()
    for kind, source in [('after', after), ('before', before)]:
        for row in source:
            ordinal = int(row['source_last_row_0based' if kind == 'after' else 'source_reference_row_0based'])
            price = int(row['price_units_1e8_usd'])
            side = row['side']
            stamp = int(row['candidate_group_time_ns'])
            actual = measured[(kind, ordinal)]
            assert actual == (int(row['positive_count']), int(row['positive_volume_units_1e8_btc']))
            level_terminal = kind == 'after' and ordinal == last_by_level_time[((side, price), stamp)]
            choices = [a for a in anchors if replay[a['candidate_state_index']]['source_last_row'] < ordinal
                       and a['event_bin_upper_exclusive_ns'] <= stamp
                       and (price >= a['bid_covered_at_or_above_units8'] if side == 'B'
                            else price <= a['ask_covered_at_or_below_units8'])]
            anchor = choices[-1] if choices else None
            stats[kind+'_rows'] += 1
            stats[kind+'_positive_count_volume_reproduced'] += 1
            stats[kind+'_locally_checkpoint_covered_price'] += anchor is not None
            if kind == 'after': stats['after_inside_level_candidate_group'] += not level_terminal
            else: stats['before_requires_insertion_position_semantics'] += 1
            details.append(dict(episode_id=row['episode_id'], source_cut_position=kind,
                source_row=ordinal, side=side, price_units8=price,
                positive_count=actual[0], positive_volume_units8=actual[1],
                terminal_at_this_level_candidate_time=level_terminal,
                needs_within_group_source_order_premise=not level_terminal,
                earlier_local_checkpoint_anchor=anchor['anchor_id'] if anchor else None,
                local_checkpoint_price_coverage=anchor is not None,
                initial_region_without_local_checkpoint='Old strict-clearing P3 premise remains necessary where no local checkpoint covers the price.',
                empirical_admission=False))
    (OUT/'q16_actual_cut_coverage.v3.0.1.jsonl').write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in details))
    summary = dict(summary=dict(stats), origin='exploratory_real', admitted=False,
        exact_source_order_arithmetic=True,
        within_group_source_order_not_identified_by_terminal_snapshots=True,
        checkpoint_bin_end_must_precede_candidate_cut_time=True,
        supersedes='q16_actual_cut_summary.json only for stricter local checkpoint timing; original preserved',
        additional_premise_I1='For an interior cut, exported same-price event order equals the actual processing/visibility order relevant to the source observer; final-group commutation cannot supply this premise.',
        no_cohort_filtering_or_group_end_replacement=True,
        source_hashes={str(p):sha(p) for p in [REQUEST/'q16_producer_request.json', REQUEST/'q16_required_cuts.csv',
          REQUEST/'q16_before_insertion_cuts.csv', OLD/'identity_candidate_events.v2.jsonl', OLD/'identity_candidate_initial.v2.json']},
        output_sha256=sha(OUT/'q16_actual_cut_coverage.v3.0.1.jsonl'), code_sha256=sha(Path(__file__)))
    (OUT/'q16_actual_cut_summary.v3.0.1.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__': main()
