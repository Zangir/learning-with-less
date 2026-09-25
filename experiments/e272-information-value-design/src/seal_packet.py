"""Verify scoped evidence, synthetic checks, source ledger and private PDF handoff."""
import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from resource_guard import ROOT, record

WORKTREE = Path(__file__).resolve().parents[1]
PROGRAM = ROOT.parents[1]


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=WORKTREE, text=True).strip()


def main():
    status = 'failed'
    try:
        before = json.loads((ROOT / 'preservation-before.json').read_text())
        after = {p.relative_to(ROOT.parent).as_posix(): sha(p)
                 for p in ROOT.parent.rglob('*') if p.is_file() and ROOT not in p.parents}
        assert before == after, 'Prior T-012 evidence changed'
        identities = json.loads((ROOT / 'scoped-input-identities.json').read_text())
        for item in identities['files']:
            assert sha(PROGRAM / item['path']) == item['sha256'], item['path']
        code = []
        for path in sorted((ROOT / 'code').glob('*.py')):
            ast.parse(path.read_text(), filename=path.name)
            assert sha(path) == sha(WORKTREE / 'experiments/t012/r10/code' / path.name)
            code.append(dict(path=path.name, sha256=sha(path), repository_copy_equal=True))
        assert len(code) == 5
        assert not (WORKTREE / 'research-control').exists()
        assert not (WORKTREE / 'research-state').exists()
        assert not git('status', '--porcelain', '--', 'experiments/t012/r10')
        subprocess.run(['git', 'diff', '--check'], cwd=WORKTREE, check=True)
        for stage in ('checks', 'render'):
            assert (ROOT / f'{stage}.exit').read_text().strip() == '0'
            assert json.loads((ROOT / f'{stage}-resource.json').read_text())['status'] == 'completed'
        checks = json.loads((ROOT / 'analytical-checks.json').read_text())
        assert len(checks['cases']) == 5
        assert checks['empirical_scoring'] == checks['new_fits'] == checks['native_episodes'] == 0
        assert checks['shift_counterexample']['common_source']
        review = json.loads((ROOT / 'pdf-visual-review.json').read_text())
        assert review['all_pages_inspected'] and review['pages'] == 5
        assert sha(ROOT / 'report.pdf') == review['pdf_sha256']
        assert len(list(ROOT.glob('report-preview-*.png'))) == 5
        for item in review['page_images']:
            assert sha(ROOT / item['path']) == item['sha256']
        log = (ROOT / 'report.log').read_text(errors='replace')
        assert 'Overfull' not in log and 'LaTeX Error' not in log
        extracted = (ROOT / 'report-extracted.txt').read_text(encoding='utf-8')
        for phrase in ('Information value before another learner',
                       'Falsification fixtures and alternatives', 'Nearest primary work'):
            assert phrase in extracted, phrase
        sources = {}
        for name in ('report.md', 'primary-source-ledger.md'):
            for line in (ROOT / name).read_text(encoding='utf-8').splitlines():
                for title, url in re.findall(r'\[([^\]]+)\]\((https?://[^)]+)\)', line):
                    entry = sources.setdefault(url, dict(url=url, checked_on='2026-09-22', citations=[]))
                    entry['citations'].append(dict(title=title, document=name, context=line))
        save('source-ledger.json', dict(local=identities['files'], primary_urls=list(sources.values()),
            primary_papers=7, detailed_scope='primary-source-ledger.md',
            scope='Targeted primary literature and scoped report identities; not exhaustive novelty',
            full_r042_manifest_replayed=False, empirical_arrays_read=False))
        free = shutil.disk_usage(Path.cwd()).free
        assert free >= 50 * 1024**3
        packet_bytes = sum(p.stat().st_size for p in ROOT.rglob('*') if p.is_file())
        worktree_bytes = sum(p.stat().st_size for p in WORKTREE.rglob('*') if p.is_file())
        # Leave space for the final receipts and manifests; accounting should not eat its own tail.
        new_upper = packet_bytes + worktree_bytes + 2 * 1024**2
        assert new_upper <= 64 * 1024**2
        program_upper = 12048959950 + 8 * 1024**2 + new_upper
        assert program_upper + 512 * 1024**2 <= 12 * 1024**3
        save('seal-verification.json', dict(at=datetime.now().astimezone().isoformat(), status='passed',
            previous_files=len(before), previous_files_unchanged=True, scoped_inputs=len(identities['files']),
            code=code, code_commit=git('rev-parse', 'HEAD'), branch=git('branch', '--show-current'),
            original_base='ed62f2a4ccebc7ad559ba0c185954401d5311cb8',
            worktree_base='797ffe1152076f66bf2dee39d94c15e285526770', pdf_pages=5,
            browser_interaction_verified=False, physical_free_bytes=free,
            new_retained_upper_bytes=new_upper, program_upper_bytes=program_upper,
            protected_reserve_bytes=512 * 1024**2, source_papers=7,
            new_fits=0, empirical_scoring=0, source_replay=0, market_acquisition=0,
            native_episodes=0, subagents_used=0, publication_or_push=False))
        status = 'completed'
    finally:
        record('seal-resource.json', dict(status=status, new_fits=0, native_episodes=0))


if __name__ == '__main__':
    main()
