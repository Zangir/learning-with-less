"""One recorded attempt per authorized estimator; no retry path."""
import pickle
import random
import time
import traceback
import warnings
import numpy as np
import psutil
from sklearn.exceptions import ConvergenceWarning
from t016_p2.common import OUT, dump, now, sha, stage


class FitLedger:
    def __init__(self, plan):
        self.plan = {entry['fit_id']: entry for entry in plan}
        self.attempted = set()
        self.path = OUT / 'fit-ledger.jsonl'
        if self.path.exists():
            raise ValueError('A fit ledger already exists; preserve attempts, never silently rerun')
        self.process = psutil.Process()

    def append(self, record):
        import json
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, allow_nan=False) + '\n')

    def fit_once(self, specification, estimator, X, y):
        identifier = specification['fit_id']
        if identifier in self.attempted or identifier not in self.plan or len(self.attempted) >= 39:
            raise ValueError('Fit identity/budget violation')
        if estimator.get_params() != specification['parameters']:
            raise ValueError('Estimator parameters differ from prospective freeze')
        if not np.isfinite(X).all() or not np.isfinite(y).all():
            raise ValueError('Nonfinite fit inputs must be blocked before fitting')
        self.attempted.add(identifier)
        random.seed(specification['seed']); np.random.seed(specification['seed'])
        folder = OUT / 'models' / identifier
        folder.mkdir(parents=True)
        began, wall, cpu = now(), time.perf_counter(), time.process_time()
        record = {'fit_id': identifier, 'kind': specification['kind'], 'seed': specification['seed'],
            'started_utc': began, 'status': 'started', 'rows': len(X), 'columns': X.shape[1],
            'target_columns': y.shape[1] if y.ndim == 2 else 1,
            'parameters': estimator.get_params(), 'sample_weights': 'all ones',
            'rss_before_bytes': self.process.memory_info().rss, 'attempt_number': len(self.attempted)}
        self.append(record)
        stage('fit-start', f'{len(self.attempted)}/39 {identifier}: {len(X)} x {X.shape[1]}')
        captured, error, fitted = [], None, False
        try:
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter('always')
                estimator.fit(X, y, sample_weight=np.ones(len(X)))
            fitted = True
        except Exception:
            error = traceback.format_exc()
            (folder / 'exception.txt').write_text(error, encoding='utf-8')
        caught = [{'category': w.category.__name__, 'message': str(w.message),
            'fatal_for_evaluation': issubclass(w.category, (ConvergenceWarning, RuntimeWarning))
                or w.category.__name__ == 'LinAlgWarning'} for w in captured]
        elapsed, consumed = time.perf_counter() - wall, time.process_time() - cpu
        valid = fitted and not any(w['fatal_for_evaluation'] for w in caught)
        record.update(status='evaluable' if valid else 'not_evaluable', finished_utc=now(),
            fit_wall_seconds=elapsed, fit_cpu_seconds=consumed, warnings=caught,
            failure_reason='fit_exception' if error else 'convergence_or_numerical_warning' if not valid else None,
            returned_fitted_estimator=fitted, rss_after_bytes=self.process.memory_info().rss,
            process_peak_working_set_bytes=getattr(self.process.memory_info(), 'peak_wset', None))
        if fitted:
            with (folder / 'estimator.pkl').open('wb') as stream:
                pickle.dump(estimator, stream, protocol=5)
            record['estimator_sha256'] = sha(folder / 'estimator.pkl')
            iterations = getattr(estimator, 'n_iter_', None)
            record['n_iter'] = np.asarray(iterations).tolist() if iterations is not None else None
        dump(folder / 'fit.json', record)
        self.append(record)
        stage('fit-finished', f'{identifier}: {record["status"]}; {elapsed:.3f}s wall / {consumed:.3f}s CPU')
        return estimator if fitted else None, record
