"""Executable counterexamples and review notes for frozen receipt-first v3.2 policy."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'clock_adaptation'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
NS=1000000000
def candidate(rows):
    prior=None;analytical=[]
    for receipt,event,payload in rows:
        if receipt<30*NS:continue
        if prior is not None:
            if event<prior[0]:raise ValueError('remaining source inversion')
            if event==prior[0] and payload!=prior[1]:raise ValueError('remaining full-payload conflict')
            if event==prior[0]:continue
        prior=(event,payload)
        if 30*NS<=event<3600*NS:analytical.append((receipt,event,payload))
    return analytical
def rejects(rows):
    try:candidate(rows)
    except ValueError:return True
    return False
checks=[]
def test(name,value):
    assert value,name
    checks.append(dict(name=name,passed=True))
test('provider receipt prefix excluded first even if event time at or after30s',candidate([(29*NS,31*NS,'a'),(31*NS,32*NS,'b')])==[(31*NS,32*NS,'b')])
test('source event reversal inside excluded receipt prefix does not reorder retained source',candidate([(28*NS,29*NS,'a'),(29*NS,28*NS,'b'),(31*NS,31*NS,'c')])==[(31*NS,31*NS,'c')])
test('boundary event below30s aftergoodretainedmessage still rejects inversion',rejects([(31*NS,31*NS,'a'),(32*NS,29*NS,'b')]))
test('boundary conflicting tie below30s still rejects before analytical filtering',rejects([(31*NS,29*NS,'a'),(32*NS,29*NS,'b')]))
test('late reversal beyond30s rejected rather than sorted',rejects([(31*NS,31*NS,'a'),(36*NS,35*NS,'b'),(37*NS,32*NS,'c')]))
test('out-of-period event cannot hide later reversal',rejects([(3598*NS,3601*NS,'a'),(3599*NS,3599*NS,'b')]))
test('exact30s receipt and eventincluded',candidate([(30*NS,30*NS,'a')])==[(30*NS,30*NS,'a')])
test('identicalfullpayload tieskeep earliest source receipt',candidate([(31*NS,31*NS,'a'),(32*NS,31*NS,'a')])==[(31*NS,31*NS,'a')])
test('matchingtop5butdifferent deeper level rejects full-payloadtie',rejects([(31*NS,31*NS,('same5','deepA')),(32*NS,31*NS,('same5','deepB'))]))
test('Q17 earliest feature cannot borrow excludedprefix',49*NS-20*NS<30*NS)
test('Q18 support starts at actualfirstsnapshot not nominal30',105*NS-75*NS<30*NS+100000000)
test('exclusive fractional guard rejects equality',not(10500000000<10500000000) and 10500000000<10500000001)
test('reversed-reset segments overlap until pre-reversal highwaterpassed',min([32,34])<max([31,35]) and min([36,37])>max([31,35]))
test('fullsnapshot records selfcontainedstate whiledelta doesnot',{'bid':12}['bid']==12 and 10+2!=20+2)
assessment=OUT/'receipt_prefix_clock_assessment.v3.2.json'
observed=json.loads(assessment.read_text())
test('all24firsthourdateassetpairs assessed',len(observed['results'])==24)
test('remaining source hasnoinversions/conflicts before analyticalfilter',all(r.get('remaining_source_inversions',0)==r.get('remaining_conflicting_equal_timestamp',0)==0 for r in observed['results'].values()))
test('three raw inversion witnesses lieinside common receiptprefix',len(observed['inversion_witnesses'])==3 and all(r['both_provider_receipts_inside_fixed_prefix'] for r in observed['inversion_witnesses']))
policy=ROOT/'panel_protocol.v3.2.startup30.json'
assert sha(policy)=='e5de9c455d3918b11693af0f771de4776f49cd9b2a1f1918000c0179259c8d19'
result=dict(schema='t008-clock-policy-mechanics-proof/3.2',role='Engineer',status='mechanics_evidence_for_RV011_not_scientific_acceptance',
    frozen_policy_sha256=sha(policy),created_utc=datetime.now(timezone.utc).isoformat(),
    tested_order='Receipt-prefix exclusion, strict remaining source event/full-depth-tie validation, then analytical event-window filter.',
    checks=checks,no_revised_market_normalizer_or_fits_executed=True,
    input_assessment_sha256=sha(assessment),code_sha256=sha(Path(__file__)),
    prior_v1_proposal='Preserved generic event-prefix proposal is superseded by exact receipt-first frozen v3.2; it was not an executed production policy.',
    future_mask='Final future-target/utility support remains retrospective; exact source filtering alone does not create online admission.',
    clock_scope='Provider receipt is an uncalibrated third-party selection/provenance clock; event timestamps define the hypothetical sampled exchange-time observer.')
(OUT/'mechanics_proof.v3.2.json').write_text(json.dumps(result,indent=2)+'\n')
report='''# Exact receipt-first startup exclusion: evidence for RV011

Role: Engineer. This document supports review of the exact frozen `panel_protocol.v3.2.startup30.json` with SHA-256 `e5de9c455d3918b11693af0f771de4776f49cd9b2a1f1918000c0179259c8d19`. It is mechanics evidence, not an independent scientific acceptance or fit authorization. D019 permits construction; fits remain gated on RV011 support for the exact amended input contracts and consumer amendments. The original strict policy, its ten valid paired dates and two unavailable required training dates remain preserved. That strict model design is not evaluable, not a negative model finding.

## Exact order of operations

First exclude raw messages whose **provider receipt** is before UTC00:00:30, identically for every fixed date and both assets. Retain all such bytes, hashes, source ordinals and exclusion counts. Blank disconnect markers stay in the raw evidence and retain their boundary semantics. Second, validate the event-clock source order and full-depth equal-time payloads on **all remaining messages**, including event timestamps below00:00:30 or outside the analytical period. A late old-event row must not bypass validation by being filtered from analysis. Third, select analytical full snapshots with exchange event timestamps at or after00:00:30 and before the declared period end, in unchanged source order. Identical full-payload ties retain the earliest source occurrence; conflicting ties and later inversions reject.

Provider receipt defines the fixed excluded prefix and the original acquisition slices. It is not relabeled strategy availability, exchange admission or calibrated latency. No inequality between receipt and exchange event time is imposed as physical truth. Both clocks remain separately preserved. Thirty seconds was chosen after source-only quality inspection, so this is source-quality-informed, post-acquisition and pre-fit; identical application across dates does not make it pre-acquisition or fully untouched.

## Narrow mechanics argument

The receipt-prefix operation returns a source-order subsequence. Strict validation of that entire remainder detects retained inversions and conflicting equal-time states before event-period selection can conceal them. Selecting an analytical event interval from a monotone remainder preserves its order. A full l2Book snapshot supplies its own observed state; no excluded incremental history is needed to construct that snapshot. This supports the declared sampled-state observer, conditional on the provider's source claims. It does not authenticate exchange chronology, native atomic events, intervening event completeness or a restart cause.

The first analytical snapshot initializes a fresh observation segment. No preprefix snapshot or derived return, change-count, staleness, rolling statistic or fitted quantity may be carried through it. Q17 must rebuild all20 seconds of backward support; Q18 must rebuild75 seconds. All forecast and utility endpoints, including10.1/10.5 seconds and every twelve-by-eleven-second schedule, must fit actual observed support and avoid gaps/disconnects. The period end is exclusive. Source-gap2s and age1.5s rules stay separate. Paired assets use eligible calendar-cut intersections; source timestamps are not claimed synchronous. A previously frozen UTC scheduling phase must be checked explicitly so changing window start does not silently shift the11-second grid. No gaps are compressed and overlapping windows are not counted as independent periods.

Final target/future-freshness eligibility remains an offline retrospective population mask. Past-only feature lookup does not make it an online admission rule.

## Independent source-clock evidence

The independent72-response provider audit verifies request/index hashes, headers, compressed sizes, gzip EOF/CRC and decoded digests, exact provider-receipt slice membership and monotonicity. An additional CPU1 clock-only pass implements the exact receipt-first validation order over24 first-hour date/asset pairs. It finds three raw reversals: February BTC -89ms, March BTC -2779ms and March ETH -2843ms. Both provider receipts of every witness lie in the common excluded prefix. All remaining source messages have zero event inversions and zero conflicting equal-time full-depth payloads. Counts, first/last candidate analytical events and boundary exclusions are bound in `receipt_prefix_clock_assessment.v3.2.json`. No production normalized data, return, class, model threshold or fit is produced by this diagnostic.

These first-hour facts do not establish full-day source quality. Every later acquired message still requires the exact frozen checks and a separate exact-input scope review; a later inversion cannot be cured by expanding the prefix or replacing a date after inspecting results.

## Counterexamples and limitations

Seventeen executable checks cover receipt-first exclusion, exact30-second boundaries, identical/full-depth-conflicting ties, later reversals, actual first-snapshot history support and exclusive fractional guards. Two key negative examples validate a remainder `(receipt31,event31)` followed by `(receipt32,event29)`, and two different payloads at event29 after receipt30. Both must reject even though event29 would be outside the analytical period. Validating only after event filtering would silently hide those source defects.

A separate segmented-recovery idea is not implemented. Resetting immediately after an event reversal, for example31,35 then32,34, leaves overlapping event-time support. Such a policy would have to exclude the ambiguous overlap, resume past the previous high-water mark and rebuild all task histories. It would require a separate reviewed support-selection rule. The fixed uniform prefix has a simpler declared population but is still chosen after source inspection; source-quality selection can correlate with market conditions.

No authenticated collector or exchange restart is inferred. No accepted original full-day criterion, mandatory transfer, performance result, scientific negative or counterfactual execution conclusion follows from this engineering evidence.
'''
(OUT/'review_note.v3.2.md').write_text(report,encoding='utf-8')
files=[policy,assessment,OUT/'mechanics_proof.v3.2.json',OUT/'review_note.v3.2.md',ROOT/'evidence/hour00_provider_chain_independent.json',
       ROOT/'code/participant_warmup_receipt_assessment.py',Path(__file__),OUT/'manifest.json']
manifest=dict(schema='t008-clock-adaptation-review-bundle/3.2',status='awaiting_RV011_exact_input_review_no_fit_authorization',
    files={str(p):dict(sha256=sha(p),bytes=p.stat().st_size) for p in files})
(OUT/'manifest.v3.2.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(dict(checks_passed=len(checks),proof_sha256=sha(OUT/'mechanics_proof.v3.2.json'),manifest_sha256=sha(OUT/'manifest.v3.2.json')),indent=2))
