"""Documented secondary retry of unresolved anchors; primary results stay frozen."""
import hashlib
import json
from pathlib import Path
import time

from r2_adapter import evaluate_episode

ROOT = (Path(__file__).resolve().parents[2] / 'runtime')


def run():
    results_path = ROOT / 'conditional_results.jsonl'
    primary_digest = hashlib.sha256(results_path.read_bytes()).hexdigest()
    primary = [json.loads(line) for line in results_path.read_text().splitlines()]
    pending = {row['episode_id'] for row in primary if row['status'] == 'unresolved'}
    episodes = json.loads((ROOT / 'conditional_episodes.json').read_text())['episodes']
    policy = {'origin': 'exploratory_real', 'admitted': False,
              'primary_results_sha256': primary_digest,
              'selection': 'all and only unresolved anchors from unchanged primary cohort',
              'query_timeout_ms': 10000, 'cohort_or_model_changes': False,
              'interpretation': 'secondary completion analysis; primary timeout dispositions retained',
              'episode_ids': sorted(pending)}
    (ROOT / 'conditional_retry_protocol.json').write_text(json.dumps(policy, indent=2) + '\n')
    started, results = time.monotonic(), []
    for episode in episodes:
        if episode['episode_id'] in pending:
            result = evaluate_episode(episode, '0.00000001', 'exploratory_real', timeout_ms=10000)
            results.append(result)
            print(json.dumps({'episode_id': episode['episode_id'], 'status': result['status']}), flush=True)
    if hashlib.sha256(results_path.read_bytes()).hexdigest() != primary_digest:
        raise ValueError('Primary results changed during secondary retry')
    output = {**policy, 'results': results, 'elapsed_seconds': time.monotonic() - started,
              'primary_results_unchanged': True}
    (ROOT / 'conditional_retry.json').write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps({'elapsed_seconds': output['elapsed_seconds'],
                      'statuses': [row['status'] for row in results]}), flush=True)


if __name__ == '__main__':
    run()
