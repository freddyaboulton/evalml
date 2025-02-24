import inspect

import numpy as np
import pandas as pd
import pytest

from evalml.exceptions import MissingComponentError
from evalml.model_family import ModelFamily
from evalml.pipelines import (
    BinaryClassificationPipeline,
    MulticlassClassificationPipeline,
    RegressionPipeline,
)
from evalml.pipelines.components import ComponentBase, RandomForestClassifier
from evalml.pipelines.components.utils import (
    _all_estimators,
    all_components,
    handle_component_class,
    make_balancing_dictionary,
    scikit_learn_wrapped_estimator,
)
from evalml.problem_types import ProblemTypes

binary = pd.Series([0] * 800 + [1] * 200)
multiclass = pd.Series([0] * 800 + [1] * 150 + [2] * 50)


def test_all_components(
    has_minimal_dependencies,
    is_running_py_39_or_above,
    is_using_conda,
    is_using_windows,
):
    # The total number of minimal components is 42
    # The total number of components is 54
    # Depending on the environment the detrender/Arima and/or Prophet will not be installed

    if has_minimal_dependencies:
        n_components = 43
    elif is_using_conda:
        # No prophet and no arima
        n_components = 52
    elif is_using_windows and not is_running_py_39_or_above:
        # No prophet
        n_components = 53
    elif is_using_windows and is_running_py_39_or_above:
        # No detrender, no arima, no prophet
        n_components = 51
    elif not is_using_windows and is_running_py_39_or_above:
        # No detrender or arima
        n_components = 52
    else:
        n_components = 54
    assert len(all_components()) == n_components


def test_handle_component_class_names():
    for cls in all_components():
        cls_ret = handle_component_class(cls)
        assert inspect.isclass(cls_ret)
        assert issubclass(cls_ret, ComponentBase)
        name_ret = handle_component_class(cls.name)
        assert inspect.isclass(name_ret)
        assert issubclass(name_ret, ComponentBase)

    invalid_name = "This Component Does Not Exist"
    with pytest.raises(
        MissingComponentError,
        match='Component "This Component Does Not Exist" was not found',
    ):
        handle_component_class(invalid_name)

    class NonComponent:
        pass

    with pytest.raises(ValueError):
        handle_component_class(NonComponent())


def test_scikit_learn_wrapper_invalid_problem_type():
    evalml_pipeline = MulticlassClassificationPipeline([RandomForestClassifier])
    evalml_pipeline.problem_type = None
    with pytest.raises(
        ValueError, match="Could not wrap EvalML object in scikit-learn wrapper."
    ):
        scikit_learn_wrapped_estimator(evalml_pipeline)


def test_scikit_learn_wrapper(X_y_binary, X_y_multi, X_y_regression, ts_data):
    for estimator in [
        estimator
        for estimator in _all_estimators()
        if estimator.model_family != ModelFamily.ENSEMBLE
    ]:
        for problem_type in estimator.supported_problem_types:
            if problem_type == ProblemTypes.BINARY:
                X, y = X_y_binary
                num_classes = 2
                pipeline_class = BinaryClassificationPipeline
            elif problem_type == ProblemTypes.MULTICLASS:
                X, y = X_y_multi
                num_classes = 3
                pipeline_class = MulticlassClassificationPipeline
            elif problem_type == ProblemTypes.REGRESSION:
                X, y = X_y_regression
                pipeline_class = RegressionPipeline

            elif problem_type in [
                ProblemTypes.TIME_SERIES_REGRESSION,
                ProblemTypes.TIME_SERIES_MULTICLASS,
                ProblemTypes.TIME_SERIES_BINARY,
            ]:
                continue

            evalml_pipeline = pipeline_class([estimator])
            scikit_estimator = scikit_learn_wrapped_estimator(evalml_pipeline)
            scikit_estimator.fit(X, y)
            y_pred = scikit_estimator.predict(X)
            assert len(y_pred) == len(y)
            assert not np.isnan(y_pred).all()
            if problem_type in [ProblemTypes.BINARY, ProblemTypes.MULTICLASS]:
                y_pred_proba = scikit_estimator.predict_proba(X)
                assert y_pred_proba.shape == (len(y), num_classes)
                assert not np.isnan(y_pred_proba).all().all()


def test_make_balancing_dictionary_errors():
    with pytest.raises(ValueError, match="Sampling ratio must be in range"):
        make_balancing_dictionary(pd.Series([1]), 0)

    with pytest.raises(ValueError, match="Sampling ratio must be in range"):
        make_balancing_dictionary(pd.Series([1]), 1.1)

    with pytest.raises(ValueError, match="Sampling ratio must be in range"):
        make_balancing_dictionary(pd.Series([1]), -1)

    with pytest.raises(ValueError, match="Target data must not be empty"):
        make_balancing_dictionary(pd.Series([]), 0.5)


@pytest.mark.parametrize(
    "y,sampling_ratio,result",
    [
        (binary, 1, {0: 800, 1: 800}),
        (binary, 0.5, {0: 800, 1: 400}),
        (binary, 0.25, {0: 800, 1: 200}),
        (binary, 0.1, {0: 800, 1: 200}),
        (multiclass, 1, {0: 800, 1: 800, 2: 800}),
        (multiclass, 0.5, {0: 800, 1: 400, 2: 400}),
        (multiclass, 0.25, {0: 800, 1: 200, 2: 200}),
        (multiclass, 0.1, {0: 800, 1: 150, 2: 80}),
        (multiclass, 0.01, {0: 800, 1: 150, 2: 50}),
    ],
)
def test_make_balancing_dictionary(y, sampling_ratio, result):
    dic = make_balancing_dictionary(y, sampling_ratio)
    assert dic == result
