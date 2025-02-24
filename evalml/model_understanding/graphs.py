"""Model understanding graphing utilities."""
import copy
import os
import warnings
from collections import OrderedDict

import numpy as np
import pandas as pd
import woodwork as ww
from sklearn.exceptions import NotFittedError
from sklearn.manifold import TSNE
from sklearn.metrics import auc as sklearn_auc
from sklearn.metrics import confusion_matrix as sklearn_confusion_matrix
from sklearn.metrics import (
    precision_recall_curve as sklearn_precision_recall_curve,
)
from sklearn.metrics import roc_curve as sklearn_roc_curve
from sklearn.preprocessing import LabelBinarizer
from sklearn.tree import export_graphviz
from sklearn.utils.multiclass import unique_labels

import evalml
from evalml.exceptions import (
    NoPositiveLabelException,
    NullsInColumnWarning,
    PartialDependenceError,
    PartialDependenceErrorCode,
)
from evalml.model_family import ModelFamily
from evalml.model_understanding._partial_dependence import (
    _partial_dependence,
    _range_for_dates,
)
from evalml.model_understanding.permutation_importance import (
    calculate_permutation_importance,
)
from evalml.objectives.utils import get_objective
from evalml.problem_types import ProblemTypes
from evalml.utils import import_or_raise, infer_feature_types, jupyter_check


def confusion_matrix(y_true, y_predicted, normalize_method="true"):
    """Confusion matrix for binary and multiclass classification.

    Args:
        y_true (pd.Series or np.ndarray): True binary labels.
        y_predicted (pd.Series or np.ndarray): Predictions from a binary classifier.
        normalize_method ({'true', 'pred', 'all', None}): Normalization method to use, if not None. Supported options are: 'true' to normalize by row, 'pred' to normalize by column, or 'all' to normalize by all values. Defaults to 'true'.

    Returns:
        pd.DataFrame: Confusion matrix. The column header represents the predicted labels while row header represents the actual labels.
    """
    y_true = infer_feature_types(y_true)
    y_predicted = infer_feature_types(y_predicted)
    y_true = y_true.to_numpy()
    y_predicted = y_predicted.to_numpy()
    labels = unique_labels(y_true, y_predicted)
    conf_mat = sklearn_confusion_matrix(y_true, y_predicted)
    conf_mat = pd.DataFrame(conf_mat, index=labels, columns=labels)
    if normalize_method is not None:
        return normalize_confusion_matrix(conf_mat, normalize_method=normalize_method)
    return conf_mat


def normalize_confusion_matrix(conf_mat, normalize_method="true"):
    """Normalizes a confusion matrix.

    Args:
        conf_mat (pd.DataFrame or np.ndarray): Confusion matrix to normalize.
        normalize_method ({'true', 'pred', 'all'}): Normalization method. Supported options are: 'true' to normalize by row, 'pred' to normalize by column, or 'all' to normalize by all values. Defaults to 'true'.

    Returns:
        pd.DataFrame: normalized version of the input confusion matrix. The column header represents the predicted labels while row header represents the actual labels.

    Raises:
        ValueError: If configuration is invalid, or if the sum of a given axis is zero and normalization by axis is specified.
    """
    conf_mat = infer_feature_types(conf_mat)
    col_names = conf_mat.columns

    conf_mat = conf_mat.to_numpy()
    with warnings.catch_warnings(record=True) as w:
        if normalize_method == "true":
            conf_mat = conf_mat.astype("float") / conf_mat.sum(axis=1)[:, np.newaxis]
        elif normalize_method == "pred":
            conf_mat = conf_mat.astype("float") / conf_mat.sum(axis=0)
        elif normalize_method == "all":
            conf_mat = conf_mat.astype("float") / conf_mat.sum().sum()
        else:
            raise ValueError(
                'Invalid value provided for "normalize_method": {}'.format(
                    normalize_method
                )
            )
        if w and "invalid value encountered in" in str(w[0].message):
            raise ValueError(
                "Sum of given axis is 0 and normalization is not possible. Please select another option."
            )
    conf_mat = pd.DataFrame(conf_mat, index=col_names, columns=col_names)
    return conf_mat


def graph_confusion_matrix(
    y_true, y_pred, normalize_method="true", title_addition=None
):
    """Generate and display a confusion matrix plot.

    If `normalize_method` is set, hover text will show raw count, otherwise hover text will show count normalized with method 'true'.

    Args:
        y_true (pd.Series or np.ndarray): True binary labels.
        y_pred (pd.Series or np.ndarray): Predictions from a binary classifier.
        normalize_method ({'true', 'pred', 'all', None}): Normalization method to use, if not None. Supported options are: 'true' to normalize by row, 'pred' to normalize by column, or 'all' to normalize by all values. Defaults to 'true'.
        title_addition (str): If not None, append to plot title. Defaults to None.

    Returns:
        plotly.Figure representing the confusion matrix plot generated.
    """
    _go = import_or_raise(
        "plotly.graph_objects", error_msg="Cannot find dependency plotly.graph_objects"
    )
    _ff = import_or_raise(
        "plotly.figure_factory",
        error_msg="Cannot find dependency plotly.figure_factory",
    )
    if jupyter_check():
        import_or_raise("ipywidgets", warning=True)

    conf_mat = confusion_matrix(y_true, y_pred, normalize_method=None)
    conf_mat_normalized = confusion_matrix(
        y_true, y_pred, normalize_method=normalize_method or "true"
    )
    labels = conf_mat.columns.tolist()

    title = "Confusion matrix{}{}".format(
        "" if title_addition is None else (" " + title_addition),
        ""
        if normalize_method is None
        else (', normalized using method "' + normalize_method + '"'),
    )
    z_data, custom_data = (
        (conf_mat, conf_mat_normalized)
        if normalize_method is None
        else (conf_mat_normalized, conf_mat)
    )
    z_data = z_data.to_numpy()
    z_text = [["{:.3f}".format(y) for y in x] for x in z_data]
    primary_heading, secondary_heading = (
        ("Raw", "Normalized") if normalize_method is None else ("Normalized", "Raw")
    )
    hover_text = (
        "<br><b>"
        + primary_heading
        + " Count</b>: %{z}<br><b>"
        + secondary_heading
        + " Count</b>: %{customdata} <br>"
    )
    # the "<extra> tags at the end are necessary to remove unwanted trace info
    hover_template = (
        "<b>True</b>: %{y}<br><b>Predicted</b>: %{x}" + hover_text + "<extra></extra>"
    )
    layout = _go.Layout(
        title={"text": title},
        xaxis={"title": "Predicted Label", "type": "category", "tickvals": labels},
        yaxis={"title": "True Label", "type": "category", "tickvals": labels},
    )
    fig = _ff.create_annotated_heatmap(
        z_data,
        x=labels,
        y=labels,
        annotation_text=z_text,
        customdata=custom_data,
        hovertemplate=hover_template,
        colorscale="Blues",
        showscale=True,
    )
    fig.update_layout(layout)
    # put xaxis text on bottom to not overlap with title
    fig["layout"]["xaxis"].update(side="bottom")
    # plotly Heatmap y axis defaults to the reverse of what we want: https://community.plotly.com/t/heatmap-y-axis-is-reversed-by-default-going-against-standard-convention-for-matrices/32180
    fig.update_yaxes(autorange="reversed")
    return fig


def precision_recall_curve(y_true, y_pred_proba, pos_label_idx=-1):
    """Given labels and binary classifier predicted probabilities, compute and return the data representing a precision-recall curve.

    Args:
        y_true (pd.Series or np.ndarray): True binary labels.
        y_pred_proba (pd.Series or np.ndarray): Predictions from a binary classifier, before thresholding has been applied. Note this should be the predicted probability for the "true" label.
        pos_label_idx (int): the column index corresponding to the positive class. If predicted probabilities are two-dimensional, this will be used to access the probabilities for the positive class.

    Returns:
        list: Dictionary containing metrics used to generate a precision-recall plot, with the following keys:

                  * `precision`: Precision values.
                  * `recall`: Recall values.
                  * `thresholds`: Threshold values used to produce the precision and recall.
                  * `auc_score`: The area under the ROC curve.

    Raises:
        NoPositiveLabelException: If predicted probabilities do not contain a column at the specified label.
    """
    y_true = infer_feature_types(y_true)
    y_pred_proba = infer_feature_types(y_pred_proba)

    if isinstance(y_pred_proba, pd.DataFrame):
        y_pred_proba_shape = y_pred_proba.shape
        try:
            y_pred_proba = y_pred_proba.iloc[:, pos_label_idx]
        except IndexError:
            raise NoPositiveLabelException(
                f"Predicted probabilities of shape {y_pred_proba_shape} don't contain a column at index {pos_label_idx}"
            )

    precision, recall, thresholds = sklearn_precision_recall_curve(y_true, y_pred_proba)
    auc_score = sklearn_auc(recall, precision)
    return {
        "precision": precision,
        "recall": recall,
        "thresholds": thresholds,
        "auc_score": auc_score,
    }


def graph_precision_recall_curve(y_true, y_pred_proba, title_addition=None):
    """Generate and display a precision-recall plot.

    Args:
        y_true (pd.Series or np.ndarray): True binary labels.
        y_pred_proba (pd.Series or np.ndarray): Predictions from a binary classifier, before thresholding has been applied. Note this should be the predicted probability for the "true" label.
        title_addition (str or None): If not None, append to plot title. Defaults to None.

    Returns:
        plotly.Figure representing the precision-recall plot generated
    """
    _go = import_or_raise(
        "plotly.graph_objects", error_msg="Cannot find dependency plotly.graph_objects"
    )
    if jupyter_check():
        import_or_raise("ipywidgets", warning=True)
    precision_recall_curve_data = precision_recall_curve(y_true, y_pred_proba)
    title = "Precision-Recall{}".format(
        "" if title_addition is None else (" " + title_addition)
    )
    layout = _go.Layout(
        title={"text": title},
        xaxis={"title": "Recall", "range": [-0.05, 1.05]},
        yaxis={"title": "Precision", "range": [-0.05, 1.05]},
    )
    data = []
    data.append(
        _go.Scatter(
            x=precision_recall_curve_data["recall"],
            y=precision_recall_curve_data["precision"],
            name="Precision-Recall (AUC {:06f})".format(
                precision_recall_curve_data["auc_score"]
            ),
            line=dict(width=3),
        )
    )
    return _go.Figure(layout=layout, data=data)


def roc_curve(y_true, y_pred_proba):
    """Given labels and classifier predicted probabilities, compute and return the data representing a Receiver Operating Characteristic (ROC) curve. Works with binary or multiclass problems.

    Args:
        y_true (pd.Series or np.ndarray): True labels.
        y_pred_proba (pd.Series or np.ndarray): Predictions from a classifier, before thresholding has been applied.

    Returns:
        list(dict): A list of dictionaries (with one for each class) is returned. Binary classification problems return a list with one dictionary.
            Each dictionary contains metrics used to generate an ROC plot with the following keys:
                  * `fpr_rate`: False positive rate.
                  * `tpr_rate`: True positive rate.
                  * `threshold`: Threshold values used to produce each pair of true/false positive rates.
                  * `auc_score`: The area under the ROC curve.
    """
    y_true = infer_feature_types(y_true).to_numpy()
    y_pred_proba = infer_feature_types(y_pred_proba).to_numpy()

    if len(y_pred_proba.shape) == 1:
        y_pred_proba = y_pred_proba.reshape(-1, 1)
    if y_pred_proba.shape[1] == 2:
        y_pred_proba = y_pred_proba[:, 1].reshape(-1, 1)
    nan_indices = np.logical_or(pd.isna(y_true), np.isnan(y_pred_proba).any(axis=1))
    y_true = y_true[~nan_indices]
    y_pred_proba = y_pred_proba[~nan_indices]

    lb = LabelBinarizer()
    lb.fit(np.unique(y_true))
    y_one_hot_true = lb.transform(y_true)
    n_classes = y_one_hot_true.shape[1]

    curve_data = []
    for i in range(n_classes):
        fpr_rates, tpr_rates, thresholds = sklearn_roc_curve(
            y_one_hot_true[:, i], y_pred_proba[:, i]
        )
        auc_score = sklearn_auc(fpr_rates, tpr_rates)
        curve_data.append(
            {
                "fpr_rates": fpr_rates,
                "tpr_rates": tpr_rates,
                "thresholds": thresholds,
                "auc_score": auc_score,
            }
        )

    return curve_data


def graph_roc_curve(y_true, y_pred_proba, custom_class_names=None, title_addition=None):
    """Generate and display a Receiver Operating Characteristic (ROC) plot for binary and multiclass classification problems.

    Args:
        y_true (pd.Series or np.ndarray): True labels.
        y_pred_proba (pd.Series or np.ndarray): Predictions from a classifier, before thresholding has been applied. Note this should a one dimensional array with the predicted probability for the "true" label in the binary case.
        custom_class_names (list or None): If not None, custom labels for classes. Defaults to None.
        title_addition (str or None): if not None, append to plot title. Defaults to None.

    Returns:
        plotly.Figure representing the ROC plot generated

    Raises:
        ValueError: If the number of custom class names does not match number of classes in the input data.
    """
    _go = import_or_raise(
        "plotly.graph_objects", error_msg="Cannot find dependency plotly.graph_objects"
    )
    if jupyter_check():
        import_or_raise("ipywidgets", warning=True)

    title = "Receiver Operating Characteristic{}".format(
        "" if title_addition is None else (" " + title_addition)
    )
    layout = _go.Layout(
        title={"text": title},
        xaxis={"title": "False Positive Rate", "range": [-0.05, 1.05]},
        yaxis={"title": "True Positive Rate", "range": [-0.05, 1.05]},
    )

    all_curve_data = roc_curve(y_true, y_pred_proba)
    graph_data = []

    n_classes = len(all_curve_data)

    if custom_class_names and len(custom_class_names) != n_classes:
        raise ValueError(
            "Number of custom class names does not match number of classes"
        )

    for i in range(n_classes):
        roc_curve_data = all_curve_data[i]
        name = i + 1 if custom_class_names is None else custom_class_names[i]
        graph_data.append(
            _go.Scatter(
                x=roc_curve_data["fpr_rates"],
                y=roc_curve_data["tpr_rates"],
                hovertemplate="(False Postive Rate: %{x}, True Positive Rate: %{y})<br>"
                + "Threshold: %{text}",
                name=f"Class {name} (AUC {roc_curve_data['auc_score']:.06f})",
                text=roc_curve_data["thresholds"],
                line=dict(width=3),
            )
        )
    graph_data.append(
        _go.Scatter(
            x=[0, 1], y=[0, 1], name="Trivial Model (AUC 0.5)", line=dict(dash="dash")
        )
    )
    return _go.Figure(layout=layout, data=graph_data)


def graph_permutation_importance(pipeline, X, y, objective, importance_threshold=0):
    """Generate a bar graph of the pipeline's permutation importance.

    Args:
        pipeline (PipelineBase or subclass): Fitted pipeline.
        X (pd.DataFrame): The input data used to score and compute permutation importance.
        y (pd.Series): The target data.
        objective (str, ObjectiveBase): Objective to score on.
        importance_threshold (float, optional): If provided, graph features with a permutation importance whose absolute value is larger than importance_threshold. Defaults to 0.

    Returns:
        plotly.Figure, a bar graph showing features and their respective permutation importance.

    Raises:
        ValueError: If importance_threshold is not greater than or equal to 0.
    """
    go = import_or_raise(
        "plotly.graph_objects", error_msg="Cannot find dependency plotly.graph_objects"
    )
    if jupyter_check():
        import_or_raise("ipywidgets", warning=True)

    perm_importance = calculate_permutation_importance(pipeline, X, y, objective)
    perm_importance["importance"] = perm_importance["importance"]

    if importance_threshold < 0:
        raise ValueError(
            f"Provided importance threshold of {importance_threshold} must be greater than or equal to 0"
        )
    # Remove features with close to zero importance
    perm_importance = perm_importance[
        abs(perm_importance["importance"]) >= importance_threshold
    ]
    # List is reversed to go from ascending order to descending order
    perm_importance = perm_importance.iloc[::-1]

    title = "Permutation Importance"
    subtitle = (
        "The relative importance of each input feature's "
        "overall influence on the pipelines' predictions, computed using "
        "the permutation importance algorithm."
    )
    data = [
        go.Bar(
            x=perm_importance["importance"],
            y=perm_importance["feature"],
            orientation="h",
        )
    ]

    layout = {
        "title": "{0}<br><sub>{1}</sub>".format(title, subtitle),
        "height": 800,
        "xaxis_title": "Permutation Importance",
        "yaxis_title": "Feature",
        "yaxis": {"type": "category"},
    }

    fig = go.Figure(data=data, layout=layout)
    return fig


def binary_objective_vs_threshold(pipeline, X, y, objective, steps=100):
    """Computes objective score as a function of potential binary classification decision thresholds for a fitted binary classification pipeline.

    Args:
        pipeline (BinaryClassificationPipeline obj): Fitted binary classification pipeline.
        X (pd.DataFrame): The input data used to compute objective score.
        y (pd.Series): The target labels.
        objective (ObjectiveBase obj, str): Objective used to score.
        steps (int): Number of intervals to divide and calculate objective score at.

    Returns:
        pd.DataFrame: DataFrame with thresholds and the corresponding objective score calculated at each threshold.

    Raises:
        ValueError: If objective is not a binary classification objective.
        ValueError: If objective's `score_needs_proba` is not False.
    """
    objective = get_objective(objective, return_instance=True)
    if not objective.is_defined_for_problem_type(ProblemTypes.BINARY):
        raise ValueError(
            "`binary_objective_vs_threshold` can only be calculated for binary classification objectives"
        )
    if objective.score_needs_proba:
        raise ValueError("Objective `score_needs_proba` must be False")

    pipeline_tmp = copy.copy(pipeline)
    thresholds = np.linspace(0, 1, steps + 1)
    costs = []
    for threshold in thresholds:
        pipeline_tmp.threshold = threshold
        scores = pipeline_tmp.score(X, y, [objective])
        costs.append(scores[objective.name])
    df = pd.DataFrame({"threshold": thresholds, "score": costs})
    return df


def graph_binary_objective_vs_threshold(pipeline, X, y, objective, steps=100):
    """Generates a plot graphing objective score vs. decision thresholds for a fitted binary classification pipeline.

    Args:
        pipeline (PipelineBase or subclass): Fitted pipeline
        X (pd.DataFrame): The input data used to score and compute scores
        y (pd.Series): The target labels
        objective (ObjectiveBase obj, str): Objective used to score, shown on the y-axis of the graph
        steps (int): Number of intervals to divide and calculate objective score at

    Returns:
        plotly.Figure representing the objective score vs. threshold graph generated

    """
    _go = import_or_raise(
        "plotly.graph_objects", error_msg="Cannot find dependency plotly.graph_objects"
    )
    if jupyter_check():
        import_or_raise("ipywidgets", warning=True)

    objective = get_objective(objective, return_instance=True)
    df = binary_objective_vs_threshold(pipeline, X, y, objective, steps)
    title = f"{objective.name} Scores vs. Thresholds"
    layout = _go.Layout(
        title={"text": title},
        xaxis={"title": "Threshold", "range": _calculate_axis_range(df["threshold"])},
        yaxis={
            "title": f"{objective.name} Scores vs. Binary Classification Decision Threshold",
            "range": _calculate_axis_range(df["score"]),
        },
    )
    data = []
    data.append(_go.Scatter(x=df["threshold"], y=df["score"], line=dict(width=3)))
    return _go.Figure(layout=layout, data=data)


def _is_feature_of_type(feature, X, ltype):
    """Determine whether the feature the user passed in to partial dependence is a Woodwork logical type."""
    if isinstance(feature, int):
        is_type = isinstance(X.ww.logical_types[X.columns[feature]], ltype)
    else:
        is_type = isinstance(X.ww.logical_types[feature], ltype)
    return is_type


def _put_categorical_feature_first(features, first_feature_categorical):
    """If the user is doing a two-way partial dependence plot and one of the features is categorical, we need to ensure the categorical feature is the first element in the tuple that's passed to sklearn.

    This is because in the two-way grid calculation, sklearn will try to coerce every element of the grid to the
    type of the first feature in the tuple. If we put the categorical feature first, the grid will be of type 'object'
    which can accommodate both categorical and numeric data. If we put the numeric feature first, the grid will be of
    type float64 and we can't coerce categoricals to float64 dtype.
    """
    new_features = features if first_feature_categorical else (features[1], features[0])
    return new_features


def _get_feature_names_from_str_or_col_index(X, names_or_col_indices):
    """Helper function to map the user-input features param to column names."""
    feature_list = []
    for name_or_index in names_or_col_indices:
        if isinstance(name_or_index, int):
            feature_list.append(X.columns[name_or_index])
        else:
            feature_list.append(name_or_index)
    return feature_list


def _raise_value_error_if_any_features_all_nan(df):
    """Helper for partial dependence data validation."""
    nan_pct = df.isna().mean()
    all_nan = nan_pct[nan_pct == 1].index.tolist()
    all_nan = [f"'{name}'" for name in all_nan]

    if all_nan:
        raise PartialDependenceError(
            "The following features have all NaN values and so the "
            f"partial dependence cannot be computed: {', '.join(all_nan)}",
            PartialDependenceErrorCode.FEATURE_IS_ALL_NANS,
        )


def _raise_value_error_if_mostly_one_value(df, percentile):
    """Helper for partial dependence data validation."""
    one_value = []
    values = []

    for col in df.columns:
        normalized_counts = df[col].value_counts(normalize=True) + 0.01
        normalized_counts = normalized_counts[normalized_counts > percentile]
        if not normalized_counts.empty:
            one_value.append(f"'{col}'")
            values.append(str(normalized_counts.index[0]))

    if one_value:
        raise PartialDependenceError(
            f"Features ({', '.join(one_value)}) are mostly one value, ({', '.join(values)}), "
            f"and cannot be used to compute partial dependence. Try raising the upper percentage value.",
            PartialDependenceErrorCode.FEATURE_IS_MOSTLY_ONE_VALUE,
        )


def partial_dependence(
    pipeline, X, features, percentiles=(0.05, 0.95), grid_resolution=100, kind="average"
):
    """Calculates one or two-way partial dependence.

    If a single integer or string is given for features, one-way partial dependence is calculated. If
    a tuple of two integers or strings is given, two-way partial dependence
    is calculated with the first feature in the y-axis and second feature in the x-axis.

    Args:
        pipeline (PipelineBase or subclass): Fitted pipeline
        X (pd.DataFrame, np.ndarray): The input data used to generate a grid of values
            for feature where partial dependence will be calculated at
        features (int, string, tuple[int or string]): The target feature for which to create the partial dependence plot for.
            If features is an int, it must be the index of the feature to use.
            If features is a string, it must be a valid column name in X.
            If features is a tuple of int/strings, it must contain valid column integers/names in X.
        percentiles (tuple[float]): The lower and upper percentile used to create the extreme values for the grid.
            Must be in [0, 1]. Defaults to (0.05, 0.95).
        grid_resolution (int): Number of samples of feature(s) for partial dependence plot.  If this value
            is less than the maximum number of categories present in categorical data within X, it will be
            set to the max number of categories + 1. Defaults to 100.
        kind ({'average', 'individual', 'both'}): The type of predictions to return. 'individual' will return the predictions for
            all of the points in the grid for each sample in X. 'average' will return the predictions for all of the points in
            the grid but averaged over all of the samples in X.

    Returns:
        pd.DataFrame, list(pd.DataFrame), or tuple(pd.DataFrame, list(pd.DataFrame)):
            When `kind='average'`: DataFrame with averaged predictions for all points in the grid averaged
            over all samples of X and the values used to calculate those predictions.

            When `kind='individual'`: DataFrame with individual predictions for all points in the grid for each sample
            of X and the values used to calculate those predictions. If a two-way partial dependence is calculated, then
            the result is a list of DataFrames with each DataFrame representing one sample's predictions.

            When `kind='both'`: A tuple consisting of the averaged predictions (in a DataFrame) over all samples of X and the individual
            predictions (in a list of DataFrames) for each sample of X.

            In the one-way case: The dataframe will contain two columns, "feature_values" (grid points at which the
            partial dependence was calculated) and "partial_dependence" (the partial dependence at that feature value).
            For classification problems, there will be a third column called "class_label" (the class label for which
            the partial dependence was calculated). For binary classification, the partial dependence is only calculated
            for the "positive" class.

            In the two-way case: The data frame will contain grid_resolution number of columns and rows where the
            index and column headers are the sampled values of the first and second features, respectively, used to make
            the partial dependence contour. The values of the data frame contain the partial dependence data for each
            feature value pair.

    Raises:
        ValueError: Error during call to scikit-learn's partial dependence method.
        Exception: All other errors during calculation.
        PartialDependenceError: if the user provides a tuple of not exactly two features.
        PartialDependenceError: if the provided pipeline isn't fitted.
        PartialDependenceError: if the provided pipeline is a Baseline pipeline.
        PartialDependenceError: if any of the features passed in are completely NaN
        PartialDependenceError: if any of the features are low-variance. Defined as having one value occurring more than the upper
            percentile passed by the user. By default 95%.
    """
    try:
        # Dynamically set the grid resolution to the maximum number of values
        # in the categorical/datetime variables if there are more categories/datetime values than resolution cells
        X = infer_feature_types(X)

        if isinstance(features, (list, tuple)):
            is_categorical = [
                _is_feature_of_type(f, X, ww.logical_types.Categorical)
                for f in features
            ]
            is_datetime = [
                _is_feature_of_type(f, X, ww.logical_types.Datetime) for f in features
            ]
        else:
            is_categorical = [
                _is_feature_of_type(features, X, ww.logical_types.Categorical)
            ]
            is_datetime = [_is_feature_of_type(features, X, ww.logical_types.Datetime)]

        if isinstance(features, (list, tuple)):
            if any(is_datetime) and len(features) > 1:
                raise PartialDependenceError(
                    "Two-way partial dependence is not supported for datetime columns.",
                    code=PartialDependenceErrorCode.TWO_WAY_REQUESTED_FOR_DATES,
                )
            if len(features) != 2:
                raise PartialDependenceError(
                    "Too many features given to graph_partial_dependence.  Only one or two-way partial "
                    "dependence is supported.",
                    code=PartialDependenceErrorCode.TOO_MANY_FEATURES,
                )
            if not (
                all([isinstance(x, str) for x in features])
                or all([isinstance(x, int) for x in features])
            ):
                raise PartialDependenceError(
                    "Features provided must be a tuple entirely of integers or strings, not a mixture of both.",
                    code=PartialDependenceErrorCode.FEATURES_ARGUMENT_INCORRECT_TYPES,
                )
            feature_names = _get_feature_names_from_str_or_col_index(X, features)
        else:
            feature_names = _get_feature_names_from_str_or_col_index(X, [features])

        X_features = X.ww.loc[:, feature_names]
        X_unknown = X_features.ww.select("unknown")
        if len(X_unknown.columns):
            # We drop the unknown columns in the pipelines, so we cannot calculate partial dependence for these
            raise PartialDependenceError(
                f"Columns {X_unknown.columns.values} are of type 'Unknown', which cannot be used for partial dependence",
                code=PartialDependenceErrorCode.INVALID_FEATURE_TYPE,
            )

        X_not_allowed = X_features.ww.select(["URL", "EmailAddress", "NaturalLanguage"])
        if len(X_not_allowed.columns):
            # these three logical types aren't allowed for partial dependence
            types = sorted(
                set(X_not_allowed.ww.types["Logical Type"].astype(str).tolist())
            )
            raise PartialDependenceError(
                f"Columns {X_not_allowed.columns.tolist()} are of types {types}, which cannot be used for partial dependence",
                code=PartialDependenceErrorCode.INVALID_FEATURE_TYPE,
            )

        X_cats = X_features.ww.select("categorical")
        X_dt = X_features.ww.select("datetime")

        if any(is_categorical):
            custom_range = {
                cat: list(X_cats[cat].dropna().unique()) for cat in X_cats.columns
            }
        elif any(is_datetime):
            custom_range = {
                date: _range_for_dates(
                    X_dt.ww.loc[:, date], percentiles, grid_resolution
                )
                for date in X_dt.columns
            }
        else:
            custom_range = {}

        if not pipeline._is_fitted:
            raise PartialDependenceError(
                "Pipeline to calculate partial dependence for must be fitted",
                code=PartialDependenceErrorCode.UNFITTED_PIPELINE,
            )
        if pipeline.model_family == ModelFamily.BASELINE:
            raise PartialDependenceError(
                "Partial dependence plots are not supported for Baseline pipelines",
                code=PartialDependenceErrorCode.PIPELINE_IS_BASELINE,
            )

        feature_list = X[feature_names]
        _raise_value_error_if_any_features_all_nan(feature_list)

        if feature_list.isnull().sum().any():
            warnings.warn(
                "There are null values in the features, which will cause NaN values in the partial dependence output. "
                "Fill in these values to remove the NaN values.",
                NullsInColumnWarning,
            )

        _raise_value_error_if_mostly_one_value(feature_list, percentiles[1])

        try:
            preds = _partial_dependence(
                pipeline,
                X=X,
                features=feature_names,
                percentiles=percentiles,
                grid_resolution=grid_resolution,
                kind=kind,
                custom_range=custom_range,
            )
        except ValueError as e:
            if "percentiles are too close to each other" in str(e):
                raise PartialDependenceError(
                    "The scale of these features is too small and results in"
                    "percentiles that are too close together.  Partial dependence"
                    "cannot be computed for these types of features.  Consider"
                    "scaling the features so that they differ by > 10E-7",
                    code=PartialDependenceErrorCode.COMPUTED_PERCENTILES_TOO_CLOSE,
                )
            else:
                raise e

        classes = None
        if isinstance(pipeline, evalml.pipelines.BinaryClassificationPipeline):
            classes = [pipeline.classes_[1]]
        elif isinstance(pipeline, evalml.pipelines.MulticlassClassificationPipeline):
            classes = pipeline.classes_

        values = preds["values"]
        if kind in ["average", "both"]:
            avg_pred = preds["average"]
            if isinstance(features, (int, str)):
                avg_data = pd.DataFrame(
                    {
                        "feature_values": np.tile(values[0], avg_pred.shape[0]),
                        "partial_dependence": np.concatenate(
                            [pred for pred in avg_pred]
                        ),
                    }
                )
            elif isinstance(features, (list, tuple)):
                avg_data = pd.DataFrame(avg_pred.reshape((-1, avg_pred.shape[-1])))
                avg_data.columns = values[1]
                avg_data.index = np.tile(values[0], avg_pred.shape[0])

            if classes is not None:
                avg_data["class_label"] = np.repeat(classes, len(values[0]))

        if kind in ["individual", "both"]:
            ind_preds = preds["individual"]
            if isinstance(features, (int, str)):
                ind_data = list()
                for label in ind_preds:
                    ind_data.append(pd.DataFrame(label).T)

                ind_data = pd.concat(ind_data)
                ind_data.columns = [f"Sample {i}" for i in range(len(ind_preds[0]))]

                if classes is not None:
                    ind_data["class_label"] = np.repeat(classes, len(values[0]))
                ind_data.insert(
                    0, "feature_values", np.tile(values[0], ind_preds.shape[0])
                )

            elif isinstance(features, (list, tuple)):
                ind_data = list()
                for n, label in enumerate(ind_preds):
                    for i, sample in enumerate(label):
                        ind_df = pd.DataFrame(sample.reshape((-1, sample.shape[-1])))
                        ind_df.columns = values[1]
                        ind_df.index = values[0]

                        if n == 0:
                            ind_data.append(ind_df)
                        else:
                            ind_data[i] = pd.concat([ind_data[i], ind_df])

                for sample in ind_data:
                    sample["class_label"] = np.repeat(classes, len(values[0]))

        if kind == "both":
            return (avg_data, ind_data)
        elif kind == "individual":
            return ind_data
        elif kind == "average":
            return avg_data
    except Exception as e:
        if isinstance(e, PartialDependenceError):
            raise e
        else:
            raise PartialDependenceError(
                str(e), PartialDependenceErrorCode.ALL_OTHER_ERRORS
            ) from e


def _update_fig_with_two_way_partial_dependence(
    _go,
    fig,
    label_df,
    part_dep,
    features,
    is_categorical,
    label=None,
    row=None,
    col=None,
):
    """Helper for formatting the two-way partial dependence plot."""
    y = label_df.index
    x = label_df.columns
    z = label_df.values
    if not any(is_categorical):
        # No features are categorical. In this case, we pass both x and y data to the Contour plot so that
        # plotly can figure out the axis formatting for us.
        kwargs = {"x": x, "y": y}
        fig.update_xaxes(
            title=f"{features[1]}",
            range=_calculate_axis_range(
                np.array([x for x in part_dep.columns if x != "class_label"])
            ),
            row=row,
            col=col,
        )
        fig.update_yaxes(range=_calculate_axis_range(part_dep.index), row=row, col=col)
    elif sum(is_categorical) == 1:
        # One feature is categorical. Since we put the categorical feature first, the numeric feature will be the x
        # axis. So we pass the x to the Contour plot so that plotly can format it for us.
        # Since the y axis is a categorical value, we will set the y tickmarks ourselves. Passing y to the contour plot
        # in this case will "work" but the formatting will look bad.
        kwargs = {"x": x}
        fig.update_xaxes(
            title=f"{features[1]}",
            range=_calculate_axis_range(
                np.array([x for x in part_dep.columns if x != "class_label"])
            ),
            row=row,
            col=col,
        )
        fig.update_yaxes(
            tickmode="array",
            tickvals=list(range(label_df.shape[0])),
            ticktext=list(label_df.index),
            row=row,
            col=col,
        )
    else:
        # Both features are categorical so we must format both axes ourselves.
        kwargs = {}
        fig.update_yaxes(
            tickmode="array",
            tickvals=list(range(label_df.shape[0])),
            ticktext=list(label_df.index),
            row=row,
            col=col,
        )
        fig.update_xaxes(
            tickmode="array",
            tickvals=list(range(label_df.shape[1])),
            ticktext=list(label_df.columns),
            row=row,
            col=col,
        )
    fig.add_trace(
        _go.Contour(z=z, name=label, coloraxis="coloraxis", **kwargs), row=row, col=col
    )


def graph_partial_dependence(
    pipeline, X, features, class_label=None, grid_resolution=100, kind="average"
):
    """Create an one-way or two-way partial dependence plot.

    Passing a single integer or string as features will create a one-way partial dependence plot with the feature values
    plotted against the partial dependence.  Passing features a tuple of int/strings will create
    a two-way partial dependence plot with a contour of feature[0] in the y-axis, feature[1]
    in the x-axis and the partial dependence in the z-axis.

    Args:
        pipeline (PipelineBase or subclass): Fitted pipeline.
        X (pd.DataFrame, np.ndarray): The input data used to generate a grid of values
            for feature where partial dependence will be calculated at.
        features (int, string, tuple[int or string]): The target feature for which to create the partial dependence plot for.
            If features is an int, it must be the index of the feature to use.
            If features is a string, it must be a valid column name in X.
            If features is a tuple of strings, it must contain valid column int/names in X.
        class_label (string, optional): Name of class to plot for multiclass problems. If None, will plot
            the partial dependence for each class. This argument does not change behavior for regression or binary
            classification pipelines. For binary classification, the partial dependence for the positive label will
            always be displayed. Defaults to None.
        grid_resolution (int): Number of samples of feature(s) for partial dependence plot.
        kind ({'average', 'individual', 'both'}): Type of partial dependence to plot. 'average' creates a regular partial dependence
             (PD) graph, 'individual' creates an individual conditional expectation (ICE) plot, and 'both' creates a
             single-figure PD and ICE plot. ICE plots can only be shown for one-way partial dependence plots.

    Returns:
        plotly.graph_objects.Figure: figure object containing the partial dependence data for plotting

    Raises:
        PartialDependenceError: if a graph is requested for a class name that isn't present in the pipeline.
        PartialDependenceError: if an ICE plot is requested for a two-way partial dependence.
    """
    X = infer_feature_types(X)
    if isinstance(features, (list, tuple)):
        mode = "two-way"
        is_categorical = [
            _is_feature_of_type(f, X, ww.logical_types.Categorical) for f in features
        ]
        if any(is_categorical):
            features = _put_categorical_feature_first(features, is_categorical[0])
        if kind == "individual" or kind == "both":
            raise PartialDependenceError(
                "Individual conditional expectation plot can only be created with a one-way partial dependence plot",
                PartialDependenceErrorCode.ICE_PLOT_REQUESTED_FOR_TWO_WAY_PLOT,
            )
    elif isinstance(features, (int, str)):
        mode = "one-way"
        is_categorical = _is_feature_of_type(features, X, ww.logical_types.Categorical)

    _go = import_or_raise(
        "plotly.graph_objects", error_msg="Cannot find dependency plotly.graph_objects"
    )
    if jupyter_check():
        import_or_raise("ipywidgets", warning=True)
    if (
        isinstance(pipeline, evalml.pipelines.MulticlassClassificationPipeline)
        and class_label is not None
    ):
        if class_label not in pipeline.classes_:
            msg = f"Class {class_label} is not one of the classes the pipeline was fit on: {', '.join(list(pipeline.classes_))}"
            raise PartialDependenceError(
                msg, code=PartialDependenceErrorCode.INVALID_CLASS_LABEL
            )

    part_dep = partial_dependence(
        pipeline, X, features=features, grid_resolution=grid_resolution, kind=kind
    )

    ice_data = None
    if kind == "both":
        part_dep, ice_data = part_dep
    elif kind == "individual":
        ice_data = part_dep
        part_dep = None

    if mode == "two-way":
        title = f"Partial Dependence of '{features[0]}' vs. '{features[1]}'"
        layout = _go.Layout(
            title={"text": title},
            xaxis={"title": f"{features[1]}"},
            yaxis={"title": f"{features[0]}"},
            showlegend=True,
        )
    elif mode == "one-way":
        feature_name = str(features)
        if kind == "individual":
            title = f"Individual Conditional Expectation of '{feature_name}'"
        elif kind == "average":
            title = f"Partial Dependence of '{feature_name}'"
        else:
            title = f"Partial Dependence of '{feature_name}' <br><sub>Including Individual Conditional Expectation Plot</sub>"
        layout = _go.Layout(
            title={"text": title},
            xaxis={"title": f"{feature_name}"},
            yaxis={"title": "Partial Dependence"},
            showlegend=True,
        )

    fig = _go.Figure(layout=layout)
    if isinstance(pipeline, evalml.pipelines.MulticlassClassificationPipeline):
        class_labels = [class_label] if class_label is not None else pipeline.classes_
        _subplots = import_or_raise(
            "plotly.subplots", error_msg="Cannot find dependency plotly.graph_objects"
        )

        # If the user passes in a value for class_label, we want to create a 1 x 1 subplot or else there would
        # be an empty column in the plot and it would look awkward
        rows, cols = (
            ((len(class_labels) + 1) // 2, 2)
            if len(class_labels) > 1
            else (1, len(class_labels))
        )

        class_labels_mapping = {
            class_label: str(class_label) for class_label in class_labels
        }
        # Don't specify share_xaxis and share_yaxis so that we get tickmarks in each subplot
        fig = _subplots.make_subplots(rows=rows, cols=cols, subplot_titles=class_labels)
        for i, label in enumerate(class_labels):
            label_df = (
                part_dep.loc[part_dep.class_label == label]
                if part_dep is not None
                else ice_data.loc[ice_data.class_label == label]
            )
            row = (i + 2) // 2
            col = (i % 2) + 1
            if ice_data is not None and kind == "individual":
                fig = _add_ice_plot(_go, fig, ice_data, row=row, col=col, label=label)
            else:
                label_df.drop(columns=["class_label"], inplace=True)
                if mode == "two-way":
                    _update_fig_with_two_way_partial_dependence(
                        _go,
                        fig,
                        label_df,
                        part_dep,
                        features,
                        is_categorical,
                        label,
                        row,
                        col,
                    )
                elif mode == "one-way":
                    x = label_df["feature_values"]
                    y = label_df["partial_dependence"]
                    if is_categorical:
                        trace = _go.Bar(x=x, y=y, name=label)
                    else:
                        if ice_data is not None:
                            fig = _add_ice_plot(
                                _go, fig, ice_data, row=row, col=col, label=label
                            )
                        trace = _go.Scatter(
                            x=x,
                            y=y,
                            line=dict(width=3, color="rgb(99,110,250)"),
                            name="Partial Dependence: " + class_labels_mapping[label],
                        )
                    fig.add_trace(trace, row=row, col=col)

        fig.update_layout(layout)

        if mode == "two-way":
            fig.update_layout(coloraxis=dict(colorscale="Bluered_r"), showlegend=False)
        elif mode == "one-way":
            title = f"{feature_name}"
            x_scale_df = (
                part_dep["feature_values"]
                if part_dep is not None
                else ice_data["feature_values"]
            )
            xrange = _calculate_axis_range(x_scale_df) if not is_categorical else None
            yrange = _calculate_axis_range(
                ice_data.drop("class_label", axis=1)
                if ice_data is not None
                else part_dep["partial_dependence"]
            )
            fig.update_xaxes(title=title, range=xrange)
            fig.update_yaxes(range=yrange)
    elif kind == "individual" and ice_data is not None:
        fig = _add_ice_plot(_go, fig, ice_data)
    elif part_dep is not None:
        if ice_data is not None and not is_categorical:
            fig = _add_ice_plot(_go, fig, ice_data)
        if "class_label" in part_dep.columns:
            part_dep.drop(columns=["class_label"], inplace=True)
        if mode == "two-way":
            _update_fig_with_two_way_partial_dependence(
                _go,
                fig,
                part_dep,
                part_dep,
                features,
                is_categorical,
                label="Partial Dependence",
                row=None,
                col=None,
            )
        elif mode == "one-way":
            if is_categorical:
                trace = _go.Bar(
                    x=part_dep["feature_values"],
                    y=part_dep["partial_dependence"],
                    name="Partial Dependence",
                )
            else:
                trace = _go.Scatter(
                    x=part_dep["feature_values"],
                    y=part_dep["partial_dependence"],
                    name="Partial Dependence",
                    line=dict(width=3, color="rgb(99,110,250)"),
                )
            fig.add_trace(trace)
    return fig


def _add_ice_plot(_go, fig, ice_data, label=None, row=None, col=None):
    x = ice_data["feature_values"]
    y = ice_data
    if "class_label" in ice_data.columns:
        if label:
            y = y[y["class_label"] == label]
        y.drop(columns=["class_label"], inplace=True)
    y = y.drop(columns=["feature_values"])
    for i, sample in enumerate(y):
        fig.add_trace(
            _go.Scatter(
                x=x,
                y=y[sample],
                line=dict(width=0.5, color="gray"),
                name=f"Individual Conditional Expectation{': ' + label if label else ''}",
                legendgroup="ICE" + label if label else "ICE",
                showlegend=True if i == 0 else False,
            ),
            row=row,
            col=col,
        )
    return fig


def _calculate_axis_range(arr):
    """Helper method to help calculate the appropriate range for an axis based on the data to graph."""
    max_value = arr.max()
    min_value = arr.min()
    margins = abs(max_value - min_value) * 0.05
    return [min_value - margins, max_value + margins]


def get_prediction_vs_actual_data(y_true, y_pred, outlier_threshold=None):
    """Combines y_true and y_pred into a single dataframe and adds a column for outliers. Used in `graph_prediction_vs_actual()`.

    Args:
        y_true (pd.Series, or np.ndarray): The real target values of the data
        y_pred (pd.Series, or np.ndarray): The predicted values outputted by the regression model.
        outlier_threshold (int, float): A positive threshold for what is considered an outlier value. This value is compared to the absolute difference
                                 between each value of y_true and y_pred. Values within this threshold will be blue, otherwise they will be yellow.
                                 Defaults to None.

    Returns:
        pd.DataFrame with the following columns:
                * `prediction`: Predicted values from regression model.
                * `actual`: Real target values.
                * `outlier`: Colors indicating which values are in the threshold for what is considered an outlier value.

    Raises:
        ValueError: If threshold is not positive.
    """
    if outlier_threshold and outlier_threshold <= 0:
        raise ValueError(
            f"Threshold must be positive! Provided threshold is {outlier_threshold}"
        )

    y_true = infer_feature_types(y_true)
    y_pred = infer_feature_types(y_pred)

    predictions = y_pred.reset_index(drop=True)
    actual = y_true.reset_index(drop=True)
    data = pd.concat([pd.Series(predictions), pd.Series(actual)], axis=1)
    data.columns = ["prediction", "actual"]
    if outlier_threshold:
        data["outlier"] = np.where(
            (abs(data["prediction"] - data["actual"]) >= outlier_threshold),
            "#ffff00",
            "#0000ff",
        )
    else:
        data["outlier"] = "#0000ff"
    return data


def graph_prediction_vs_actual(y_true, y_pred, outlier_threshold=None):
    """Generate a scatter plot comparing the true and predicted values. Used for regression plotting.

    Args:
        y_true (pd.Series): The real target values of the data.
        y_pred (pd.Series): The predicted values outputted by the regression model.
        outlier_threshold (int, float): A positive threshold for what is considered an outlier value. This value is compared to the absolute difference
                                 between each value of y_true and y_pred. Values within this threshold will be blue, otherwise they will be yellow.
                                 Defaults to None.

    Returns:
        plotly.Figure representing the predicted vs. actual values graph

    Raises:
        ValueError: If threshold is not positive.
    """
    _go = import_or_raise(
        "plotly.graph_objects", error_msg="Cannot find dependency plotly.graph_objects"
    )
    if jupyter_check():
        import_or_raise("ipywidgets", warning=True)

    if outlier_threshold and outlier_threshold <= 0:
        raise ValueError(
            f"Threshold must be positive! Provided threshold is {outlier_threshold}"
        )

    df = get_prediction_vs_actual_data(y_true, y_pred, outlier_threshold)
    data = []

    x_axis = _calculate_axis_range(df["prediction"])
    y_axis = _calculate_axis_range(df["actual"])
    x_y_line = [min(x_axis[0], y_axis[0]), max(x_axis[1], y_axis[1])]
    data.append(
        _go.Scatter(x=x_y_line, y=x_y_line, name="y = x line", line_color="grey")
    )

    title = "Predicted vs Actual Values Scatter Plot"
    layout = _go.Layout(
        title={"text": title},
        xaxis={"title": "Prediction", "range": x_y_line},
        yaxis={"title": "Actual", "range": x_y_line},
    )

    for color, outlier_group in df.groupby("outlier"):
        if outlier_threshold:
            name = (
                "< outlier_threshold" if color == "#0000ff" else ">= outlier_threshold"
            )
        else:
            name = "Values"
        data.append(
            _go.Scatter(
                x=outlier_group["prediction"],
                y=outlier_group["actual"],
                mode="markers",
                marker=_go.scatter.Marker(color=color),
                name=name,
            )
        )
    return _go.Figure(layout=layout, data=data)


def _tree_parse(est, feature_names):
    children_left = est.tree_.children_left
    children_right = est.tree_.children_right
    features = est.tree_.feature
    thresholds = est.tree_.threshold
    values = est.tree_.value

    def recurse(i):
        if children_left[i] == children_right[i]:
            return {"Value": values[i]}
        return OrderedDict(
            {
                "Feature": feature_names[features[i]],
                "Threshold": thresholds[i],
                "Value": values[i],
                "Left_Child": recurse(children_left[i]),
                "Right_Child": recurse(children_right[i]),
            }
        )

    return recurse(0)


def decision_tree_data_from_estimator(estimator):
    """Return data for a fitted tree in a restructured format.

    Args:
        estimator (ComponentBase): A fitted DecisionTree-based estimator.

    Returns:
        OrderedDict: An OrderedDict of OrderedDicts describing a tree structure.

    Raises:
        ValueError: If estimator is not a decision tree-based estimator.
        NotFittedError: If estimator is not yet fitted.
    """
    if not estimator.model_family == ModelFamily.DECISION_TREE:
        raise ValueError(
            "Tree structure reformatting is only supported for decision tree estimators"
        )
    if not estimator._is_fitted:
        raise NotFittedError(
            "This DecisionTree estimator is not fitted yet. Call 'fit' with appropriate arguments "
            "before using this estimator."
        )
    est = estimator._component_obj
    feature_names = estimator.input_feature_names
    return _tree_parse(est, feature_names)


def decision_tree_data_from_pipeline(pipeline_):
    """Return data for a fitted pipeline in a restructured format.

    Args:
        pipeline_ (PipelineBase): A pipeline with a DecisionTree-based estimator.

    Returns:
        OrderedDict: An OrderedDict of OrderedDicts describing a tree structure.

    Raises:
        ValueError: If estimator is not a decision tree-based estimator.
        NotFittedError: If estimator is not yet fitted.
    """
    if not pipeline_.model_family == ModelFamily.DECISION_TREE:
        raise ValueError(
            "Tree structure reformatting is only supported for decision tree estimators"
        )
    if not pipeline_._is_fitted:
        raise NotFittedError(
            "The DecisionTree estimator associated with this pipeline is not fitted yet. Call 'fit' "
            "with appropriate arguments before using this estimator."
        )
    est = pipeline_.estimator._component_obj
    feature_names = pipeline_.input_feature_names[pipeline_.estimator.name]

    return _tree_parse(est, feature_names)


def visualize_decision_tree(
    estimator, max_depth=None, rotate=False, filled=False, filepath=None
):
    """Generate an image visualizing the decision tree.

    Args:
        estimator (ComponentBase): A fitted DecisionTree-based estimator.
        max_depth (int, optional): The depth to which the tree should be displayed. If set to None (as by default), tree is fully generated.
        rotate (bool, optional): Orient tree left to right rather than top-down.
        filled (bool, optional): Paint nodes to indicate majority class for classification, extremity of values for regression, or purity of node for multi-output.
        filepath (str, optional): Path to where the graph should be saved. If set to None (as by default), the graph will not be saved.

    Returns:
        graphviz.Source: DOT object that can be directly displayed in Jupyter notebooks.

    Raises:
        ValueError: If estimator is not a decision tree-based estimator.
        NotFittedError: If estimator is not yet fitted.
    """
    if not estimator.model_family == ModelFamily.DECISION_TREE:
        raise ValueError(
            "Tree visualizations are only supported for decision tree estimators"
        )
    if max_depth and (not isinstance(max_depth, int) or not max_depth >= 0):
        raise ValueError(
            "Unknown value: '{}'. The parameter max_depth has to be a non-negative integer".format(
                max_depth
            )
        )
    if not estimator._is_fitted:
        raise NotFittedError(
            "This DecisionTree estimator is not fitted yet. Call 'fit' with appropriate arguments before using this estimator."
        )

    est = estimator._component_obj

    graphviz = import_or_raise(
        "graphviz", error_msg="Please install graphviz to visualize trees."
    )

    graph_format = None
    if filepath:
        # Cast to str in case a Path object was passed in
        filepath = str(filepath)
        try:
            f = open(filepath, "w")
            f.close()
        except (IOError, FileNotFoundError):
            raise ValueError(
                ("Specified filepath is not writeable: {}".format(filepath))
            )
        path_and_name, graph_format = os.path.splitext(filepath)
        if graph_format:
            graph_format = graph_format[1:].lower()  # ignore the dot
            supported_filetypes = graphviz.backend.FORMATS
            if graph_format not in supported_filetypes:
                raise ValueError(
                    (
                        "Unknown format '{}'. Make sure your format is one of the "
                        + "following: {}"
                    ).format(graph_format, supported_filetypes)
                )
        else:
            graph_format = "pdf"  # If the filepath has no extension default to pdf

    dot_data = export_graphviz(
        decision_tree=est,
        max_depth=max_depth,
        rotate=rotate,
        filled=filled,
        feature_names=estimator.input_feature_names,
    )
    source_obj = graphviz.Source(source=dot_data, format=graph_format)
    if filepath:
        source_obj.render(filename=path_and_name, cleanup=True)

    return source_obj


def get_prediction_vs_actual_over_time_data(pipeline, X, y, X_train, y_train, dates):
    """Get the data needed for the prediction_vs_actual_over_time plot.

    Args:
        pipeline (TimeSeriesRegressionPipeline): Fitted time series regression pipeline.
        X (pd.DataFrame): Features used to generate new predictions.
        y (pd.Series): Target values to compare predictions against.
        X_train (pd.DataFrame): Data the pipeline was trained on.
        y_train (pd.Series): Target values for training data.
        dates (pd.Series): Dates corresponding to target values and predictions.

    Returns:
        pd.DataFrame: Predictions vs. time.
    """
    dates = infer_feature_types(dates)
    prediction = pipeline.predict_in_sample(X, y, X_train=X_train, y_train=y_train)

    return pd.DataFrame(
        {
            "dates": dates.reset_index(drop=True),
            "target": y.reset_index(drop=True),
            "prediction": prediction.reset_index(drop=True),
        }
    )


def graph_prediction_vs_actual_over_time(pipeline, X, y, X_train, y_train, dates):
    """Plot the target values and predictions against time on the x-axis.

    Args:
        pipeline (TimeSeriesRegressionPipeline): Fitted time series regression pipeline.
        X (pd.DataFrame): Features used to generate new predictions.
        y (pd.Series): Target values to compare predictions against.
        X_train (pd.DataFrame): Data the pipeline was trained on.
        y_train (pd.Series): Target values for training data.
        dates (pd.Series): Dates corresponding to target values and predictions.

    Returns:
        plotly.Figure: Showing the prediction vs actual over time.

    Raises:
        ValueError: If the pipeline is not a time-series regression pipeline.
    """
    _go = import_or_raise(
        "plotly.graph_objects", error_msg="Cannot find dependency plotly.graph_objects"
    )

    if pipeline.problem_type != ProblemTypes.TIME_SERIES_REGRESSION:
        raise ValueError(
            "graph_prediction_vs_actual_over_time only supports time series regression pipelines! "
            f"Received {str(pipeline.problem_type)}."
        )

    data = get_prediction_vs_actual_over_time_data(
        pipeline, X, y, X_train, y_train, dates
    )

    data = [
        _go.Scatter(
            x=data["dates"],
            y=data["target"],
            mode="lines+markers",
            name="Target",
            line=dict(color="#1f77b4"),
        ),
        _go.Scatter(
            x=data["dates"],
            y=data["prediction"],
            mode="lines+markers",
            name="Prediction",
            line=dict(color="#d62728"),
        ),
    ]
    # Let plotly pick the best date format.
    layout = _go.Layout(
        title={"text": "Prediction vs Target over time"},
        xaxis={"title": "Time"},
        yaxis={"title": "Target Values and Predictions"},
    )

    return _go.Figure(data=data, layout=layout)


def get_linear_coefficients(estimator, features=None):
    """Returns a dataframe showing the features with the greatest predictive power for a linear model.

    Args:
        estimator (Estimator): Fitted linear model family estimator.
        features (list[str]): List of feature names associated with the underlying data.

    Returns:
        pd.DataFrame: Displaying the features by importance.

    Raises:
        ValueError: If the model is not a linear model.
        NotFittedError: If the model is not yet fitted.
    """
    if not estimator.model_family == ModelFamily.LINEAR_MODEL:
        raise ValueError(
            "Linear coefficients are only available for linear family models"
        )
    if not estimator._is_fitted:
        raise NotFittedError(
            "This linear estimator is not fitted yet. Call 'fit' with appropriate arguments "
            "before using this estimator."
        )
    coef_ = estimator.feature_importance
    coef_ = pd.Series(coef_, name="Coefficients", index=features)
    coef_ = coef_.sort_values()
    coef_ = pd.Series(estimator._component_obj.intercept_, index=["Intercept"]).append(
        coef_
    )

    return coef_


def t_sne(
    X,
    n_components=2,
    perplexity=30.0,
    learning_rate=200.0,
    metric="euclidean",
    **kwargs,
):
    """Get the transformed output after fitting X to the embedded space using t-SNE.

     Args:
        X (np.ndarray, pd.DataFrame): Data to be transformed. Must be numeric.
        n_components (int, optional): Dimension of the embedded space.
        perplexity (float, optional): Related to the number of nearest neighbors that is used in other manifold learning algorithms. Larger datasets usually require a larger perplexity. Consider selecting a value between 5 and 50.
        learning_rate (float, optional): Usually in the range [10.0, 1000.0]. If the cost function gets stuck in a bad local minimum, increasing the learning rate may help.
        metric (str, optional): The metric to use when calculating distance between instances in a feature array.
        kwargs: Arbitrary keyword arguments.

    Returns:
        np.ndarray (n_samples, n_components): TSNE output.

    Raises:
        ValueError: If specified parameters are not valid values.
    """
    if not isinstance(n_components, int) or not n_components > 0:
        raise ValueError(
            "The parameter n_components must be of type integer and greater than 0"
        )
    if not perplexity >= 0:
        raise ValueError("The parameter perplexity must be non-negative")

    X = infer_feature_types(X)
    t_sne_ = TSNE(
        n_components=n_components,
        perplexity=perplexity,
        learning_rate=learning_rate,
        metric=metric,
        **kwargs,
    )
    X_new = t_sne_.fit_transform(X)
    return X_new


def graph_t_sne(
    X,
    n_components=2,
    perplexity=30.0,
    learning_rate=200.0,
    metric="euclidean",
    marker_line_width=2,
    marker_size=7,
    **kwargs,
):
    """Plot high dimensional data into lower dimensional space using t-SNE.

    Args:
        X (np.ndarray, pd.DataFrame): Data to be transformed. Must be numeric.
        n_components (int, optional): Dimension of the embedded space.
        perplexity (float, optional): Related to the number of nearest neighbors that is used in other manifold learning algorithms. Larger datasets usually require a larger perplexity. Consider selecting a value between 5 and 50.
        learning_rate (float, optional): Usually in the range [10.0, 1000.0]. If the cost function gets stuck in a bad local minimum, increasing the learning rate may help.
        metric (str, optional): The metric to use when calculating distance between instances in a feature array.
        marker_line_width (int, optional): Determines the line width of the marker boundary.
        marker_size (int, optional): Determines the size of the marker.
        kwargs: Arbitrary keyword arguments.

    Returns:
        plotly.Figure: Figure representing the transformed data.

    Raises:
        ValueError: If marker_line_width or marker_size are not valid values.
    """
    _go = import_or_raise(
        "plotly.graph_objects", error_msg="Cannot find dependency plotly.graph_objects"
    )

    if not marker_line_width >= 0:
        raise ValueError("The parameter marker_line_width must be non-negative")
    if not marker_size >= 0:
        raise ValueError("The parameter marker_size must be non-negative")

    X_embedded = t_sne(
        X,
        n_components=n_components,
        perplexity=perplexity,
        learning_rate=learning_rate,
        metric=metric,
        **kwargs,
    )

    fig = _go.Figure()
    fig.add_trace(_go.Scatter(x=X_embedded[:, 0], y=X_embedded[:, 1], mode="markers"))
    fig.update_traces(
        mode="markers", marker_line_width=marker_line_width, marker_size=marker_size
    )
    fig.update_layout(title="t-SNE", yaxis_zeroline=False, xaxis_zeroline=False)

    return fig
