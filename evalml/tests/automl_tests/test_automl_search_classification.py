import warnings
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from sklearn.model_selection import StratifiedKFold

from evalml import AutoMLSearch
from evalml.automl.automl_algorithm import DefaultAlgorithm, IterativeAlgorithm
from evalml.automl.callbacks import raise_error_callback
from evalml.automl.pipeline_search_plots import SearchIterationPlot
from evalml.automl.utils import get_best_sampler_for_data
from evalml.exceptions import ParameterNotUsedWarning, PipelineNotFoundError
from evalml.model_family import ModelFamily
from evalml.objectives import (
    FraudCost,
    Precision,
    PrecisionMicro,
    Recall,
    get_core_objectives,
    get_objective,
)
from evalml.pipelines import (
    BinaryClassificationPipeline,
    MulticlassClassificationPipeline,
    PipelineBase,
    TimeSeriesBinaryClassificationPipeline,
    TimeSeriesMulticlassClassificationPipeline,
)
from evalml.pipelines.components.utils import get_estimators
from evalml.pipelines.utils import make_pipeline
from evalml.preprocessing import TimeSeriesSplit, split_data
from evalml.problem_types import ProblemTypes


def test_init(X_y_binary):
    X, y = X_y_binary

    automl = AutoMLSearch(
        X_train=X, y_train=y, problem_type="binary", max_iterations=1, n_jobs=1
    )
    automl.search()

    assert automl.n_jobs == 1
    assert isinstance(automl._automl_algorithm, IterativeAlgorithm)
    assert isinstance(automl.rankings, pd.DataFrame)
    assert isinstance(automl.best_pipeline, PipelineBase)
    automl.best_pipeline.predict(X)

    # test with dataframes
    automl = AutoMLSearch(
        pd.DataFrame(X), pd.Series(y), problem_type="binary", max_iterations=1, n_jobs=1
    )
    automl.search()

    assert isinstance(automl.rankings, pd.DataFrame)
    assert isinstance(automl.full_rankings, pd.DataFrame)
    assert isinstance(automl.best_pipeline, PipelineBase)
    assert isinstance(automl.get_pipeline(0), PipelineBase)
    assert automl.objective.name == "Log Loss Binary"
    automl.best_pipeline.predict(X)

    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        max_iterations=1,
        n_jobs=1,
        _automl_algorithm="default",
    )
    assert isinstance(automl._automl_algorithm, DefaultAlgorithm)

    with pytest.raises(ValueError, match="Please specify a valid automl algorithm."):
        AutoMLSearch(
            X_train=X,
            y_train=y,
            problem_type="binary",
            max_iterations=1,
            n_jobs=1,
            _automl_algorithm="not_valid",
        )


def test_init_objective(X_y_binary):
    X, y = X_y_binary
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective=Precision(),
        max_iterations=1,
    )
    assert isinstance(automl.objective, Precision)
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective="Precision",
        max_iterations=1,
    )
    assert isinstance(automl.objective, Precision)


def test_get_pipeline_none(X_y_binary):
    X, y = X_y_binary
    automl = AutoMLSearch(X_train=X, y_train=y, problem_type="binary")
    with pytest.raises(PipelineNotFoundError, match="Pipeline not found"):
        automl.describe_pipeline(0)


def test_data_splitter(X_y_binary):
    X, y = X_y_binary
    cv_folds = 5
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        data_splitter=StratifiedKFold(n_splits=cv_folds),
        max_iterations=1,
        n_jobs=1,
    )
    automl.search()

    assert isinstance(automl.rankings, pd.DataFrame)
    assert len(automl.results["pipeline_results"][0]["cv_data"]) == cv_folds

    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        data_splitter=TimeSeriesSplit(n_splits=cv_folds),
        max_iterations=1,
        n_jobs=1,
    )
    automl.search()

    assert isinstance(automl.rankings, pd.DataFrame)
    assert len(automl.results["pipeline_results"][0]["cv_data"]) == cv_folds


def test_max_iterations(AutoMLTestEnv, X_y_binary):
    X, y = X_y_binary
    max_iterations = 5
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        max_iterations=max_iterations,
        n_jobs=1,
    )
    env = AutoMLTestEnv("binary")
    with env.test_context(score_return_value={automl.objective.name: 0.2}):
        automl.search()
    assert len(automl.full_rankings) == max_iterations


def test_recall_error(X_y_binary):
    X, y = X_y_binary
    # Recall is a valid objective but it's not allowed in AutoML so a ValueError is expected
    error_msg = "recall is not allowed in AutoML!"
    with pytest.raises(ValueError, match=error_msg):
        AutoMLSearch(
            X_train=X,
            y_train=y,
            problem_type="binary",
            objective="recall",
            max_iterations=1,
        )


def test_recall_object(X_y_binary):
    X, y = X_y_binary
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective=Recall(),
        max_iterations=1,
        n_jobs=1,
    )
    automl.search()
    assert len(automl.full_rankings) > 0
    assert automl.objective.name == "Recall"


def test_binary_auto(X_y_binary):
    X, y = X_y_binary
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective="Log Loss Binary",
        max_iterations=3,
        n_jobs=1,
    )
    automl.search()

    best_pipeline = automl.best_pipeline
    assert best_pipeline._is_fitted
    y_pred = best_pipeline.predict(X)
    assert len(np.unique(y_pred)) == 2


def test_multi_auto(X_y_multi):
    multiclass_objectives = get_core_objectives("multiclass")
    X, y = X_y_multi
    objective = PrecisionMicro()
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="multiclass",
        objective=objective,
        max_iterations=3,
        n_jobs=1,
    )
    automl.search()
    best_pipeline = automl.best_pipeline
    assert best_pipeline._is_fitted
    y_pred = best_pipeline.predict(X)
    assert len(np.unique(y_pred)) == 3

    objective_in_additional_objectives = next(
        (obj for obj in multiclass_objectives if obj.name == objective.name), None
    )
    multiclass_objectives.remove(objective_in_additional_objectives)

    for expected, additional in zip(
        multiclass_objectives, automl.additional_objectives
    ):
        assert type(additional) is type(expected)


def test_multi_objective(X_y_multi):
    X, y = X_y_multi
    automl = AutoMLSearch(
        X_train=X, y_train=y, problem_type="binary", objective="Log Loss Binary"
    )
    assert automl.problem_type == ProblemTypes.BINARY

    automl = AutoMLSearch(
        X_train=X, y_train=y, problem_type="multiclass", objective="Log Loss Multiclass"
    )
    assert automl.problem_type == ProblemTypes.MULTICLASS

    automl = AutoMLSearch(
        X_train=X, y_train=y, problem_type="multiclass", objective="AUC Micro"
    )
    assert automl.problem_type == ProblemTypes.MULTICLASS

    automl = AutoMLSearch(X_train=X, y_train=y, problem_type="binary", objective="AUC")
    assert automl.problem_type == ProblemTypes.BINARY

    automl = AutoMLSearch(X_train=X, y_train=y, problem_type="multiclass")
    assert automl.problem_type == ProblemTypes.MULTICLASS

    automl = AutoMLSearch(X_train=X, y_train=y, problem_type="binary")
    assert automl.problem_type == ProblemTypes.BINARY


def test_categorical_classification(AutoMLTestEnv, X_y_categorical_classification):
    X, y = X_y_categorical_classification

    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective="precision",
        max_batches=1,
        n_jobs=1,
    )

    env = AutoMLTestEnv("binary")
    with env.test_context(score_return_value={automl.objective.name: 1}):
        automl.search()
    assert not automl.rankings["mean_cv_score"].isnull().any()


def test_random_seed(X_y_binary):
    X, y = X_y_binary

    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective=Precision(),
        max_batches=1,
        random_seed=0,
        n_jobs=1,
    )
    automl.search()

    automl_1 = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective=Precision(),
        random_seed=0,
        n_jobs=1,
    )
    automl_1.search()
    assert automl.rankings.equals(automl_1.rankings)


def test_callback(X_y_binary):
    X, y = X_y_binary

    counts = {
        "start_iteration_callback": 0,
        "add_result_callback": 0,
    }

    def start_iteration_callback(pipeline, automl_obj, counts=counts):
        counts["start_iteration_callback"] += 1

    def add_result_callback(results, trained_pipeline, automl_obj, counts=counts):
        counts["add_result_callback"] += 1

    max_iterations = 3
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective=Precision(),
        max_iterations=max_iterations,
        start_iteration_callback=start_iteration_callback,
        add_result_callback=add_result_callback,
        n_jobs=1,
    )
    automl.search()

    assert counts["start_iteration_callback"] == len(get_estimators("binary")) + 1
    assert counts["add_result_callback"] == max_iterations


def test_additional_objectives(X_y_binary):
    X, y = X_y_binary

    objective = FraudCost(
        retry_percentage=0.5,
        interchange_fee=0.02,
        fraud_payout_percentage=0.75,
        amount_col=10,
    )
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective="F1",
        max_iterations=2,
        additional_objectives=[objective],
        n_jobs=1,
    )
    automl.search()

    results = automl.describe_pipeline(0, return_dict=True)
    assert "Fraud Cost" in list(results["cv_data"][0]["all_objective_scores"].keys())


def test_optimizable_threshold_enabled(
    AutoMLTestEnv,
    X_y_binary,
    caplog,
):
    X, y = X_y_binary
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective="precision",
        max_iterations=1,
        optimize_thresholds=True,
    )
    env = AutoMLTestEnv("binary")
    with env.test_context(
        score_return_value={"precision": 1.0},
        optimize_threshold_return_value=0.8,
    ):
        automl.search()

    env.mock_fit.assert_called()
    env.mock_score.assert_called()
    env.mock_predict_proba.assert_called()
    env.mock_optimize_threshold.assert_called()
    assert automl.best_pipeline.threshold == 0.8
    assert (
        automl.results["pipeline_results"][0]["cv_data"][0].get(
            "binary_classification_threshold"
        )
        == 0.8
    )
    assert (
        automl.results["pipeline_results"][0]["cv_data"][1].get(
            "binary_classification_threshold"
        )
        == 0.8
    )
    assert (
        automl.results["pipeline_results"][0]["cv_data"][2].get(
            "binary_classification_threshold"
        )
        == 0.8
    )

    automl.describe_pipeline(0)
    out = caplog.text
    assert "Objective to optimize binary classification pipeline thresholds for" in out


def test_optimizable_threshold_disabled(
    AutoMLTestEnv,
    X_y_binary,
):
    X, y = X_y_binary
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective="precision",
        max_iterations=1,
        optimize_thresholds=False,
    )
    env = AutoMLTestEnv("binary")
    with env.test_context(score_return_value={automl.objective.name: 1}):
        automl.search()
    env.mock_fit.assert_called()
    env.mock_score.assert_called()
    assert not env.mock_predict_proba.called
    assert not env.mock_optimize_threshold.called
    assert automl.best_pipeline.threshold == 0.5
    assert (
        automl.results["pipeline_results"][0]["cv_data"][0].get(
            "binary_classification_threshold"
        )
        == 0.5
    )
    assert (
        automl.results["pipeline_results"][0]["cv_data"][1].get(
            "binary_classification_threshold"
        )
        == 0.5
    )
    assert (
        automl.results["pipeline_results"][0]["cv_data"][2].get(
            "binary_classification_threshold"
        )
        == 0.5
    )


def test_non_optimizable_threshold(AutoMLTestEnv, X_y_binary):
    X, y = X_y_binary
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective="AUC",
        optimize_thresholds=False,
        max_iterations=1,
    )
    env = AutoMLTestEnv("binary")
    with env.test_context(score_return_value={"AUC": 1}):
        automl.search()
    env.mock_fit.assert_called()
    env.mock_score.assert_called()
    assert automl.best_pipeline.threshold is None
    assert (
        automl.results["pipeline_results"][0]["cv_data"][0].get(
            "binary_classification_threshold"
        )
        is None
    )
    assert (
        automl.results["pipeline_results"][0]["cv_data"][1].get(
            "binary_classification_threshold"
        )
        is None
    )
    assert (
        automl.results["pipeline_results"][0]["cv_data"][2].get(
            "binary_classification_threshold"
        )
        is None
    )


def test_describe_pipeline_objective_ordered(X_y_binary, caplog):
    X, y = X_y_binary
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective="AUC",
        max_iterations=2,
        n_jobs=1,
    )
    automl.search()

    automl.describe_pipeline(0)
    out = caplog.text
    out_stripped = " ".join(out.split())

    objectives = [get_objective(obj) for obj in automl.additional_objectives]
    objectives_names = [obj.name for obj in objectives]
    expected_objective_order = " ".join(objectives_names)

    assert expected_objective_order in out_stripped


def test_max_time_units(X_y_binary):
    X, y = X_y_binary
    str_max_time = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective="F1",
        max_time="60 seconds",
    )
    assert str_max_time.max_time == 60

    hour_max_time = AutoMLSearch(
        X_train=X, y_train=y, problem_type="binary", objective="F1", max_time="1 hour"
    )
    assert hour_max_time.max_time == 3600

    min_max_time = AutoMLSearch(
        X_train=X, y_train=y, problem_type="binary", objective="F1", max_time="30 mins"
    )
    assert min_max_time.max_time == 1800

    min_max_time = AutoMLSearch(
        X_train=X, y_train=y, problem_type="binary", objective="F1", max_time="30 s"
    )
    assert min_max_time.max_time == 30

    with pytest.raises(
        AssertionError,
        match="Invalid unit. Units must be hours, mins, or seconds. Received 'year'",
    ):
        AutoMLSearch(
            X_train=X,
            y_train=y,
            problem_type="binary",
            objective="F1",
            max_time="30 years",
        )

    with pytest.raises(
        TypeError,
        match="Parameter max_time must be a float, int, string or None. Received <class 'tuple'> with value \\(30, 'minutes'\\).",
    ):
        AutoMLSearch(
            X_train=X,
            y_train=y,
            problem_type="binary",
            objective="F1",
            max_time=(30, "minutes"),
        )


def test_plot_disabled_missing_dependency(X_y_binary, has_minimal_dependencies):
    X, y = X_y_binary

    automl = AutoMLSearch(X_train=X, y_train=y, problem_type="binary", max_iterations=3)
    if has_minimal_dependencies:
        with pytest.raises(AttributeError):
            automl.plot.search_iteration_plot
    else:
        automl.plot.search_iteration_plot


def test_plot_iterations_max_iterations(X_y_binary):
    go = pytest.importorskip(
        "plotly.graph_objects",
        reason="Skipping plotting test because plotly not installed",
    )
    X, y = X_y_binary

    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective="f1",
        max_iterations=3,
        n_jobs=1,
    )
    automl.search()
    plot = automl.plot.search_iteration_plot()
    plot_data = plot.data[0]
    x = pd.Series(plot_data["x"])
    y = pd.Series(plot_data["y"])

    assert isinstance(plot, go.Figure)
    assert x.is_monotonic_increasing
    assert y.is_monotonic_increasing
    assert len(x) == 3
    assert len(y) == 3


def test_plot_iterations_max_time(AutoMLTestEnv, X_y_binary):
    go = pytest.importorskip(
        "plotly.graph_objects",
        reason="Skipping plotting test because plotly not installed",
    )
    X, y = X_y_binary

    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective="f1",
        max_time=2,
        n_jobs=1,
        optimize_thresholds=False,
    )
    env = AutoMLTestEnv("binary")
    with env.test_context(score_return_value={"F1": 0.8}):
        automl.search()
    plot = automl.plot.search_iteration_plot()
    plot_data = plot.data[0]
    x = pd.Series(plot_data["x"])
    y = pd.Series(plot_data["y"])

    assert isinstance(plot, go.Figure)
    assert x.is_monotonic_increasing
    assert y.is_monotonic_increasing
    assert len(x) > 0
    assert len(y) > 0


@patch("IPython.display.display")
def test_plot_iterations_ipython_mock(mock_ipython_display, X_y_binary):
    pytest.importorskip(
        "IPython.display",
        reason="Skipping plotting test because ipywidgets not installed",
    )
    pytest.importorskip(
        "plotly.graph_objects",
        reason="Skipping plotting test because plotly not installed",
    )
    X, y = X_y_binary

    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective="f1",
        max_iterations=3,
        n_jobs=1,
    )
    automl.search()
    plot = automl.plot.search_iteration_plot(interactive_plot=True)
    assert isinstance(plot, SearchIterationPlot)
    mock_ipython_display.assert_called_with(plot.best_score_by_iter_fig)


@patch("IPython.display.display")
def test_plot_iterations_ipython_mock_import_failure(mock_ipython_display, X_y_binary):
    pytest.importorskip(
        "IPython.display",
        reason="Skipping plotting test because ipywidgets not installed",
    )
    go = pytest.importorskip(
        "plotly.graph_objects",
        reason="Skipping plotting test because plotly not installed",
    )
    X, y = X_y_binary

    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        objective="f1",
        max_iterations=3,
        n_jobs=1,
    )
    automl.search()

    mock_ipython_display.side_effect = ImportError("KABOOOOOOMMMM")
    plot = automl.plot.search_iteration_plot(interactive_plot=True)
    mock_ipython_display.assert_called_once()

    assert isinstance(plot, go.Figure)
    assert isinstance(plot.data, tuple)
    plot_data = plot.data[0]
    x = pd.Series(plot_data["x"])
    y = pd.Series(plot_data["y"])
    assert x.is_monotonic_increasing
    assert y.is_monotonic_increasing
    assert len(x) == 3
    assert len(y) == 3


def test_max_time(X_y_binary):
    X, y = X_y_binary
    automl = AutoMLSearch(
        X_train=X, y_train=y, problem_type="binary", max_time=1e-16, n_jobs=1
    )
    automl.search()
    # search will always run at least one pipeline
    assert len(automl.results["pipeline_results"]) == 1


@pytest.mark.parametrize("automl_type", [ProblemTypes.BINARY, ProblemTypes.MULTICLASS])
def test_automl_allowed_component_graphs_no_component_graphs(
    automl_type, X_y_binary, X_y_multi
):
    is_multiclass = automl_type == ProblemTypes.MULTICLASS
    X, y = X_y_multi if is_multiclass else X_y_binary
    problem_type = "multiclass" if is_multiclass else "binary"
    with pytest.raises(ValueError, match="No allowed pipelines to search"):
        AutoMLSearch(
            X_train=X,
            y_train=y,
            problem_type=problem_type,
            allowed_component_graphs=None,
            allowed_model_families=[],
        )


def test_automl_component_graphs_specified_component_graphs_binary(
    AutoMLTestEnv,
    dummy_classifier_estimator_class,
    dummy_binary_pipeline_class,
    X_y_binary,
):
    X, y = X_y_binary
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        allowed_component_graphs={
            "Mock Binary Classification Pipeline": [dummy_classifier_estimator_class]
        },
        optimize_thresholds=False,
        allowed_model_families=None,
    )
    expected_pipeline = dummy_binary_pipeline_class({})
    expected_component_graph = expected_pipeline.component_graph
    expected_name = expected_pipeline.name
    expected_parameters = expected_pipeline.parameters
    assert automl.allowed_pipelines[0].component_graph == expected_component_graph
    assert automl.allowed_pipelines[0].name == expected_name
    assert automl.allowed_pipelines[0].parameters == expected_parameters
    assert automl.allowed_model_families == [ModelFamily.NONE]

    env = AutoMLTestEnv("binary")
    with env.test_context(score_return_value={automl.objective.name: 1.0}):
        automl.search()
    env.mock_fit.assert_called()
    env.mock_score.assert_called()
    assert automl.allowed_pipelines[0].component_graph == expected_component_graph
    assert automl.allowed_pipelines[0].name == expected_name
    assert automl.allowed_pipelines[0].parameters == expected_parameters
    assert automl.allowed_model_families == [ModelFamily.NONE]


def test_automl_component_graphs_specified_component_graphs_multi(
    AutoMLTestEnv,
    dummy_classifier_estimator_class,
    dummy_multiclass_pipeline_class,
    X_y_multi,
):
    X, y = X_y_multi
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="multiclass",
        allowed_component_graphs={
            "Mock Multiclass Classification Pipeline": [
                dummy_classifier_estimator_class
            ]
        },
        allowed_model_families=None,
    )
    expected_pipeline = dummy_multiclass_pipeline_class({})
    expected_component_graph = expected_pipeline.component_graph
    expected_name = expected_pipeline.name
    expected_parameters = expected_pipeline.parameters
    assert automl.allowed_pipelines[0].component_graph == expected_component_graph
    assert automl.allowed_pipelines[0].name == expected_name
    assert automl.allowed_pipelines[0].parameters == expected_parameters
    assert automl.allowed_model_families == [ModelFamily.NONE]

    env = AutoMLTestEnv("multiclass")
    with env.test_context(score_return_value={automl.objective.name: 1.0}):
        automl.search()
    env.mock_fit.assert_called()
    env.mock_score.assert_called()
    assert automl.allowed_pipelines[0].component_graph == expected_component_graph
    assert automl.allowed_pipelines[0].name == expected_name
    assert automl.allowed_pipelines[0].parameters == expected_parameters
    assert automl.allowed_model_families == [ModelFamily.NONE]


def test_automl_component_graphs_specified_allowed_model_families_binary(
    AutoMLTestEnv, X_y_binary, assert_allowed_pipelines_equal_helper
):
    X, y = X_y_binary
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        allowed_component_graphs=None,
        allowed_model_families=[ModelFamily.RANDOM_FOREST],
        optimize_thresholds=False,
    )
    expected_pipelines = [
        make_pipeline(X, y, estimator, ProblemTypes.BINARY)
        for estimator in get_estimators(
            ProblemTypes.BINARY, model_families=[ModelFamily.RANDOM_FOREST]
        )
    ]
    assert_allowed_pipelines_equal_helper(automl.allowed_pipelines, expected_pipelines)

    env = AutoMLTestEnv("binary")
    with env.test_context(score_return_value={automl.objective.name: 1.0}):
        automl.search()
    assert_allowed_pipelines_equal_helper(automl.allowed_pipelines, expected_pipelines)
    assert set(automl.allowed_model_families) == set([ModelFamily.RANDOM_FOREST])
    env.mock_fit.assert_called()
    env.mock_score.assert_called()

    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        allowed_component_graphs=None,
        allowed_model_families=["random_forest"],
        optimize_thresholds=False,
    )
    expected_pipelines = [
        make_pipeline(X, y, estimator, ProblemTypes.BINARY)
        for estimator in get_estimators(
            ProblemTypes.BINARY, model_families=[ModelFamily.RANDOM_FOREST]
        )
    ]
    assert_allowed_pipelines_equal_helper(automl.allowed_pipelines, expected_pipelines)
    with env.test_context(score_return_value={automl.objective.name: 1.0}):
        automl.search()
    assert_allowed_pipelines_equal_helper(automl.allowed_pipelines, expected_pipelines)
    assert set(automl.allowed_model_families) == set([ModelFamily.RANDOM_FOREST])
    env.mock_fit.assert_called()
    env.mock_score.assert_called()


def test_automl_component_graphs_specified_allowed_model_families_multi(
    AutoMLTestEnv, X_y_multi, assert_allowed_pipelines_equal_helper
):
    X, y = X_y_multi
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="multiclass",
        allowed_component_graphs=None,
        allowed_model_families=[ModelFamily.RANDOM_FOREST],
    )
    expected_pipelines = [
        make_pipeline(X, y, estimator, ProblemTypes.MULTICLASS)
        for estimator in get_estimators(
            ProblemTypes.MULTICLASS, model_families=[ModelFamily.RANDOM_FOREST]
        )
    ]
    assert_allowed_pipelines_equal_helper(automl.allowed_pipelines, expected_pipelines)

    env = AutoMLTestEnv("multiclass")
    with env.test_context(score_return_value={automl.objective.name: 1}):
        automl.search()
    assert_allowed_pipelines_equal_helper(automl.allowed_pipelines, expected_pipelines)
    assert set(automl.allowed_model_families) == set([ModelFamily.RANDOM_FOREST])
    env.mock_fit.assert_called()
    env.mock_score.assert_called()

    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="multiclass",
        allowed_component_graphs=None,
        allowed_model_families=["random_forest"],
    )
    expected_pipelines = [
        make_pipeline(X, y, estimator, ProblemTypes.MULTICLASS)
        for estimator in get_estimators(
            ProblemTypes.MULTICLASS, model_families=[ModelFamily.RANDOM_FOREST]
        )
    ]
    assert_allowed_pipelines_equal_helper(automl.allowed_pipelines, expected_pipelines)
    with env.test_context(score_return_value={automl.objective.name: 1}):
        automl.search()
    assert_allowed_pipelines_equal_helper(automl.allowed_pipelines, expected_pipelines)
    assert set(automl.allowed_model_families) == set([ModelFamily.RANDOM_FOREST])
    env.mock_fit.assert_called()
    env.mock_score.assert_called()


def test_automl_component_graphs_init_allowed_both_not_specified_binary(
    AutoMLTestEnv, X_y_binary, assert_allowed_pipelines_equal_helper
):
    X, y = X_y_binary
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        allowed_component_graphs=None,
        allowed_model_families=None,
        optimize_thresholds=False,
    )
    expected_pipelines = [
        make_pipeline(X, y, estimator, ProblemTypes.BINARY)
        for estimator in get_estimators(ProblemTypes.BINARY, model_families=None)
    ]
    assert_allowed_pipelines_equal_helper(automl.allowed_pipelines, expected_pipelines)
    env = AutoMLTestEnv("binary")
    with env.test_context(score_return_value={automl.objective.name: 1}):
        automl.search()
    assert_allowed_pipelines_equal_helper(automl.allowed_pipelines, expected_pipelines)
    assert set(automl.allowed_model_families) == set(
        [p.model_family for p in expected_pipelines]
    )
    env.mock_fit.assert_called()
    env.mock_score.assert_called()


def test_automl_component_graphs_init_allowed_both_not_specified_multi(
    AutoMLTestEnv, X_y_multi, assert_allowed_pipelines_equal_helper
):
    X, y = X_y_multi
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="multiclass",
        allowed_component_graphs=None,
        allowed_model_families=None,
    )
    expected_pipelines = [
        make_pipeline(X, y, estimator, ProblemTypes.MULTICLASS)
        for estimator in get_estimators(ProblemTypes.MULTICLASS, model_families=None)
    ]
    assert_allowed_pipelines_equal_helper(automl.allowed_pipelines, expected_pipelines)
    env = AutoMLTestEnv("multiclass")
    with env.test_context(score_return_value={automl.objective.name: 1}):
        automl.search()
    assert_allowed_pipelines_equal_helper(automl.allowed_pipelines, expected_pipelines)
    assert set(automl.allowed_model_families) == set(
        [p.model_family for p in expected_pipelines]
    )
    env.mock_fit.assert_called()
    env.mock_score.assert_called()


def test_automl_component_graphs_init_allowed_both_specified_binary(
    AutoMLTestEnv,
    dummy_classifier_estimator_class,
    dummy_binary_pipeline_class,
    X_y_binary,
):
    X, y = X_y_binary
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        allowed_component_graphs={
            "Mock Binary Classification Pipeline": [dummy_classifier_estimator_class]
        },
        allowed_model_families=[ModelFamily.RANDOM_FOREST],
        optimize_thresholds=False,
    )
    expected_pipeline = dummy_binary_pipeline_class({})
    expected_component_graph = expected_pipeline.component_graph
    expected_name = expected_pipeline.name
    expected_parameters = expected_pipeline.parameters
    assert automl.allowed_pipelines[0].component_graph == expected_component_graph
    assert automl.allowed_pipelines[0].name == expected_name
    assert automl.allowed_pipelines[0].parameters == expected_parameters
    assert automl.allowed_model_families == [ModelFamily.NONE]

    env = AutoMLTestEnv("binary")
    with env.test_context(score_return_value={automl.objective.name: 1}):
        automl.search()
    assert set(automl.allowed_model_families) == set(
        [p.model_family for p in expected_pipeline]
    )
    env.mock_fit.assert_called()
    env.mock_score.assert_called()


def test_automl_component_graphs_init_allowed_both_specified_multi(
    AutoMLTestEnv,
    dummy_classifier_estimator_class,
    dummy_multiclass_pipeline_class,
    X_y_multi,
):
    X, y = X_y_multi
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="multiclass",
        allowed_component_graphs={
            "Mock Multiclass Classification Pipeline": [
                dummy_classifier_estimator_class
            ]
        },
        allowed_model_families=[ModelFamily.RANDOM_FOREST],
    )
    expected_pipeline = dummy_multiclass_pipeline_class({})
    expected_component_graph = expected_pipeline.component_graph
    expected_name = expected_pipeline.name
    expected_parameters = expected_pipeline.parameters
    assert automl.allowed_pipelines[0].component_graph == expected_component_graph
    assert automl.allowed_pipelines[0].name == expected_name
    assert automl.allowed_pipelines[0].parameters == expected_parameters
    assert automl.allowed_model_families == [ModelFamily.NONE]

    env = AutoMLTestEnv("multiclass")
    with env.test_context(score_return_value={automl.objective.name: 1}):
        automl.search()
    assert set(automl.allowed_model_families) == set(
        [p.model_family for p in expected_pipeline]
    )
    env.mock_fit.assert_called()
    env.mock_score.assert_called()


@pytest.mark.parametrize("problem_type", ["binary", "multiclass"])
def test_automl_component_graphs_search(
    problem_type,
    example_graph,
    X_y_binary,
    X_y_multi,
    AutoMLTestEnv,
):
    if problem_type == "binary":
        X, y = X_y_binary
        score_return_value = {"Log Loss Binary": 1.0}
        expected_mock_class = BinaryClassificationPipeline
    else:
        X, y = X_y_multi
        score_return_value = {"Log Loss Multiclass": 1.0}
        expected_mock_class = MulticlassClassificationPipeline
    component_graph = {"CG": example_graph}

    start_iteration_callback = MagicMock()
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        max_iterations=5,
        problem_type=problem_type,
        start_iteration_callback=start_iteration_callback,
        allowed_component_graphs=component_graph,
        optimize_thresholds=False,
    )
    env = AutoMLTestEnv(problem_type)
    with env.test_context(score_return_value=score_return_value):
        automl.search()

    assert isinstance(
        start_iteration_callback.call_args_list[0][0][0], expected_mock_class
    )
    for i in range(1, 5):
        if problem_type == "binary":
            assert isinstance(
                start_iteration_callback.call_args_list[i][0][0],
                BinaryClassificationPipeline,
            )
        elif problem_type == "multiclass":
            assert isinstance(
                start_iteration_callback.call_args_list[i][0][0],
                MulticlassClassificationPipeline,
            )


@pytest.mark.parametrize(
    "problem_type",
    [ProblemTypes.TIME_SERIES_MULTICLASS, ProblemTypes.TIME_SERIES_BINARY],
)
def test_automl_supports_time_series_classification(
    problem_type,
    X_y_binary,
    X_y_multi,
    AutoMLTestEnv,
):
    if problem_type == ProblemTypes.TIME_SERIES_BINARY:
        X, y = X_y_binary
        baseline = TimeSeriesBinaryClassificationPipeline(
            component_graph=["Time Series Baseline Estimator"],
            parameters={
                "Time Series Baseline Estimator": {
                    "date_index": None,
                    "gap": 0,
                    "max_delay": 0,
                    "forecast_horizon": 1,
                },
                "pipeline": {
                    "date_index": None,
                    "gap": 0,
                    "max_delay": 0,
                    "forecast_horizon": 1,
                },
            },
        )
        score_return_value = {"Log Loss Binary": 0.2}
        problem_type = "time series binary"
    else:
        X, y = X_y_multi
        baseline = TimeSeriesMulticlassClassificationPipeline(
            component_graph=["Time Series Baseline Estimator"],
            parameters={
                "Time Series Baseline Estimator": {
                    "date_index": None,
                    "gap": 0,
                    "max_delay": 0,
                    "forecast_horizon": 1,
                },
                "pipeline": {
                    "date_index": None,
                    "gap": 0,
                    "max_delay": 0,
                    "forecast_horizon": 1,
                },
            },
        )
        score_return_value = {"Log Loss Multiclass": 0.25}
        problem_type = "time series multiclass"

    configuration = {
        "date_index": None,
        "gap": 0,
        "max_delay": 0,
        "forecast_horizon": 1,
        "delay_target": False,
        "delay_features": True,
    }

    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type=problem_type,
        optimize_thresholds=False,
        problem_configuration=configuration,
        max_batches=2,
    )
    env = AutoMLTestEnv(problem_type)
    with env.test_context(score_return_value=score_return_value):
        automl.search()
    assert isinstance(automl.data_splitter, TimeSeriesSplit)
    for result in automl.results["pipeline_results"].values():
        if result["id"] == 0:
            assert result["pipeline_class"] == baseline.__class__
            continue

        assert result["parameters"]["Delayed Feature Transformer"] == configuration
        assert result["parameters"]["pipeline"] == configuration


@pytest.mark.parametrize("objective", ["F1", "Log Loss Binary"])
@pytest.mark.parametrize("optimize", [True, False])
@patch("evalml.automl.engine.engine_base.split_data")
def test_automl_time_series_classification_threshold(
    mock_split_data,
    optimize,
    objective,
    X_y_binary,
    AutoMLTestEnv,
):
    X, y = X_y_binary
    score_return_value = {objective: 0.4}
    problem_type = "time series binary"

    configuration = {
        "date_index": None,
        "gap": 0,
        "forecast_horizon": 1,
        "max_delay": 0,
        "delay_target": False,
        "delay_features": True,
    }

    optimize_return_value = 0.62
    mock_split_data.return_value = split_data(
        X, y, problem_type, test_size=0.2, random_seed=0
    )
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type=problem_type,
        problem_configuration=configuration,
        objective=objective,
        optimize_thresholds=optimize,
        max_batches=2,
    )
    env = AutoMLTestEnv(problem_type)
    with env.test_context(
        score_return_value=score_return_value,
        optimize_threshold_return_value=optimize_return_value,
    ):
        automl.search()
    assert isinstance(automl.data_splitter, TimeSeriesSplit)
    if optimize:
        env.mock_optimize_threshold.assert_called()
        assert automl.best_pipeline.threshold == 0.62
        mock_split_data.assert_called()
    else:
        env.mock_optimize_threshold.assert_not_called()
        mock_split_data.assert_not_called()
        if objective == "Log Loss Binary":
            assert automl.best_pipeline.threshold is None
        else:
            assert automl.best_pipeline.threshold == 0.5


@pytest.mark.parametrize("problem_type", ["binary", "multiclass"])
@pytest.mark.parametrize("categorical_features", ["none", "some", "all"])
@pytest.mark.parametrize("size", ["small", "large"])
@pytest.mark.parametrize("sampling_ratio", [0.8, 0.5, 0.25, 0.2, 0.1, 0.05])
def test_automl_search_sampler_ratio(
    sampling_ratio,
    size,
    categorical_features,
    problem_type,
    mock_imbalanced_data_X_y,
    has_minimal_dependencies,
):
    X, y = mock_imbalanced_data_X_y(problem_type, categorical_features, size)
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type=problem_type,
        sampler_method="auto",
        sampler_balanced_ratio=sampling_ratio,
    )
    pipelines = automl.allowed_pipelines
    if sampling_ratio <= 0.2:
        # we consider this balanced, so we expect no samplers
        assert not any(
            any("sampler" in comp.name for comp in pipeline.component_graph)
            for pipeline in pipelines
        )
    else:
        if size == "large" or has_minimal_dependencies:
            assert all(
                any("Undersampler" in comp.name for comp in pipeline.component_graph)
                for pipeline in pipelines
            )
        else:
            assert all(
                any("Oversampler" in comp.name for comp in pipeline.component_graph)
                for pipeline in pipelines
            )
        for comp in pipelines[0].component_graph:
            if "sampler" in comp.name:
                assert comp.parameters["sampling_ratio"] == sampling_ratio


def test_automl_oversampler_selection():
    X = pd.DataFrame({"a": ["a"] * 50 + ["b"] * 25 + ["c"] * 25, "b": list(range(100))})
    y = pd.Series([1] * 90 + [0] * 10)
    X.ww.init(logical_types={"a": "Categorical"})

    sampler = get_best_sampler_for_data(
        X, y, sampler_method="Oversampler", sampler_balanced_ratio=0.5
    )

    allowed_component_graph = {
        "DropCols": ["Drop Columns Transformer", "X", "y"],
        "Oversampler": [sampler, "DropCols.x", "y"],
        "RF": ["Random Forest Classifier", "Oversampler.x", "Oversampler.y"],
    }

    automl = AutoMLSearch(
        X,
        y,
        "binary",
        allowed_component_graphs={"pipeline": allowed_component_graph},
        pipeline_parameters={"DropCols": {"columns": ["a"]}},
        error_callback=raise_error_callback,
    )
    # This should run without error
    automl.search()


@pytest.mark.parametrize("problem_type", ["binary", "multiclass"])
@pytest.mark.parametrize(
    "sampler_method,categorical_features",
    [
        (None, "none"),
        (None, "some"),
        (None, "all"),
        ("Undersampler", "none"),
        ("Undersampler", "some"),
        ("Undersampler", "all"),
        ("Oversampler", "none"),
        ("Oversampler", "some"),
        ("Oversampler", "all"),
    ],
)
def test_automl_search_sampler_method(
    sampler_method,
    categorical_features,
    problem_type,
    mock_imbalanced_data_X_y,
    has_minimal_dependencies,
    caplog,
):
    # 0.2 minority:majority class ratios
    X, y = mock_imbalanced_data_X_y(problem_type, categorical_features, "small")
    automl = AutoMLSearch(
        X_train=X, y_train=y, problem_type=problem_type, sampler_method=sampler_method
    )
    # since our default sampler_balanced_ratio for AutoMLSearch is 0.25, we should be adding the samplers when we can
    pipelines = automl.allowed_pipelines
    if sampler_method is None:
        assert not any(
            any("sampler" in comp.name for comp in pipeline.component_graph)
            for pipeline in pipelines
        )
    else:
        if has_minimal_dependencies:
            sampler_method = "Undersampler"
            assert "Could not import imblearn.over_sampling" in caplog.text
        assert all(
            any(sampler_method in comp.name for comp in pipeline.component_graph)
            for pipeline in pipelines
        )


@pytest.mark.parametrize("sampling_ratio", [0.1, 0.2, 0.5, 1])
@pytest.mark.parametrize("sampler", ["Undersampler", "Oversampler"])
def test_automl_search_ratio_overrides_sampler_ratio(
    sampler, sampling_ratio, mock_imbalanced_data_X_y, has_minimal_dependencies
):
    if has_minimal_dependencies and sampler == "Oversampler":
        pytest.skip("Skipping test with minimal dependencies")
    X, y = mock_imbalanced_data_X_y("binary", "none", "small")
    pipeline_parameters = {sampler: {"sampling_ratio": sampling_ratio}}
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        sampler_method=sampler,
        pipeline_parameters=pipeline_parameters,
        sampler_balanced_ratio=0.5,
    )
    # make sure that our sampling_balanced_ratio of 0.5 overrides the pipeline params passed in
    pipelines = automl.allowed_pipelines
    for pipeline in pipelines:
        seen_sampler = False
        for comp in pipeline.component_graph:
            if comp.name == sampler:
                assert comp.parameters["sampling_ratio"] == 0.5
                seen_sampler = True
        assert seen_sampler


@pytest.mark.parametrize(
    "problem_type,sampling_ratio_dict,length",
    [
        ("binary", {0: 0.5, 1: 1}, 600),
        ("binary", {0: 0.2, 1: 1}, 800),
        ("multiclass", {0: 0.5, 1: 1, 2: 1}, 400),
        ("multiclass", {0: 0.75, 1: 1, 2: 1}, 333),
    ],
)
@patch("evalml.pipelines.components.estimators.Estimator.fit")
@patch(
    "evalml.pipelines.BinaryClassificationPipeline.score",
    return_value={"Log Loss Binary": 0.5},
)
@patch(
    "evalml.pipelines.MulticlassClassificationPipeline.score",
    return_value={"Log Loss Multiclass": 0.5},
)
def test_automl_search_dictionary_undersampler(
    mock_multi_score,
    mock_binary_score,
    mock_est_fit,
    problem_type,
    sampling_ratio_dict,
    length,
):
    X = pd.DataFrame({"a": [i for i in range(1200)], "b": [i % 3 for i in range(1200)]})
    if problem_type == "binary":
        y = pd.Series([0] * 900 + [1] * 300)
    else:
        y = pd.Series([0] * 900 + [1] * 150 + [2] * 150)
    pipeline_parameters = {"Undersampler": {"sampling_ratio_dict": sampling_ratio_dict}}
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type=problem_type,
        optimize_thresholds=False,
        sampler_method="Undersampler",
        pipeline_parameters=pipeline_parameters,
    )
    # check that the sampling dict got set properly
    automl.search()
    for result in automl.results["pipeline_results"].values():
        parameters = result["parameters"]
        if "Undersampler" in parameters:
            assert (
                parameters["Undersampler"]["sampling_ratio_dict"] == sampling_ratio_dict
            )
    # assert we sample the right number of elements for our estimator
    assert len(mock_est_fit.call_args[0][0]) == length


@pytest.mark.parametrize(
    "problem_type,sampling_ratio_dict,length",
    [
        ("binary", {0: 1, 1: 0.5}, 900),
        ("binary", {0: 1, 1: 0.8}, 1080),
        ("multiclass", {0: 1, 1: 0.5, 2: 0.5}, 1200),
        ("multiclass", {0: 1, 1: 0.8, 2: 0.8}, 1560),
    ],
)
@patch("evalml.pipelines.components.estimators.Estimator.fit")
@patch(
    "evalml.pipelines.BinaryClassificationPipeline.score",
    return_value={"Log Loss Binary": 0.5},
)
@patch(
    "evalml.pipelines.MulticlassClassificationPipeline.score",
    return_value={"Log Loss Multiclass": 0.5},
)
def test_automl_search_dictionary_oversampler(
    mock_multi_score,
    mock_binary_score,
    mock_est_fit,
    problem_type,
    sampling_ratio_dict,
    length,
):
    pytest.importorskip(
        "imblearn", reason="Skipping tests since imblearn isn't installed"
    )
    # split this from the undersampler since the dictionaries are formatted differently
    X = pd.DataFrame({"a": [i for i in range(1200)], "b": [i % 3 for i in range(1200)]})
    if problem_type == "binary":
        y = pd.Series([0] * 900 + [1] * 300)
    else:
        y = pd.Series([0] * 900 + [1] * 150 + [2] * 150)

    pipeline_parameters = {"Oversampler": {"sampling_ratio_dict": sampling_ratio_dict}}
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type=problem_type,
        sampler_method="Oversampler",
        optimize_thresholds=False,
        pipeline_parameters=pipeline_parameters,
    )
    # check that the sampling dict got set properly
    pipelines = automl.allowed_pipelines
    for pipeline in pipelines:
        seen_under = False
        for comp in pipeline.component_graph:
            if comp.name == "Oversampler":
                assert comp.parameters["sampling_ratio_dict"] == sampling_ratio_dict
                seen_under = True
        assert seen_under
    automl.search()
    # assert we sample the right number of elements for our estimator
    assert len(mock_est_fit.call_args[0][0]) == length


@pytest.mark.parametrize(
    "sampling_ratio_dict,errors",
    [({0: 1, 1: 0.5}, False), ({"majority": 1, "minority": 0.5}, True)],
)
@pytest.mark.parametrize("sampler", ["Undersampler", "Oversampler"])
@patch("evalml.pipelines.components.estimators.Estimator.fit")
@patch(
    "evalml.pipelines.BinaryClassificationPipeline.score",
    return_value={"Log Loss Binary": 0.5},
)
def test_automl_search_sampler_dictionary_keys(
    mock_binary_score,
    mock_est_fit,
    sampler,
    sampling_ratio_dict,
    errors,
    has_minimal_dependencies,
):
    if sampler == "Oversampler" and has_minimal_dependencies:
        pytest.skip("Skipping tests since imblearn isn't installed")
    # split this from the undersampler since the dictionaries are formatted differently
    X = pd.DataFrame({"a": [i for i in range(1200)], "b": [i % 3 for i in range(1200)]})
    y = pd.Series(["majority"] * 900 + ["minority"] * 300)
    pipeline_parameters = {sampler: {"sampling_ratio_dict": sampling_ratio_dict}}
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        error_callback=raise_error_callback,
        sampler_method=sampler,
        optimize_thresholds=False,
        pipeline_parameters=pipeline_parameters,
    )
    if errors:
        with pytest.raises(
            ValueError, match="Dictionary keys are different from target"
        ):
            automl.search()
    else:
        automl.search()


@pytest.mark.parametrize("sampler", ["Undersampler", "Oversampler"])
def test_automl_search_sampler_k_neighbors_param(sampler, has_minimal_dependencies):
    if sampler == "Oversampler" and has_minimal_dependencies:
        pytest.skip("Skipping tests since imblearn isn't installed")
    # split this from the undersampler since the dictionaries are formatted differently
    X = pd.DataFrame({"a": [i for i in range(1200)], "b": [i % 3 for i in range(1200)]})
    y = pd.Series(["majority"] * 900 + ["minority"] * 300)
    pipeline_parameters = {sampler: {"k_neighbors_default": 2}}
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        sampler_method=sampler,
        sampler_balanced_ratio=0.5,
        pipeline_parameters=pipeline_parameters,
    )
    for pipeline in automl.allowed_pipelines:
        seen_under = False
        for comp in pipeline.component_graph:
            if comp.name == sampler:
                assert comp.parameters["k_neighbors_default"] == 2
                seen_under = True
        assert seen_under


@pytest.mark.parametrize(
    "parameters", [None, {"Oversampler": {"k_neighbors_default": 5}}]
)
def test_automl_search_sampler_k_neighbors_no_error(
    parameters, has_minimal_dependencies, fraud_100
):
    # automatically uses SMOTE
    if has_minimal_dependencies:
        pytest.skip("Skipping tests since imblearn isn't installed")
    X, y = fraud_100
    automl = AutoMLSearch(
        X_train=X,
        y_train=y,
        problem_type="binary",
        max_iterations=2,
        pipeline_parameters=parameters,
    )
    # check that the calling this doesn't fail
    automl.search()


@pytest.mark.parametrize(
    "pipeline_parameters,set_values",
    [
        ({"Logistic Regression Classifier": {"penalty": "l1"}}, {}),
        (
            {
                "Undersampler": {"sampling_ratio": 0.05},
                "Random Forest Classifier": {"n_estimators": 10},
            },
            {"Undersampler"},
        ),
    ],
)
def test_time_series_pipeline_parameter_warnings(
    pipeline_parameters, set_values, AutoMLTestEnv, X_y_binary
):
    pipeline_parameters.update(
        {
            "pipeline": {
                "date_index": None,
                "gap": 0,
                "max_delay": 0,
                "forecast_horizon": 2,
            }
        }
    )
    X, y = X_y_binary
    configuration = {
        "date_index": None,
        "gap": 0,
        "max_delay": 0,
        "delay_target": False,
        "delay_features": True,
        "forecast_horizon": 2,
    }
    with warnings.catch_warnings(record=True) as w:
        warnings.filterwarnings("always", category=ParameterNotUsedWarning)
        automl = AutoMLSearch(
            X_train=X,
            y_train=y,
            problem_type="time series binary",
            max_batches=2,
            n_jobs=1,
            pipeline_parameters=pipeline_parameters,
            problem_configuration=configuration,
        )
        env = AutoMLTestEnv("time series binary")
        with env.test_context(score_return_value={automl.objective.name: 1.0}):
            automl.search()
    # We throw a warning about time series being in beta
    assert len(w) == (2 if len(set_values) else 1)
    if len(w) == 2:
        assert w[1].message.components == set_values
