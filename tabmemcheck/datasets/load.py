####################################################################################
# Load datasets in 4 different transformed versions:
# - original
# - perturbed
# - task
# - statistical
# The transformations are specified in a YAML configuration file (e.g. iris.yaml).
####################################################################################

import numpy as np
import pandas as pd

import importlib.resources as resources
import yaml
import copy

import tabmemcheck.utils as utils

from .transform import *

DATASET_PLAIN = "plain"
DATASET_ORIGINAL = "original"
DATASET_PERTURBED = "perturbed"
DATASET_TASK = "task"
DATASET_STATISTICAL = "statistical"

DATASET_TRANSFORM = [
    DATASET_PLAIN,
    DATASET_ORIGINAL,
    DATASET_PERTURBED,
    DATASET_TASK,
    DATASET_STATISTICAL,
]


def __validate_inputs(transform):
    assert transform in DATASET_TRANSFORM, (
        "dataset version must be one of "
        + ", ".join(DATASET_TRANSFORM)
        + f"got {transform}"
    )


####################################################################################
# Perturbations and transformations as specified in a YAML configuration file
####################################################################################


CONFIG_DTYPE = "dtype"
CONFIG_TARGET = "target"
CONFIG_PERTURBATIONS = "perturbations"
CONFIG_TRANSFORM = "transform"
CONFIG_TASK_ONLY_TRANSFORM = "task_only_transform"
CONFIG_RENAME = "rename"
CONFIG_RECODE = "recode"

METHODS_REGISTER = {
    # generic methods
    "integer": integer_perturbation,
    "swap": swap_perturbation,
    "add_normal_noise_and_round": add_normal_noise_and_round_array,
    "astype": lambda x, dtype, seed: x.astype(dtype),
    "scale": lambda x, factor, seed: x * factor,
    "fillna": lambda x, value, seed: pd.DataFrame(x).fillna(value).values.flatten(),
    # "float": float_perturbation,
    # "value": value_perturbation,
    # special-purpose perturbations
    "titanic_ticket_perturbation": titanic_ticket_perturbation,
    "titanic_name_transform": titanic_name_transform,
}

# "to_numeric": pd.to_numeric,
# "to_int": lambda x: x.apply(
#        lambda x: np.NaN if pd.isna(x) or np.isinf(x) else int(x)
# ),
# "round": lambda x, decimals: x.round(decimals=decimals),
#
# "append": lambda x, value: x.astype(str) + value,


def __load_yaml_config(dataset_name: str):  # TODO also load other config files
    """Load from the resources folder of the package"""
    with resources.open_text(
        "tabmemcheck.resources.config", f"{dataset_name}.yaml"
    ) as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    return config


def apply_transform(
    df: pd.DataFrame, schedule: list, methods_register: dict, seed=None
):
    """Apply the transformations in schedule to the features in a dataframe.

    Valid transformations are specified in the methods_register.
    """
    df = df.copy(deep=True)  # create a deep copy of the data frame
    for transform in schedule:
        # feature name
        feature_names = transform[
            "name"
        ]  # can be a single feature or a list of features
        if not isinstance(feature_names, list):
            feature_names = [feature_names]
        for feature_name in feature_names:
            if not feature_name in df.columns:
                print(
                    f"Warning: Feature {feature_name} could not be found to the dataset."
                )
                continue
            # name of the method
            method = transform["type"]
            if not method in methods_register.keys():
                print(f"Warning: Unknown method type {method}.")
                continue
            pert_fn = methods_register[method]
            # the remaining entries in the dictionary are key-word arguments for the method function
            parameters = copy.deepcopy(transform)
            del parameters["name"]
            del parameters["type"]
            parameters["seed"] = seed  # add the seed
            df[feature_name] = pert_fn(df[feature_name].values, **parameters)
    return df


def rename_and_recode(df: pd.DataFrame, rename: dict, recode: dict):
    """Re-name featues and re-code their values according to the provided dictionaries."""
    # first recode
    for feature_name, recode_dict in recode.items():
        # feature name
        if not feature_name in df.columns:
            print(f"Warning: Feature {feature_name} could not be found to the dataset.")
            continue
        df[feature_name] = df[feature_name].replace(recode_dict)
    # then rename
    df = df.rename(columns=rename)
    return df


def check_perturbed_rows(df_original, df_perturbed):
    df_common = pd.merge(df_original, df_perturbed, how="inner")
    if df_common.empty:
        print("None of the perturbed rows appear in the original dataset.")
    else:
        per_cent = 100.0 * df_common.shape[0] / df_perturbed.shape[0]
        print(
            f"{df_common.shape[0]} perturbed row(s) appear in the original dataset (that is {per_cent:.2f}% of all perturbed rows)."
        )


####################################################################################
# Generic dataset loading function, with YAML configuration file
####################################################################################


def load_dataset(
    csv_file: str,
    dataset_name: str,
    transform=DATASET_ORIGINAL,
    permute_columns=True,  # for perturbed transform
    seed=None,
):
    """Generic dataset loading function. Dataset tranformations are specified in a yaml configuration file."""
    __validate_inputs(transform)
    rng = np.random.default_rng(seed=seed)
    config = __load_yaml_config(dataset_name)

    # plain (i.e. no transformation)
    if transform == DATASET_PLAIN:
        return utils.load_csv_df(csv_file)

    # original
    df_original = utils.load_csv_df(csv_file, dtype=config.get(CONFIG_DTYPE, None))
    df_original = utils.strip_strings_in_dataframe(df_original)

    if not CONFIG_TARGET in config.keys():  # assume that the target is the last column
        config[CONFIG_TARGET] = df_original.columns[-1]

    # move the target to the last column
    df_original = move_column_to_position(
        df_original, config[CONFIG_TARGET], len(df_original.columns) - 1
    )

    if transform == DATASET_ORIGINAL:
        return df_original

    # perturbed
    df_perturbed = apply_transform(
        df_original, config[CONFIG_PERTURBATIONS], METHODS_REGISTER, seed=rng
    )
    if permute_columns:  # permute columns, but keep the target in the last column
        df_perturbed = permute_all_columns(df_perturbed, seed=rng)
        df_perturbed = move_column_to_position(
            df_perturbed, config[CONFIG_TARGET], len(df_original.columns) - 1
        )

    if transform == DATASET_PERTURBED:
        check_perturbed_rows(df_original, df_perturbed)
        return df_perturbed

    # task
    df_task = apply_transform(
        df_perturbed, config.get(CONFIG_TRANSFORM, {}), METHODS_REGISTER, seed=rng
    )
    if (
        transform == DATASET_TASK
    ):  # apply formatting that would cause problems for the statistical transform
        df_task = apply_transform(
            df_task,
            config.get(CONFIG_TASK_ONLY_TRANSFORM, {}),
            METHODS_REGISTER,
            seed=rng,
        )
    df_task = rename_and_recode(
        df_task, config.get(CONFIG_RENAME, {}), config.get(CONFIG_RECODE, {})
    )
    if transform == DATASET_TASK:
        return df_task

    # statistical
    categorical_features = df_task.select_dtypes(
        include="object"
    ).columns  # categorical features are those with dtype object

    # convert categorical features to integers
    for feature in categorical_features:
        df_task[feature] = to_categorical(
            df_task[feature].values, random=True, seed=rng
        )

    # to all columns that are not categorical, apply the statistical transform
    for feature in df_task.columns:
        if feature not in categorical_features:
            df_task[feature] = statistical_transform(
                df_task[feature].values.reshape(-1, 1), seed=rng
            )

    # rename columns to X1, X2, X3, ...
    df_statistical = df_task.rename(
        columns={feature: f"X{idx+1}" for idx, feature in enumerate(df_task.columns)}
    )
    # the last column is the target, rename it to Y
    df_statistical = df_statistical.rename(columns={df_statistical.columns[-1]: "Y"})

    return df_statistical


####################################################################################
# Loading functions for specific datasets
####################################################################################


def load_iris(csv_file: str = "iris.csv", *args, **kwargs):
    """The Iris dataset. https://archive.ics.uci.edu/ml/datasets/iris"""
    return load_dataset(csv_file, "iris", *args, **kwargs)


def load_adult(csv_file: str = "adult-train.csv", *args, **kwargs):
    """The Adult Income dataset. http://www.cs.toronto.edu/~delve/data/adult/adultDetail.html"""
    return load_dataset(csv_file, "adult", *args, **kwargs)


def load_housing(csv_file: str, *args, **kwargs):
    """California Housing dataset."""
    return load_dataset(csv_file, "housing", *args, **kwargs)


def load_openml_diabetes(csv_file: str = "openml-diabetes.csv", *args, **kwargs):
    """The OpenML Diabetes dataset. https://www.openml.org/d/37"""
    return load_dataset("openml-diabetes.csv", "openml-diabetes", *args, **kwargs)
