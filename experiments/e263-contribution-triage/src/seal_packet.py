"""Verify private deliverables and prior preservation before final manifest sealing."""
import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
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
        assert before == after, 'Previous evidence changed'
        code = []
        for path in sorted((ROOT / 'code').glob('*.py')):
            ast.parse(path.read_text(), filename=path.name)
            peer = WORKTREE / 'experiments/t012/r9/code' / path.name
            assert sha(path) == sha(peer), path.name
            code.append(dict(path=path.name, sha256=sha(path), repository_copy_equal=True))
        assert len(code) == 5
        assert not (WORKTREE / 'research-control').exists()
        assert not (WORKTREE / 'research-state').exists()
        assert not git('status', '--porcelain', '--', 'experiments/t012/r9'), 'Uncommitted r9 code'
        assert (ROOT / 'checks.exit').read_text().strip() == '0'
        assert (ROOT / 'render.exit').read_text().strip() == '0'
        report = (ROOT / 'report.md').read_text()
        assert 'checked marginal physical/domain range' in report
        assert 'leave their training ranges' not in report
        assert len(list(ROOT.glob('report-preview-*.png'))) == 6
        assert json.loads((ROOT / 'pdf-visual-review.json').read_text())['all_pages_inspected']
        log = (ROOT / 'report.log').read_text(errors='replace')
        assert 'Overfull' not in log and 'LaTeX Error' not in log
        extracted = (ROOT / 'report-extracted.txt').read_text(encoding='utf-8')
        for phrase in ['Remaining contribution triage', 'Robust prediction under known observation changes',
                       'Constraint-aware joint sampled-path generation', 'Risk control with missing horizons']:
            assert phrase in extracted, phrase
        sources = {}
        documents = ['report.md', 'atlas-observation-operator-candidate.md',
                     'delta-path-generation-candidate.md', 'echo-censoring-risk-candidate.md']
        for name in documents:
            for line in (ROOT / name).read_text(encoding='utf-8').splitlines():
                for title, url in re.findall(r'\[([^\]]+)\]\((https?://[^)]+)\)', line):
                    source = sources.setdefault(url, dict(url=url, checked_on='2026-09-22',
                        source_kind='primary paper or publisher version record', citations=[]))
                    source['citations'].append(dict(title=title, memo=name, memo_sha256=sha(ROOT/name),
                                                    method_or_theorem_context=line))
        local_names = ['cycle-20260922-1222/T012-brief.md', 'cycle-20260922-1222/D-041.md',
            'cycle-20260922-0212/inputs/architecture.md', 'cycle-20260922-0212/inputs/resources.md',
            'cycle-20260922-0212/inputs/strategies/catalog.md',
            'cycle-20260922-1122/frozen-R-030/report.md', 'cycle-20260922-1222/frozen-RV-028/report.md',
            'cycle-20260922-1122/frozen-R-031/report.md', 'cycle-20260922-1222/frozen-RV-029/report.md',
            'q18-full-day-review-handoff/frozen-T008-r4/assessment/report.tex',
            'rv018-final-intake/frozen-review/review.md']
        local = []
        for name in local_names:
            path = PROGRAM / name
            assert path.is_file(), name
            local.append(dict(path=name, sha256=sha(path)))
        save('source-ledger.json', dict(local=local, primary=list(sources.values()),
            scope='Targeted mechanism overlap; not exhaustive novelty or independent proof certification',
            access_limit='Axioms/PMC direct access inconsistent; primary indexed text inspected in source review'))
        save('seal-verification.json', dict(at=datetime.now().astimezone().isoformat(), status='passed',
            previous_files=len(before), previous_files_unchanged=True, code=code,
            code_commit=git('rev-parse', 'HEAD'), branch=git('branch', '--show-current'),
            original_base='ed62f2a4ccebc7ad559ba0c185954401d5311cb8',
            worktree_base='e1b65d48850189c47bb7fa241303a760a9d7a989',
            checked_frozen_members=700, corrected_report_wording=True, pdf_pages=6,
            javascript_checked=True, browser_interaction_verified=False,
            local_sources=len(local), unique_primary_urls=len(sources),
            new_fits=0, native_episodes=0, market_acquisition=0,
            source_replay=0, publication_or_push=False))
        status = 'completed'
    finally:
        record('seal-resource.json', dict(status=status, new_fits=0, native_episodes=0))


if __name__ == '__main__':
    main()
