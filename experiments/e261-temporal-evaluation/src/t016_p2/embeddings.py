"""No-fit C-in-R checks for the frozen scikit-learn 1.7.2 comparison.

Inputs are already scaled by their permitted training-only scalers. This module
neither fits preprocessing nor calls an estimator's fit method.
"""
from copy import deepcopy
from hashlib import sha256

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

COARSE_WIDTH = 446
RICH_WIDTH = 1910
ALIGNMENT_ATOL = 1e-12
ALIGNMENT_RTOL = 1e-12
PROBABILITY_ATOL = 1e-10


def _array_hash(value):
    value = np.ascontiguousarray(value)
    digest = sha256(str((value.dtype.descr, value.shape)).encode())
    digest.update(value.tobytes())
    return digest.hexdigest()


def embed_coarse_model(model):
    """Return a copied rich-layout estimator and its JSON-safe identity record.

    The frozen rich layout is [X446, Z1464], so the tree feature-index map is
    identity. Numeric raw-value HGB prediction uses only indices in frozen nodes;
    its original fitted bin mapper is retained, never fitted or expanded.
    """
    if sklearn.__version__ != "1.7.2":
        raise RuntimeError("Private HGB embedding is pinned to scikit-learn 1.7.2")
    if not isinstance(model, (LogisticRegression, HistGradientBoostingClassifier)):
        raise TypeError("Only frozen logistic and histogram boosting models are supported")
    if model.n_features_in_ != COARSE_WIDTH or len(model.classes_) != 3:
        raise ValueError("Expected fitted coarse446 and three-class estimator")
    if hasattr(model, "feature_names_in_"):
        raise ValueError("The frozen comparison requires indexed numeric ndarray inputs")

    embedded = deepcopy(model)
    embedded.n_features_in_ = RICH_WIDTH
    description = {
        "sklearn_version": sklearn.__version__, "fit_calls": 0,
        "coarse_width": COARSE_WIDTH, "rich_width": RICH_WIDTH,
        "class_order": model.classes_.tolist(),
        "feature_index_map": "identity: coarse columns 0..445 are rich columns 0..445",
    }

    if isinstance(model, LogisticRegression):
        if model.coef_.shape != (3, COARSE_WIDTH) or model.intercept_.shape != (3,):
            raise ValueError("Expected three-row multinomial coefficients and intercepts")
        if model.solver != "lbfgs" or model.multi_class == "ovr":
            raise ValueError("Expected frozen lbfgs multinomial logistic model")
        embedded.coef_ = np.zeros((3, RICH_WIDTH), dtype=model.coef_.dtype)
        embedded.coef_[:, :COARSE_WIDTH] = model.coef_
        description.update(
            method="copy fitted coefficients/intercepts; zero every added-depth coefficient",
            coarse_coefficients_sha256=_array_hash(model.coef_),
            embedded_prefix_coefficients_sha256=_array_hash(embedded.coef_[:, :COARSE_WIDTH]),
            embedded_coefficients_sha256=_array_hash(embedded.coef_),
            intercept_sha256=_array_hash(embedded.intercept_),
            added_depth_nonzero_coefficients=int(np.count_nonzero(embedded.coef_[:, COARSE_WIDTH:])),
        )
    else:
        if getattr(model, "_in_fit", False):
            raise ValueError("Cannot embed an HGB estimator while it is fitting")
        if model._preprocessor is not None or np.any(model.is_categorical_):
            raise ValueError("The frozen embedding supports numeric, unremapped HGB inputs only")
        node_hashes, split_features, node_count = [], set(), 0
        for original_iteration, copied_iteration in zip(model._predictors, embedded._predictors):
            for original, copied in zip(original_iteration, copied_iteration):
                splits = original.nodes[original.nodes["is_leaf"] == 0]
                if np.any(splits["is_categorical"]):
                    raise ValueError("Categorical tree splits are outside the frozen schema")
                indices = splits["feature_idx"]
                if np.any(indices < 0) or np.any(indices >= COARSE_WIDTH):
                    raise ValueError("A coarse split references a non-coarse feature")
                split_features.update(int(index) for index in indices)
                before_hash, after_hash = _array_hash(original.nodes), _array_hash(copied.nodes)
                if before_hash != after_hash:
                    raise AssertionError("Embedding changed a frozen tree node")
                node_hashes.append(before_hash)
                node_count += len(original.nodes)
        # The added columns get a seat, but none of the frozen trees asks them a question.
        embedded._n_features = RICH_WIDTH
        description.update(
            method="copy frozen trees; preserve identity-mapped feature indices and raw thresholds",
            tree_count=len(node_hashes), node_count=node_count,
            used_coarse_feature_indices=sorted(split_features),
            original_and_embedded_tree_node_sha256=node_hashes,
            baseline_prediction_sha256=_array_hash(embedded._baseline_prediction),
            bin_mapper="original fitted mapper retained; predict_proba uses raw numeric thresholds",
        )
    return embedded, description


def check_embedding(model, X_coarse, X_rich):
    """Compare original446 and embedded1910 probabilities without any fitting.

    Call separately on the downstream training rows and April selection rows.
    Row identifiers, class mapping and scaler identities are also checked by the
    caller; this function verifies the actual shared numeric prefix and outputs.
    Malformed/misaligned inputs raise; a finite probability tolerance failure is
    returned as passed=False so the caller can retain the diagnostic evidence.
    """
    coarse, rich = np.asarray(X_coarse), np.asarray(X_rich)
    if (coarse.ndim != 2 or rich.ndim != 2 or coarse.shape[0] != rich.shape[0]
            or not coarse.shape[0] or coarse.shape[1] != COARSE_WIDTH or rich.shape[1] != RICH_WIDTH):
        raise ValueError("Expected matched nonempty (n,446) and (n,1910) matrices")
    if coarse.dtype != np.float64 or rich.dtype != np.float64:
        raise ValueError("Frozen embedding inputs must be float64")
    if not np.isfinite(coarse).all() or not np.isfinite(rich).all():
        raise ValueError("Nonfinite embedding input")
    shared = rich[:, :COARSE_WIDTH]
    if not np.allclose(coarse, shared, atol=ALIGNMENT_ATOL, rtol=ALIGNMENT_RTOL):
        raise ValueError("Rich shared-X prefix disagrees with coarse training-scaled coordinates")

    embedded, description = embed_coarse_model(model)
    original_probabilities = np.asarray(model.predict_proba(coarse))
    embedded_probabilities = np.asarray(embedded.predict_proba(rich))
    for probabilities in (original_probabilities, embedded_probabilities):
        if probabilities.shape != (len(coarse), 3) or not np.isfinite(probabilities).all():
            raise ValueError("Nonfinite or malformed three-class probabilities")
        if (np.any(probabilities < 0) or np.any(probabilities > 1)
                or not np.allclose(probabilities.sum(axis=1), 1., atol=1e-12, rtol=1e-12)):
            raise ValueError("Invalid class probabilities")
    difference = float(np.max(np.abs(original_probabilities - embedded_probabilities)))
    return {
        "passed": difference <= PROBABILITY_ATOL,
        "rows": len(coarse), "max_abs_probability_difference": difference,
        "probability_tolerance": PROBABILITY_ATOL,
        "shared_x_max_abs_difference": float(np.max(np.abs(coarse - shared))),
        "shared_x_atol": ALIGNMENT_ATOL, "shared_x_rtol": ALIGNMENT_RTOL,
        "original_probability_sha256": _array_hash(original_probabilities),
        "embedded_probability_sha256": _array_hash(embedded_probabilities),
        "embedding": description,
    }
