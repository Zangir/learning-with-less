"""Freeze the complete diagnostic contract before deriving new summaries."""
import random
import shutil
import subprocess
import unittest
import numpy as np
from t016_p0.integrity import check_file, verify_packet
from t016_p4.common import *
from t016_p4.data import input_bindings

def main():
    random.seed(SEED);np.random.seed(SEED)
    if (OUT/'execution-freeze.json').exists() or (OUT/'diagnosis.json').exists():raise FileExistsError('Preserve issued evidence')
    stage('preflight','Synthetic arithmetic checks and immutable packet bindings before diagnosis')
    suite=unittest.defaultTestLoader.discover(str(WORK/'t016_p4'),'test*.py',top_level_dir=str(WORK))
    with (OUT/'fixture-results.log').open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    dump(OUT/'fixture-results.json',{'utc':now(),'tests':result.testsRun,'passed':result.wasSuccessful(),
        'failures':len(result.failures),'errors':len(result.errors),'new_summaries_before_tests':0,'new_fits':0})
    assert result.wasSuccessful()
    packets=[]
    for root,expected in PACKETS.items():
        entries=verify_json_packet(root,expected) if root in (R029,R031) else verify_packet(root,expected)
        packets.append({'root':str(root),'manifest_sha256':expected,'members_checked':len(entries)})
    runtime=read(R029/'runtime-identity.json')
    for entry in runtime['library_files']:check_file(entry['path'],entry['sha256'])
    check_file(runtime['executable'],runtime['executable_sha256'])
    shutil.copyfile(R029/'runtime-identity.json',OUT/'runtime-identity.json')
    bindings=input_bindings()
    for record in bindings:check_file(record['path'],record['sha256'])
    contract={'operation':'D042:T016:fixed-output-diagnosis','experiment':'E264','frozen_utc':now(),
        'dates':DATES,'groups':GROUPS,'families':FAMILIES,'methods':METHODS,'contrasts':CONTRASTS,
        'seed':SEED,'input_bindings':bindings,'accepted_packets':packets,'class_order':['F','A','N'],
        'population':'Exactly accepted scored event IDs/labels for daily and downstream group diagnostics; all recorded deduplicated current-target rows before censoring for separately labeled full auxiliary diagnostics',
        'loss':'L_i=0.5*sum_k(p_ik-1[y_i=k])**2; contrasts are differences on identical event IDs; positive P-C/R-C means first arm worse',
        'raw_endpoints':{'equal_day':'Row weight1/(D*n_date) inside each ORIGINAL temporal group and family',
            'pooled':'Row weight1/N inside each ORIGINAL temporal group and family; no merged seven-date headline'},
        'profiles':'q_k=sum_i w_i*1[y_i=k]; ell_k=sum_i w_i*L_i*1[y_i=k]/q_k; total=sum_k q_k*ell_k. Daily row weights1/n_date. Same profile for signed contrast losses.',
        'change_decomposition':{'order':'Class mix first, holding earlier May-Jul conditional losses fixed; then conditional losses under later Aug-Nov class mixture',
            'mix_k':'(q_later,k-q_earlier,k)*ell_earlier,k',
            'within_k':'q_later,k*(ell_later,k-ell_earlier,k)',
            'reconciliation':'later_total-earlier_total=sum(mix_k)+sum(within_k)',
            'absence':'Attribution requires all three conditionals in BOTH groups; otherwise raw change retained and all attribution components unavailable. No imputation, partial allocation or arbitrary zero.',
            'interpretation':'Order-dependent observed arithmetic allocation, not population or causal attribution; conditional loss also mixes dates and feature distributions within class'},
        'secondary_standardization':{'weights':{'breakout':[230/675,87/675,358/675],'rebound':[44/597,276/597,277/597]},
            'origin':'Exact frozen February/March training frequency; not tuned on evaluation labels',
            'formula':'S=sum_k training_frequency_k*ell_k',
            'absence':'Unavailable if any positive-weight class has no conditional support; show all class counts',
            'group_semantics':'Apply to the group profile for each original endpoint. NOT the arithmetic mean of daily standardized scores.',
            'interpretation':'Retrospective diagnostic under an artificial fixed class mixture; never a deployment score or replacement primary endpoint'},
        'weighting_gap':'Pooled minus equal-day = sum_dates (n_date/N - 1/D)*daily_mean_loss; retain every date contribution for every method and contrast',
        'auxiliary':{'full':'All deduplicated current-target rows on seven dates, including future-censored rows; RMSE/MAE seven coordinates, frozen Jan-Mar mean baseline, unchanged marginal range checks',
            'matched':'Separately repeat seven-coordinate RMSE/MAE/range diagnostics on EXACT scored family/date events aligned to P-C differences; labels never define a subset',
            'relation':'Display all seven date points; no correlation significance, regression, selected target or causal claim. RMSE ratios versus frozen target mean require nonzero baseline; zero denominator unavailable.',
            'range':'Any first4log1p predictions<0,abs(imbalance)>1,or distances<0; finite values not clipped; not full physical realizability'},
        'examples':'First chronological scored event per family/date, tie event_id; fourteen fixed examples with saved input7, target7, auxiliary7, all original probability vectors and loss decomposition; originals preserved as inputs',
        'plots':['Main: raw daily C/P/R/frequency alongside fixed-class-mixture daily diagnostic, both families, seven dates, temporal boundary visible',
            'Class composition and class-conditional-loss heatmaps: all three classes, dates, arms/references',
            'Exact temporal-change components: raw loss and predefined contrasts, both endpoints/families',
            'Weighting-gap date contributions: both temporal groups, all methods/contrasts',
            'Auxiliary matched-population seven-coordinate RMSE ratios, range rate and P-C daily loss; all fourteen family/date rows'],
        'tables':['All daily class counts/conditionals/raw/standardized losses, all eight methods',
            'Original earlier/later equal-day and pooled scores plus labeled group diagnostics',
            'All predefined per-class mix/within terms and reconciliation residuals',
            'All date-weight contributions; auxiliary full and matched-population counts/errors/ranges; fourteen fixed examples'],
        'unavailable_policy':'Retain every date, family and reference; missing class support unavailable in the affected diagnostic, never imputed or silently reweighted',
        'prohibited':['source extraction/acquisition','fit/solver','model inference/deserialization','recalibration/clipping','model/date/threshold/label/window search','CI/p-value/population/causal attribution','retirement/trading utility/original goal closure'],
        'source_boundary':'Final accepted R031/RV029 normalized-input admission governs; no raw-source or participant expansion. Original Q17January2026 failure and December exclusions unchanged.',
        'budget':{'logical_cpus':[16,17],'memory_bytes':8*1024**3,'new_fits':0,'training_seconds':0,'watchdog_seconds':3600}}
    dump(OUT/'diagnostic-contract.json',contract)
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=WORK,text=True).strip()
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=WORK,text=True).strip()
    code=[]
    for folder in ('t016_p0','t016_p1','t016_p2','t016_p3','t016_p4'):
        for path in sorted((WORK/folder).glob('*.py')):
            rel=path.relative_to(WORK).as_posix();blob=subprocess.check_output(['git','show',head+':'+rel],cwd=WORK)
            assert path.read_bytes()==blob
            dest=OUT/'code'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
            code.append({'path':rel,'sha256':sha(path)})
    files=['diagnostic-contract.json','diagnostic-method-review.md','runtime-identity.json','bounded_job.py','run_p4-diagnosis_job.py','run_p4-diagnosis.sh']
    dump(OUT/'execution-freeze.json',{'frozen_utc':now(),'base_commit':'33b4382facb2e0b8067b49c1c4c25f3c589f8d56',
        'execution_commit':head,'code':code,'files':[{'path':name,'sha256':sha(OUT/name)} for name in files],
        'new_summaries_before_freeze':0,'new_fits':0})
    (OUT/'execution-freeze.sha256').write_text(sha(OUT/'execution-freeze.json')+'\n')
    dump(OUT/'input-integrity.json',{'utc':now(),'bindings':bindings,'accepted_packets':packets,'all_passed':True})
    stage('freeze-complete','All populations, diagnostics and executable bound; no new summaries derived')

if __name__=='__main__':main()
