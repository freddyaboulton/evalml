from unittest.mock import patch

import numpy as np
import pytest
from skopt.space import Categorical, Integer, Real

from evalml.automl.automl_algorithm import (
    AutoMLAlgorithmException,
    IterativeAlgorithm,
)
from evalml.model_family import ModelFamily
from evalml.pipelines import (
    BinaryClassificationPipeline,
    Estimator,
    StackedEnsembleClassifier,
    StackedEnsembleRegressor,
)
from evalml.pipelines.components.utils import get_estimators
from evalml.pipelines.utils import make_pipeline
from evalml.problem_types import ProblemTypes


@pytest.fixture
def dummy_binary_pipeline_classes():
    def _method(hyperparameters=["default", "other"]):
        class MockEstimator(Estimator):
            name = "Mock Classifier"
            model_family = ModelFamily.RANDOM_FOREST
            supported_problem_types = [ProblemTypes.BINARY, ProblemTypes.MULTICLASS]
            if isinstance(hyperparameters, (list, tuple, Real, Categorical, Integer)):
                hyperparameter_ranges = {"dummy_parameter": hyperparameters}
            else:
                hyperparameter_ranges = {"dummy_parameter": [hyperparameters]}

            def __init__(
                self, dummy_parameter="default", n_jobs=-1, random_seed=0, **kwargs
            ):
                super().__init__(
                    parameters={
                        "dummy_parameter": dummy_parameter,
                        **kwargs,
                        "n_jobs": n_jobs,
                    },
                    component_obj=None,
                    random_seed=random_seed,
                )

        allowed_component_graphs = {
            "graph_1": [MockEstimator],
            "graph_2": [MockEstimator],
            "graph_3": [MockEstimator],
        }
        return [
            BinaryClassificationPipeline([MockEstimator]),
            BinaryClassificationPipeline([MockEstimator]),
            BinaryClassificationPipeline([MockEstimator]),
        ], allowed_component_graphs

    return _method


def test_iterative_algorithm_init(
    X_y_binary,
):
    X, y = X_y_binary

    algo = IterativeAlgorithm(X=X, y=y, problem_type="binary")
    assert algo.pipeline_number == 0
    assert algo.batch_number == 0

    estimators = get_estimators("binary")
    assert len(algo.allowed_pipelines) == len(
        [
            make_pipeline(
                X,
                y,
                estimator,
                "binary",
            )
            for estimator in estimators
        ]
    )


def test_make_iterative_algorithm_custom_hyperparameters_error(
    dummy_binary_pipeline_classes, X_y_binary
):
    (
        dummy_binary_pipeline_classes,
        allowed_component_graphs,
    ) = dummy_binary_pipeline_classes()
    X, y = X_y_binary

    custom_hyperparameters = [
        {"Imputer": {"numeric_imput_strategy": ["median"]}},
        {"One Hot Encoder": {"value1": ["value2"]}},
    ]

    with pytest.raises(
        ValueError, match="If custom_hyperparameters provided, must be of type dict"
    ):
        IterativeAlgorithm(
            X=X,
            y=y,
            problem_type="binary",
            allowed_component_graphs=allowed_component_graphs,
            custom_hyperparameters=custom_hyperparameters,
        )


def test_iterative_algorithm_allowed_pipelines(
    X_y_binary, dummy_binary_pipeline_classes
):
    X, y = X_y_binary

    (
        dummy_binary_pipeline_classes,
        allowed_component_graphs,
    ) = dummy_binary_pipeline_classes()
    algo = IterativeAlgorithm(
        X=X,
        y=y,
        problem_type="binary",
        allowed_component_graphs=allowed_component_graphs,
    )
    assert algo.pipeline_number == 0
    assert algo.batch_number == 0
    assert algo.allowed_pipelines == dummy_binary_pipeline_classes


def test_iterative_algorithm_empty(X_y_binary, dummy_binary_pipeline_classes):
    X, y = X_y_binary

    (
        dummy_binary_pipeline_classes,
        allowed_component_graphs,
    ) = dummy_binary_pipeline_classes()

    with pytest.raises(ValueError, match="No allowed pipelines to search"):
        IterativeAlgorithm(X=X, y=y, problem_type="binary", allowed_component_graphs={})

    algo = IterativeAlgorithm(
        X=X,
        y=y,
        problem_type="binary",
        allowed_component_graphs=allowed_component_graphs,
    )
    algo.allowed_pipelines = []
    assert algo.pipeline_number == 0
    assert algo.batch_number == 0
    assert algo.allowed_pipelines == []

    next_batch = algo.next_batch()
    assert [p.__class__ for p in next_batch] == []
    assert algo.pipeline_number == 0
    assert algo.batch_number == 1

    with pytest.raises(
        AutoMLAlgorithmException, match="No results were reported from the first batch"
    ):
        algo.next_batch()
    assert algo.batch_number == 1
    assert algo.pipeline_number == 0


@pytest.mark.parametrize("ensembling_value", [True, False])
@patch("evalml.tuners.skopt_tuner.Optimizer.tell")
def test_iterative_algorithm_results(
    mock_opt_tell,
    ensembling_value,
    dummy_binary_pipeline_classes,
    X_y_binary,
):
    X, y = X_y_binary

    (
        dummy_binary_pipeline_classes,
        allowed_component_graphs,
    ) = dummy_binary_pipeline_classes()

    algo = IterativeAlgorithm(
        X=X,
        y=y,
        problem_type="binary",
        allowed_component_graphs=allowed_component_graphs,
        ensembling=ensembling_value,
    )
    assert algo.pipeline_number == 0
    assert algo.batch_number == 0
    assert algo.allowed_pipelines == dummy_binary_pipeline_classes

    # initial batch contains one of each pipeline, with default parameters
    next_batch = algo.next_batch()
    assert len(next_batch) == len(dummy_binary_pipeline_classes)
    assert [p.__class__ for p in next_batch] == [
        p.__class__ for p in dummy_binary_pipeline_classes
    ]
    assert algo.pipeline_number == len(dummy_binary_pipeline_classes)
    assert algo.batch_number == 1
    assert all(
        [p.parameters == p.component_graph.default_parameters for p in next_batch]
    )
    # the "best" score will be the 1st dummy pipeline
    scores = np.arange(0, len(next_batch))
    for score, pipeline in zip(scores, next_batch):
        algo.add_result(score, pipeline, {"id": algo.pipeline_number})

    # subsequent batches contain pipelines_per_batch copies of one pipeline, moving from best to worst from the first batch
    last_batch_number = algo.batch_number
    last_pipeline_number = algo.pipeline_number
    all_parameters = []

    for i in range(1, 5):
        for _ in range(len(dummy_binary_pipeline_classes)):
            next_batch = algo.next_batch()
            assert len(next_batch) == algo.pipelines_per_batch
            num_pipelines_classes = (
                (len(dummy_binary_pipeline_classes) + 1)
                if ensembling_value
                else len(dummy_binary_pipeline_classes)
            )
            cls = dummy_binary_pipeline_classes[
                (algo.batch_number - 2) % num_pipelines_classes
            ].__class__
            assert [p.__class__ for p in next_batch] == [cls] * len(next_batch)
            assert all(
                [p.parameters["Mock Classifier"]["n_jobs"] == -1 for p in next_batch]
            )
            assert all((p.random_seed == algo.random_seed) for p in next_batch)
            assert algo.pipeline_number == last_pipeline_number + len(next_batch)
            last_pipeline_number = algo.pipeline_number
            assert algo.batch_number == last_batch_number + 1
            last_batch_number = algo.batch_number
            all_parameters.extend([p.parameters for p in next_batch])
            scores = -np.arange(0, len(next_batch))
            for score, pipeline in zip(scores, next_batch):
                algo.add_result(score, pipeline, {"id": algo.pipeline_number})

        assert any(
            [p != dummy_binary_pipeline_classes[0].parameters for p in all_parameters]
        )

        if ensembling_value:
            # check next batch is stacking ensemble batch
            assert algo.batch_number == (len(dummy_binary_pipeline_classes) + 1) * i
            next_batch = algo.next_batch()
            assert len(next_batch) == 1
            assert algo.batch_number == last_batch_number + 1
            last_batch_number = algo.batch_number
            assert algo.pipeline_number == last_pipeline_number + 1
            last_pipeline_number = algo.pipeline_number
            scores = np.arange(0, len(next_batch))
            for score, pipeline in zip(scores, next_batch):
                algo.add_result(score, pipeline, {"id": algo.pipeline_number})
            assert pipeline.model_family == ModelFamily.ENSEMBLE
            assert pipeline.random_seed == algo.random_seed
            estimators_used_in_ensemble = pipeline.component_graph.get_estimators()
            random_seeds_the_same = [
                (estimator.random_seed == algo.random_seed)
                for estimator in estimators_used_in_ensemble
            ]
            assert all(random_seeds_the_same)
            assert ModelFamily.ENSEMBLE not in algo._best_pipeline_info


@patch("evalml.tuners.skopt_tuner.Optimizer.tell")
def test_iterative_algorithm_passes_pipeline_params(
    mock_opt_tell,
    X_y_binary,
    dummy_binary_pipeline_classes,
):
    X, y = X_y_binary

    (
        dummy_binary_pipeline_classes,
        allowed_component_graphs,
    ) = dummy_binary_pipeline_classes()
    algo = IterativeAlgorithm(
        X=X,
        y=y,
        problem_type="binary",
        allowed_component_graphs=allowed_component_graphs,
        pipeline_params={
            "pipeline": {"gap": 2, "max_delay": 10, "forecast_horizon": 3}
        },
    )

    next_batch = algo.next_batch()
    assert all(
        [
            p.parameters["pipeline"]
            == {"gap": 2, "max_delay": 10, "forecast_horizon": 3}
            for p in next_batch
        ]
    )

    # the "best" score will be the 1st dummy pipeline
    scores = np.arange(0, len(next_batch))
    for score, pipeline in zip(scores, next_batch):
        algo.add_result(score, pipeline, {"id": algo.pipeline_number})

    for i in range(1, 5):
        for _ in range(len(dummy_binary_pipeline_classes)):
            next_batch = algo.next_batch()
            assert all(
                [
                    p.parameters["pipeline"]
                    == {"gap": 2, "max_delay": 10, "forecast_horizon": 3}
                    for p in next_batch
                ]
            )
            scores = -np.arange(0, len(next_batch))
            for score, pipeline in zip(scores, next_batch):
                algo.add_result(score, pipeline, {"id": algo.pipeline_number})


@patch("evalml.tuners.skopt_tuner.Optimizer.tell")
def test_iterative_algorithm_passes_njobs(
    mock_opt_tell, X_y_binary, dummy_binary_pipeline_classes
):
    X, y = X_y_binary

    (
        dummy_binary_pipeline_classes,
        allowed_component_graphs,
    ) = dummy_binary_pipeline_classes()
    algo = IterativeAlgorithm(
        X=X,
        y=y,
        problem_type="binary",
        allowed_component_graphs=allowed_component_graphs,
        n_jobs=2,
        ensembling=False,
    )
    next_batch = algo.next_batch()

    # the "best" score will be the 1st dummy pipeline
    scores = np.arange(0, len(next_batch))
    for score, pipeline in zip(scores, next_batch):
        algo.add_result(score, pipeline, {"id": algo.pipeline_number})

    for i in range(1, 3):
        for _ in range(len(dummy_binary_pipeline_classes)):
            next_batch = algo.next_batch()
            assert all(
                [p.parameters["Mock Classifier"]["n_jobs"] == 2 for p in next_batch]
            )
            scores = -np.arange(0, len(next_batch))
            for score, pipeline in zip(scores, next_batch):
                algo.add_result(score, pipeline, {"id": algo.pipeline_number})


@patch("evalml.tuners.skopt_tuner.Optimizer.tell")
@pytest.mark.parametrize("is_regression", [True, False])
@pytest.mark.parametrize("estimator", ["XGBoost", "CatBoost"])
def test_iterative_algorithm_passes_n_jobs_catboost_xgboost(
    mock_opt_tell, X_y_binary, X_y_regression, is_regression, estimator
):
    if estimator == "XGBoost":
        pytest.importorskip(
            "xgboost", reason="Skipping test because xgboost is not installed."
        )
    else:
        pytest.importorskip(
            "catboost", reason="Skipping test because catboost is not installed."
        )
    if is_regression:
        X, y = X_y_regression
        component_graphs = {"graph": [f"{estimator} Regressor"]}
        problem_type = "regression"
    else:
        X, y = X_y_binary
        component_graphs = {"graph": [f"{estimator} Classifier"]}
        problem_type = "binary"

    algo = IterativeAlgorithm(
        X=X,
        y=y,
        problem_type=problem_type,
        allowed_component_graphs=component_graphs,
        n_jobs=2,
        ensembling=False,
    )
    next_batch = algo.next_batch()

    # the "best" score will be the 1st dummy pipeline
    scores = np.arange(0, len(next_batch))
    for score, pipeline in zip(scores, next_batch):
        algo.add_result(score, pipeline, {"id": algo.pipeline_number})

    for _ in range(1, 3):
        for _ in range(len(component_graphs)):
            next_batch = algo.next_batch()
            for parameter_values in [list(p.parameters.values()) for p in next_batch]:
                assert parameter_values[0]["n_jobs"] == 2
            scores = -np.arange(0, len(next_batch))
            for score, pipeline in zip(scores, next_batch):
                algo.add_result(score, pipeline, {"id": algo.pipeline_number})


@pytest.mark.parametrize("ensembling_value", [True, False])
def test_iterative_algorithm_one_allowed_pipeline(
    X_y_binary, ensembling_value, dummy_binary_pipeline_classes
):
    X, y = X_y_binary

    (
        dummy_binary_pipeline_classes,
        allowed_component_graphs,
    ) = dummy_binary_pipeline_classes()
    dummy_binary_pipeline_classes = [dummy_binary_pipeline_classes[0]]
    allowed_component_graphs = {"graph_1": allowed_component_graphs["graph_1"]}
    # Checks that when len(allowed_pipeline) == 1, ensembling is not run, even if set to True
    algo = IterativeAlgorithm(
        X=X,
        y=y,
        problem_type="binary",
        allowed_component_graphs=allowed_component_graphs,
        ensembling=ensembling_value,
    )
    assert algo.pipeline_number == 0
    assert algo.batch_number == 0
    assert algo.allowed_pipelines == dummy_binary_pipeline_classes

    # initial batch contains one of each pipeline, with default parameters
    next_batch = algo.next_batch()
    assert len(next_batch) == 1
    assert [p.__class__ for p in next_batch] == [
        p.__class__ for p in dummy_binary_pipeline_classes
    ]
    assert algo.pipeline_number == 1
    assert algo.batch_number == 1
    assert all(
        [p.parameters == p.component_graph.default_parameters for p in next_batch]
    )
    # the "best" score will be the 1st dummy pipeline
    scores = np.arange(0, len(next_batch))
    for score, pipeline in zip(scores, next_batch):
        algo.add_result(score, pipeline, {"id": algo.pipeline_number})

    # subsequent batches contain pipelines_per_batch copies of one pipeline, moving from best to worst from the first batch
    last_batch_number = algo.batch_number
    last_pipeline_number = algo.pipeline_number
    all_parameters = []
    for i in range(1, 5):
        next_batch = algo.next_batch()
        assert len(next_batch) == algo.pipelines_per_batch
        assert all((p.random_seed == algo.random_seed) for p in next_batch)
        assert [p.__class__ for p in next_batch] == [
            dummy_binary_pipeline_classes[0].__class__
        ] * algo.pipelines_per_batch
        assert algo.pipeline_number == last_pipeline_number + len(next_batch)
        last_pipeline_number = algo.pipeline_number
        assert algo.batch_number == last_batch_number + 1
        last_batch_number = algo.batch_number
        all_parameters.extend([p.parameters for p in next_batch])
        scores = -np.arange(0, len(next_batch))
        for score, pipeline in zip(scores, next_batch):
            algo.add_result(score, pipeline, {"id": algo.pipeline_number})

        assert any(
            [
                p
                != dummy_binary_pipeline_classes[0]
                .__class__({})
                .component_graph.default_parameters
                for p in all_parameters
            ]
        )


@pytest.mark.parametrize("text_in_ensembling", [True, False])
@pytest.mark.parametrize("n_jobs", [-1, 0, 1, 2, 3])
def test_iterative_algorithm_stacked_ensemble_n_jobs_binary(
    n_jobs,
    X_y_binary,
    text_in_ensembling,
    dummy_binary_pipeline_classes,
):
    X, y = X_y_binary

    (
        dummy_binary_pipeline_classes,
        allowed_component_graphs,
    ) = dummy_binary_pipeline_classes()

    algo = IterativeAlgorithm(
        X=X,
        y=y,
        problem_type="binary",
        allowed_component_graphs=allowed_component_graphs,
        ensembling=True,
        text_in_ensembling=text_in_ensembling,
        n_jobs=n_jobs,
    )

    next_batch = algo.next_batch()
    seen_ensemble = False
    scores = range(0, len(next_batch))
    for score, pipeline in zip(scores, next_batch):
        algo.add_result(score, pipeline, {"id": algo.pipeline_number})

    for i in range(5):
        next_batch = algo.next_batch()
        for pipeline in next_batch:
            if isinstance(pipeline.estimator, StackedEnsembleClassifier):
                seen_ensemble = True
                if text_in_ensembling:
                    assert (
                        pipeline.parameters["Stacked Ensemble Classifier"]["n_jobs"]
                        == 1
                    )
                else:
                    assert (
                        pipeline.parameters["Stacked Ensemble Classifier"]["n_jobs"]
                        == n_jobs
                    )
    assert seen_ensemble


@pytest.mark.parametrize("text_in_ensembling", [True, False])
@pytest.mark.parametrize("n_jobs", [-1, 0, 1, 2, 3])
def test_iterative_algorithm_stacked_ensemble_n_jobs_regression(
    n_jobs, text_in_ensembling, X_y_regression, linear_regression_pipeline_class
):
    X, y = X_y_regression

    allowed_component_graphs = {
        "graph_1": linear_regression_pipeline_class.component_graph,
        "graph_2": linear_regression_pipeline_class.component_graph,
    }
    algo = IterativeAlgorithm(
        X=X,
        y=y,
        problem_type="regression",
        allowed_component_graphs=allowed_component_graphs,
        ensembling=True,
        text_in_ensembling=text_in_ensembling,
        n_jobs=n_jobs,
    )
    next_batch = algo.next_batch()
    seen_ensemble = False
    scores = range(0, len(next_batch))
    for score, pipeline in zip(scores, next_batch):
        algo.add_result(score, pipeline, {"id": algo.pipeline_number})

    for i in range(5):
        next_batch = algo.next_batch()
        for pipeline in next_batch:
            if isinstance(pipeline.estimator, StackedEnsembleRegressor):
                seen_ensemble = True
                if text_in_ensembling:
                    assert (
                        pipeline.parameters["Stacked Ensemble Regressor"]["n_jobs"] == 1
                    )
                else:
                    assert (
                        pipeline.parameters["Stacked Ensemble Regressor"]["n_jobs"]
                        == n_jobs
                    )
    assert seen_ensemble


@pytest.mark.parametrize(
    "parameters",
    [1, "hello", 1.3, -1.0006, Categorical([1, 3, 4]), Integer(2, 4), Real(2, 6)],
)
def test_iterative_algorithm_pipeline_params(
    X_y_binary,
    parameters,
    dummy_binary_pipeline_classes,
):
    X, y = X_y_binary

    (
        dummy_binary_pipeline_classes,
        allowed_component_graphs,
    ) = dummy_binary_pipeline_classes(parameters)

    if isinstance(parameters, (Categorical, Integer, Real)):
        with pytest.raises(
            ValueError,
            match="Pipeline parameters should not contain skopt.Space variables",
        ):
            IterativeAlgorithm(
                X=X,
                y=y,
                problem_type="binary",
                allowed_component_graphs=allowed_component_graphs,
                random_seed=0,
                pipeline_params={
                    "pipeline": {"gap": 2, "max_delay": 10, "forecast_horizon": 3},
                    "Mock Classifier": {"dummy_parameter": parameters},
                },
            )
        return
    else:
        algo = IterativeAlgorithm(
            X=X,
            y=y,
            problem_type="binary",
            allowed_component_graphs=allowed_component_graphs,
            random_seed=0,
            pipeline_params={
                "pipeline": {"gap": 2, "max_delay": 10, "forecast_horizon": 3},
                "Mock Classifier": {"dummy_parameter": parameters},
            },
        )

    parameter = parameters
    next_batch = algo.next_batch()
    assert all(
        [
            p.parameters["pipeline"]
            == {"gap": 2, "max_delay": 10, "forecast_horizon": 3}
            for p in next_batch
        ]
    )
    assert all(
        [
            p.parameters["Mock Classifier"]
            == {"dummy_parameter": parameter, "n_jobs": -1}
            for p in next_batch
        ]
    )

    scores = np.arange(0, len(next_batch))
    for score, pipeline in zip(scores, next_batch):
        algo.add_result(score, pipeline, {"id": algo.pipeline_number})

    # make sure that future batches have the same parameter value
    for i in range(1, 5):
        next_batch = algo.next_batch()
        assert all(
            [
                p.parameters["Mock Classifier"]["dummy_parameter"] == parameter
                for p in next_batch
            ]
        )


@pytest.mark.parametrize(
    "parameters,hyperparameters",
    [
        (1, Categorical([1, 3, 4])),
        (3, Integer(2, 4)),
        (5, Categorical([1, 3, 4])),
        (1, 1),
    ],
)
def test_iterative_algorithm_custom_hyperparameters(
    parameters,
    hyperparameters,
    X_y_binary,
    dummy_binary_pipeline_classes,
):
    X, y = X_y_binary

    (
        dummy_binary_pipeline_classes,
        allowed_component_graphs,
    ) = dummy_binary_pipeline_classes(parameters)

    if not isinstance(hyperparameters, (Categorical, Integer, Real)):
        with pytest.raises(
            ValueError, match="Custom hyperparameters should only contain skopt"
        ):
            IterativeAlgorithm(
                X=X,
                y=y,
                problem_type="binary",
                allowed_component_graphs=allowed_component_graphs,
                random_seed=0,
                pipeline_params={"Mock Classifier": {"dummy_parameter": parameters}},
                custom_hyperparameters={
                    "Mock Classifier": {"dummy_parameter": hyperparameters}
                },
            )
        return
    else:
        algo = IterativeAlgorithm(
            X=X,
            y=y,
            problem_type="binary",
            allowed_component_graphs=allowed_component_graphs,
            random_seed=0,
            pipeline_params={"Mock Classifier": {"dummy_parameter": parameters}},
            custom_hyperparameters={
                "Mock Classifier": {"dummy_parameter": hyperparameters}
            },
        )

    next_batch = algo.next_batch()

    assert all([p.parameters["Mock Classifier"]["n_jobs"] == -1 for p in next_batch])
    assert all(
        [
            p.parameters["Mock Classifier"]["dummy_parameter"] == parameters
            for p in next_batch
        ]
    )

    scores = np.arange(0, len(next_batch))

    if parameters not in hyperparameters:
        for score, pipeline in zip(scores, next_batch):
            with pytest.raises(ValueError, match="Default parameters for components"):
                algo.add_result(score, pipeline, {"id": algo.pipeline_number})
    else:
        for score, pipeline in zip(scores, next_batch):
            algo.add_result(score, pipeline, {"id": algo.pipeline_number})

        # make sure that future batches remain in the hyperparam range
        all_dummies = set()
        for i in range(1, 5):
            next_batch = algo.next_batch()
            for p in next_batch:
                dummy = p.parameters["Mock Classifier"]["dummy_parameter"]
                if dummy not in all_dummies:
                    all_dummies.add(dummy)
            assert all(
                [
                    p.parameters["Mock Classifier"]["dummy_parameter"]
                    in hyperparameters
                    for p in next_batch
                ]
            )
        assert all_dummies == {1, 3, 4} if parameters == 1 else all_dummies == {2, 3, 4}


def test_iterative_algorithm_pipeline_params_kwargs(
    X_y_binary, dummy_binary_pipeline_classes
):
    X, y = X_y_binary

    (
        dummy_binary_pipeline_classes,
        allowed_component_graphs,
    ) = dummy_binary_pipeline_classes()

    algo = IterativeAlgorithm(
        X=X,
        y=y,
        problem_type="binary",
        allowed_component_graphs=allowed_component_graphs,
        pipeline_params={
            "Mock Classifier": {"dummy_parameter": "dummy", "fake_param": "fake"}
        },
        random_seed=0,
    )

    next_batch = algo.next_batch()
    assert all(
        [
            p.parameters["Mock Classifier"]
            == {"dummy_parameter": "dummy", "n_jobs": -1, "fake_param": "fake"}
            for p in next_batch
        ]
    )


def test_iterative_algorithm_results_best_pipeline_info_id(
    X_y_binary,
    dummy_binary_pipeline_classes,
    logistic_regression_binary_pipeline_class,
):
    X, y = X_y_binary
    LogisticRegressionBinaryPipeline = logistic_regression_binary_pipeline_class
    (
        dummy_binary_pipeline_classes,
        allowed_component_graphs,
    ) = dummy_binary_pipeline_classes()
    allowed_component_graphs = {
        "graph_1": allowed_component_graphs["graph_1"],
        "graph_2": LogisticRegressionBinaryPipeline.component_graph,
    }
    algo = IterativeAlgorithm(
        X=X,
        y=y,
        problem_type="binary",
        allowed_component_graphs=allowed_component_graphs,
    )

    # initial batch contains one of each pipeline, with default parameters
    next_batch = algo.next_batch()
    scores = np.arange(0, len(next_batch))
    for pipeline_num, (score, pipeline) in enumerate(zip(scores, next_batch)):
        algo.add_result(score, pipeline, {"id": algo.pipeline_number + pipeline_num})
    assert algo._best_pipeline_info[ModelFamily.RANDOM_FOREST]["id"] == 3
    assert algo._best_pipeline_info[ModelFamily.LINEAR_MODEL]["id"] == 2

    for i in range(1, 3):
        next_batch = algo.next_batch()
        scores = -np.arange(
            1, len(next_batch)
        )  # Score always gets better with each pipeline
        for pipeline_num, (score, pipeline) in enumerate(zip(scores, next_batch)):
            algo.add_result(
                score, pipeline, {"id": algo.pipeline_number + pipeline_num}
            )
            assert (
                algo._best_pipeline_info[pipeline.model_family]["id"]
                == algo.pipeline_number + pipeline_num
            )


@pytest.mark.parametrize(
    "problem_type",
    [ProblemTypes.REGRESSION, ProblemTypes.BINARY, ProblemTypes.MULTICLASS],
)
def test_iterative_algorithm_first_batch_order(
    problem_type, X_y_binary, has_minimal_dependencies
):
    X, y = X_y_binary

    algo = IterativeAlgorithm(X=X, y=y, problem_type=problem_type)

    # initial batch contains one of each pipeline, with default parameters
    next_batch = algo.next_batch()
    estimators_in_first_batch = [p.estimator.name for p in next_batch]

    if problem_type == ProblemTypes.REGRESSION:
        final_estimators = [
            "XGBoost Regressor",
            "LightGBM Regressor",
            "CatBoost Regressor",
        ]
    else:
        final_estimators = [
            "XGBoost Classifier",
            "LightGBM Classifier",
            "CatBoost Classifier",
        ]
    if has_minimal_dependencies:
        final_estimators = []
    if problem_type == ProblemTypes.REGRESSION:
        assert (
            estimators_in_first_batch
            == [
                "Elastic Net Regressor",
                "Decision Tree Regressor",
                "Extra Trees Regressor",
                "Random Forest Regressor",
            ]
            + final_estimators
        )
    if problem_type == ProblemTypes.BINARY:
        assert (
            estimators_in_first_batch
            == [
                "Elastic Net Classifier",
                "Logistic Regression Classifier",
                "Decision Tree Classifier",
                "Extra Trees Classifier",
                "Random Forest Classifier",
            ]
            + final_estimators
        )
    if problem_type == ProblemTypes.MULTICLASS:
        assert (
            estimators_in_first_batch
            == [
                "Elastic Net Classifier",
                "Logistic Regression Classifier",
                "Decision Tree Classifier",
                "Extra Trees Classifier",
                "Random Forest Classifier",
            ]
            + final_estimators
        )


def test_iterative_algorithm_first_batch_order_param(
    X_y_binary, has_minimal_dependencies
):
    X, y = X_y_binary

    # put random forest first
    estimator_family_order = [
        ModelFamily.RANDOM_FOREST,
        ModelFamily.LINEAR_MODEL,
        ModelFamily.DECISION_TREE,
        ModelFamily.EXTRA_TREES,
        ModelFamily.XGBOOST,
        ModelFamily.LIGHTGBM,
        ModelFamily.CATBOOST,
    ]
    algo = IterativeAlgorithm(
        X=X, y=y, problem_type="binary", _estimator_family_order=estimator_family_order
    )
    next_batch = algo.next_batch()
    estimators_in_first_batch = [p.estimator.name for p in next_batch]

    final_estimators = [
        "XGBoost Classifier",
        "LightGBM Classifier",
        "CatBoost Classifier",
    ]
    if has_minimal_dependencies:
        final_estimators = []
    assert (
        estimators_in_first_batch
        == [
            "Random Forest Classifier",
            "Elastic Net Classifier",
            "Logistic Regression Classifier",
            "Decision Tree Classifier",
            "Extra Trees Classifier",
        ]
        + final_estimators
    )


@pytest.mark.parametrize(
    "sampler",
    ["Undersampler", "Oversampler"],
)
@pytest.mark.parametrize("problem_type", [ProblemTypes.BINARY, ProblemTypes.MULTICLASS])
def test_iterative_algorithm_sampling_params(
    problem_type, sampler, mock_imbalanced_data_X_y, has_minimal_dependencies
):
    if has_minimal_dependencies and sampler != "Undersampler":
        pytest.skip(
            "Minimal dependencies, so we don't test the oversamplers for iterative algorithm"
        )
    X, y = mock_imbalanced_data_X_y(problem_type, "some", "small")
    algo = IterativeAlgorithm(
        X=X,
        y=y,
        problem_type=problem_type,
        random_seed=0,
        sampler_name=sampler,
    )
    next_batch = algo.next_batch()
    for p in next_batch:
        for component in p.component_graph:
            if "sampler" in component.name:
                assert component.parameters["sampling_ratio"] == 0.25

    scores = np.arange(0, len(next_batch))
    for score, pipeline in zip(scores, next_batch):
        algo.add_result(score, pipeline, {"id": algo.pipeline_number})

    # # make sure that future batches remain in the hyperparam range
    for i in range(1, 5):
        next_batch = algo.next_batch()
        for p in next_batch:
            for component in p.component_graph:
                if "sampler" in component.name:
                    assert component.parameters["sampling_ratio"] == 0.25
