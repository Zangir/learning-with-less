"""Inference permits verified deserialization; fitting and solvers stay blocked."""
import numpy as np
import scipy.linalg
from t016_p3.fixed_inference import install_fit_guards

def install():
    ledger = {'fit_guard':install_fit_guards(), 'solver_attempts':[], 'solver_calls':0}
    def block(name):
        def forbidden(*args, **kwargs):
            ledger['solver_attempts'].append(name)
            raise RuntimeError('E271 forbids solver calls: '+name)
        return forbidden
    for module,names in [(np.linalg,('solve','lstsq','pinv','inv')),
                         (scipy.linalg,('solve','lstsq','pinv','inv','cho_solve','solve_triangular'))]:
        for name in names:
            setattr(module,name,block(module.__name__+'.'+name))
    return ledger
