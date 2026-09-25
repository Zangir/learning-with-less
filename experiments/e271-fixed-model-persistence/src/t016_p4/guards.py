"""Block learning, linear solvers and model deserialization in output-only diagnosis."""
import pickle
import numpy as np
import scipy.linalg
from t016_p3.fixed_inference import install_fit_guards

_LEDGER=None
def install_guards():
    global _LEDGER
    fits=install_fit_guards()
    if _LEDGER is not None:return _LEDGER
    _LEDGER={'fit_guard':fits,'forbidden_calls':[],'guards':[],'new_fits':0,'model_inference_calls':0,'solver_calls':0}
    def forbidden(name):
        def stop(*args,**kwargs):
            _LEDGER['forbidden_calls'].append(name)
            raise RuntimeError('Output-only diagnosis forbids '+name)
        return stop
    for module,names in [(np.linalg,('solve','lstsq','pinv','inv')),
        (scipy.linalg,('solve','lstsq','pinv','inv','cho_solve','solve_triangular')),
        (pickle,('load','loads'))]:
        for name in names:
            label=module.__name__+'.'+name
            setattr(module,name,forbidden(label));_LEDGER['guards'].append(label)
    return _LEDGER
