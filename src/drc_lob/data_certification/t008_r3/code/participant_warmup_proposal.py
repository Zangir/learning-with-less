"""Freeze a clock-only adaptation proposal and falsifying boundary examples."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'clock_adaptation'
NS=1000000000
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def normalize_example(rows,prefix=30*NS):
    output=[]
    for row in rows:
        if row[0]<prefix:continue
        if output and row[0]<output[-1][0]:raise ValueError('inversion')
        if output and row[0]==output[-1][0]:
            if row[1]!=output[-1][1]:raise ValueError('conflicting full payload')
            continue
        output.append(row)
    return output
checks=[]
def test(name,value):
    assert value,name
    checks.append(dict(name=name,passed=True))
def rejects(rows):
    try:normalize_example(rows)
    except ValueError:return True
    return False
test('fixed prefix removes only old event times, preserves retained source order',normalize_example([(3*NS,'a'),(NS,'b'),(31*NS,'c'),(32*NS,'d')])==[(31*NS,'c'),(32*NS,'d')])
test('late reversal is rejected, never sorted',rejects([(31*NS,'a'),(35*NS,'b'),(32*NS,'c')]))
test('exact30s event retained,30s-minus1ns excluded',normalize_example([(30*NS-1,'a'),(30*NS,'b')])==[(30*NS,'b')])
test('identical full-payload tie collapses to first source occurrence',normalize_example([(31*NS,'a'),(31*NS,'a')])==[(31*NS,'a')])
test('same top5 cannot excuse conflicting deeper payload',rejects([(31*NS,('same_top5','depth6_a')),(31*NS,('same_top5','depth6_b'))]))
test('Q17history cannot borrow preprefix observation',49*NS-20*NS<30*NS and 50*NS-20*NS>=30*NS)
test('Q18 history begins after first retained snapshot, not merely nominal warmup',105*NS-75*NS<30*NS+100000000 and 106*NS-75*NS>=30*NS+100000000)
test('10.5second exclusive-end guard rejects equality',not (10500000000<10500000000) and 10500000000<10500000001)
test('segment reset at reversed timestamp creates overlapping event intervals',max([31,35])>=min([32,34]))
test('recovery past prior high-water avoids overlapping event intervals',min([36,37])>max([31,35]))
test('standalone snapshot establishes recorded state without hidden prefix',normalize_example([(3*NS,{'bid':10}),(31*NS,{'bid':12})])[-1][1]=={'bid':12})
test('incremental delta would not identify state after prefix',10+2!=20+2)
assessment=OUT/'first_hour_clock_assessment.json'
observed=json.loads(assessment.read_text())
test('all3observed first-hour inversions inside common30s prefix',len(observed['inversion_witnesses'])==3 and all(w['both_events_inside_fixed_prefix'] for w in observed['inversion_witnesses']))
test('no observed retained first-hour inversions or conflicting ties',all(v.get('retained_event_inversions',0)==v.get('retained_conflicting_equal_timestamp',0)==0 for v in observed['results'].values()))
test('all24dateassetpairs retained in assessment',len(observed['results'])==24)
tests=dict(schema='t008-clock-proposal-counterexamples/1',synthetic_argument_checks=checks,
           execution_scope='Tests of proposed mechanics only; no changed-policy market normalization or fitting.',code_sha256=sha(Path(__file__)))
(OUT/'counterexamples_and_checks.json').write_text(json.dumps(tests,indent=2)+'\n')
proposal=dict(schema='t008-clock-adaptation-proposal/1',status='proposed_pending_scoped_decision_and_independent_review_before_fits',
    created_at_utc=datetime.now(timezone.utc).isoformat(),operation='cycle1808:T-008:clock-quality-adaptation-proposal',
    role='Engineer',seed=20260919,
    preserves=dict(strict_policy_path=str(ROOT/'panel_protocol.v3.1.json'),strict_policy_sha256=sha(ROOT/'panel_protocol.v3.1.json'),
                   strict_result='All frozen roles remain required; unavailable training dates imply not_evaluable and zero strict-policy fits.'),
    selection_timing='Post-acquisition, pre-fit quality-driven proposal. Not original pre-acquisition preregistration; no outcome/return/class/model statistic used.',
    proposed_rule=dict(prefix_seconds=30,applies='All12 fixed dates, BTC and ETH, identical event-time rule for first-hour and any later full-day adaptation.',
        event_period='[UTC_day_start+30s, declared_period_end), further bounded by actual observed support.',
        receipt_period='Original acquired provider-receipt slices remain unchanged, beginning00:00; raw prefix and boundary observations all retained.',
        retained_row='Original-order full l2Book snapshot whose exchange event timestamp lies inside proposed event period.',
        receipt_handling='Preserve exact provider receipt separately. Do not treat it as strategy release, calibrated exchange receipt, or proof event_time<=receipt_time.',
        later_quality='Preserve source order. After declared prefix, reject any inversion or conflicting equal-time full-depth payload. Collapse only full-payload-identical ties to earliest source occurrence with ledger.',
        continuity='Keep2s source-gap/disconnect segmentation and1.5s independent maximum age unchanged.',
        history='Initialize at the first retained full snapshot in each segment; no preprefix state, return, change count or temporal feature may carry forward.',
        horizons='Q17: -20,-5,-1,0,+0.1,+0.5,+10,+10.1,+10.5s; Q18 every one-second cut[-75,+10] and+10.5s guard. Entire task support fits the same new segment; endpoint exclusive.',
        grid='Keep an explicitly frozen UTC grid phase; do not silently shift11s scheduling phase when window start changes. Proposal changes eligibility only; consumer must report/validate chosen original anchor.',
        pairing='Use paired common eligible calendar cuts across assets as required; no gap compression, duplicated overlap, date replacement or role dropping.',
        full_day='First-hour success does not establish full-day source quality. Later reversals/conflicts remain unavailable under this proposed rule; assess all retained full-day rows separately.'),
    minimal_argument='Filtering a fixed event-time prefix preserves source order. A retained l2Book message is a standalone observed snapshot, so it needs no excluded delta prefix for state arithmetic. If retained timestamps pass strict ordering/tie checks and every feature/target cut stays within retained support, prefix snapshots cannot enter any feature. This justifies the sampled-state observation mechanics conditional on source claims; it does not authenticate exchange ordering or prove online final-mask availability.',
    distinction_from_segmented_recovery='Resetting at a lower reversed timestamp leaves overlapping event-time ranges and ambiguous as-of states. A separately proposed segmented policy must exclude the ambiguous interval and resume past the previous event high-water mark, preserve disjoint support and purge all task horizons; it changes support adaptively to timestamp faults. It is not implemented or selected here.',
    unresolved=['Restart cause is not authenticated; no claim that the provider reconnected or exchange restarted.',
                'Quality-driven exclusion can correlate with market conditions even without inspecting outcomes; all exclusion counts and strict result remain visible.',
                'Third-party source authenticity and historical/strategy receive latency remain unproved.',
                'No original full-day criterion, performance result, scientific negative or accepted primary follows from this proposal.'],
    prohibited_until_review=['Changed-policy production normalizer','Model fits','Outcome or score-based warmup/date/period tuning'],
    bindings={p.name:dict(path=str(p),sha256=sha(p)) for p in (assessment,OUT/'counterexamples_and_checks.json',ROOT/'evidence/hour00_provider_chain_independent.json')})
(OUT/'proposal.v1.json').write_text(json.dumps(proposal,indent=2)+'\n')
text='''# Uniform prefix exclusion: review proposal

Role: Engineer. This is a post-acquisition, pre-fit source-quality adaptation proposal. It is pending a scoped decision and independent review before any revised normalization or fit. The original strict policy, unavailable February/March records and all required train/validation/test roles remain unchanged; the strict path is not evaluable and has zero fits when required training roles are unavailable.

The proposed analytical event period begins at 00:00:30 UTC on every fixed date for both BTC and ETH. Entire original provider-receipt slices and raw prefixes remain retained. Only full snapshots with exchange event times in the declared new period enter analysis, in their original source order. Provider receipt remains separately preserved collection metadata; no calibration, strategy release or causal delivery assertion is added. Later event inversions or conflicting full-depth equal-time payloads still reject under the strict rule. Identical full-payload ties may collapse to their earliest source row with a ledger. The two-second gap rule and separate1.5-second age rule are unchanged.

An independent clock-only pass over72 acquired responses and24 date/asset pairs found exactly three event-order reversals: one February BTC reversal of89ms and March BTC/ETH reversals near2.8s. Both endpoints of each reversal lie in the fixed30-second prefix. There are no retained first-hour reversals or conflicting equal-time payloads after that prefix. No returns, labels, classes, model outputs or revised normalized market rows were calculated. These facts explain the proposal; they do not make it a pre-acquisition preregistration or establish full-day quality.

The minimum mechanics argument is narrow. A full snapshot records a complete observed book view without requiring an excluded incremental prefix. Filtering a uniform event-time prefix preserves the relative order of all retained observations. Strict ordering and tie checks on those retained observations provide an unambiguous as-of lookup under the sampled exchange-time convention. All features begin at the first retained snapshot of a valid segment, so no prefix information may flow through carried state, returns, change counts or age calculations. Every Q17/Q18 backward and forward cut, including the fractional10.5-second guard, must remain in that same segment; final support validity stays retrospective. A fixed UTC grid phase must be preserved or explicitly declared before evaluation: changing start_ns must not silently move the11-second schedule phase.

Full snapshots remove the need for an initial delta state, but do not prove source authentication, native exchange ordering, complete intervening venue events or a restart mechanism. The proposal does not claim that the provider or exchange restarted. Quality-selected exclusions may correlate with market conditions; the strict result and all removed-row counts remain visible. Later full-day bytes require a separate full-source audit. No dates or role requirements are replaced after inspection, and no scientific negative, original full-day acceptance or performance conclusion follows.

A segmented reversal alternative is more complicated. Resetting a segment immediately at a reversed timestamp produces overlapping event ranges:31,35 followed by32,34 has two candidate histories for cuts in32–35. A defensible segmented proposal must remove the ambiguous overlap and resume beyond the previous high-water time, then rebuild full task histories and prevent cross-gap schedules. It would create data-dependent support windows and require its own reviewed protocol. It is not implemented or chosen here.

Fifteen mechanics/data-quality checks cover late reversal rejection, strict30-second inclusion, deeper-payload tie conflicts, earliest identical-tie retention, Q17/Q18 history rebuild, exclusive10.5-second guards, the overlapping-segment counterexample and the standalone-snapshot versus incremental-delta distinction. They test an explicit proposal, not a changed-policy experiment.
'''
(OUT/'proposal.md').write_text(text,encoding='utf-8')
files=[p for p in OUT.iterdir() if p.is_file() and p.name!='manifest.json']
manifest=dict(schema='t008-clock-adaptation-review-bundle/1',status='proposal_only',
    files={p.name:dict(path=str(p),sha256=sha(p),bytes=p.stat().st_size) for p in files},
    code={p.name:dict(path=str(p),sha256=sha(p)) for p in (Path(__file__),ROOT/'code/participant_warmup_assessment.py')})
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(dict(checks_passed=len(checks),proposal_sha256=sha(OUT/'proposal.v1.json'),manifest_sha256=sha(OUT/'manifest.json')),indent=2))
