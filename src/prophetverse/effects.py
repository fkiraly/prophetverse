#  pylint: disable=g-import-not-at-top
from typing import Protocol, TypedDict, Dict, Tuple, Callable, List
import jax.numpy as jnp
import numpyro
from numpyro import distributions as dist
import re
import logging
import pandas as pd
from abc import ABC, abstractmethod


# --------------
#     Effects
# --------------

class AbstractEffect(ABC):
    """Abstract class for effects.
    
    Effects should inherit from this class and implement the `compute_effect` method.
    The id is used to create unique names for the samples in the model.
    
    """

    def __init__(self, id="", regex=None, **kwargs):
        self.id = id
        self.regex = regex
        
        
    def match_columns(self, columns : pd.Index) -> pd.Index:
        """Match the columns of the DataFrame with the regex pattern.
        
        Args:
            X (pd.DataFrame): The DataFrame to match.
        
        Returns:
            pd.Index: The columns that match the regex pattern.
        """
        
        if isinstance(columns, List):
            columns = pd.Index(columns)
            
        if self.regex is None:
            raise ValueError("To use this method, you must set the regex pattern")
        return columns[columns.str.match(self.regex)]
    
    @staticmethod
    def split_data_into_effects(X : pd.DataFrame, effects : List) -> Dict[str, pd.DataFrame]:
        """Split the data into effects.
        
        Args:
            X (pd.DataFrame): The DataFrame to split.
            effects (List[AbstractEffect]): The effects to split the data into.
        
        Returns:
            Dict[str, pd.DataFrame]: A dictionary mapping effect names to DataFrames.
        """
        data = {}
        for effect in effects:
            data[effect.id] = X[effect.match_columns(X)]
        return data

    def sample(self, name : str, *args, **kwargs):
        """
        Sample a random variable with a unique name.
        """
        return numpyro.sample(f"{self.id}__{name}", *args, **kwargs)

    @abstractmethod
    def compute_effect(self, trend : jnp.ndarray, data : jnp.ndarray) -> jnp.ndarray: 
        """Compute the effect based on the trend and data.
        
        Args:
            trend (jnp.ndarray): The trend.
            data (jnp.ndarray): The data concerning this effect.
        
        Returns:
            jnp.ndarray: The effect.
        """
        ...

    def __call__(self, trend, data):

        return self.compute_effect(trend, data)


class LogEffect(AbstractEffect):
    """
    Log effect for a variable.

    Computes the effect using the formula:

    effect = scale * log(rate * data + 1)

    A gamma prior is used for the scale and rate parameters.

    Args:
        id (str): The identifier for the effect.
        scale_prior (dist.Distribution): The prior distribution for the scale parameter.
        rate_prior (dist.Distribution): The prior distribution for the rate parameter.
    """

    def __init__(
        self,
        scale_prior=dist.Gamma(1, 1),
        rate_prior=dist.Gamma(1, 1),
        effect_mode="multiplicative",
        **kwargs,
    ):
        self.scale_prior = scale_prior
        self.rate_prior = rate_prior
        self.effect_mode = effect_mode
        super().__init__(**kwargs)

    def compute_effect(self, trend, data):
        """
        Computes the effect using the log transformation.

        Args:
            trend: The trend component.
            data: The input data.

        Returns:
            The computed effect.
        """
        scale = self.sample("log_scale", self.scale_prior)
        rate = self.sample("log_rate", self.rate_prior)
        effect = scale * jnp.log(rate * data + 1)
        if self.effect_mode == "additive":
            return effect
        return trend * effect


class LinearEffect(AbstractEffect):
    """
    Represents a linear effect in a hierarchical prophet model.

    Args:
        id (str): The identifier for the effect.
        prior (tuple): A tuple with the distribution class to use for sampling coefficients and  the arguments to pass to the distribution class. Defaults to (dist.Normal, 0, 1).
        effect_mode (str): The mode of the effect, either "multiplicative" or "additive".

    Attributes:
        dist (type): The distribution class used for sampling coefficients.
        dist_args (tuple): The arguments passed to the distribution class.
        effect_mode (str): The mode of the effect, either "multiplicative" or "additive".

    Methods:
        compute_effect(trend, data): Computes the effect based on the given trend and data.

    """

    def __init__(
        self,
        prior=(dist.Normal, 0, 1),
        effect_mode="multiplicative",
        **kwargs):
        self.prior = prior
        self.effect_mode = effect_mode
        super().__init__(**kwargs)

    def compute_effect(self, trend, data):
        """
        Computes the effect based on the given trend and data.

        Args:
            trend: The trend component of the hierarchical prophet model.
            data: The data used to compute the effect.

        Returns:
            The computed effect based on the given trend and data.

        """
        n_features = data.shape[-1]

        dist = self.prior[0]
        dist_args = self.prior[1:]
        coefficients = self.sample(
            "coefs",
            dist(*[jnp.array([arg] * n_features) for arg in dist_args]),
        )

        if coefficients.ndim == 1:
            coefficients = jnp.expand_dims(coefficients, axis=-1)

        if data.ndim == 3 and coefficients.ndim == 2:
            coefficients = jnp.expand_dims(coefficients, axis=0)
        if self.effect_mode == "multiplicative":
            return multiplicative_effect(trend, data, coefficients)
        return additive_effect(trend, data, coefficients)

class LinearHeterogenousPriorsEffect(AbstractEffect):
    """
    Represents a linear effect with heterogenous priors.

    This effect applies a linear transformation to the input data using coefficients sampled from
    heterogenous priors. The effect can be either multiplicative or additive.

    Args:
        exogenous_priors (Dict[str, Tuple[dist.Distribution, ...]]: A dictionary
            mapping regular expressions to tuples of distribution names and their corresponding
            parameters. These priors are used to sample coefficients for each matching column in
            the input data.
        feature_names (pd.Index): The index of feature names in the input data.
        default_exogenous_prior (Tuple[dist.Distribution, ...], optional): The default prior to use
            for columns that do not match any regular expressions. Defaults to (dist.Normal, 0, 1).
        effect_mode (str, optional): The effect mode, either "multiplicative" or "additive".
            Defaults to "multiplicative".
        id (str, optional): The identifier for the effect. Defaults to "".

    Attributes:
        exogenous_priors (Dict[str, Tuple[dist.Distribution, ...]]): A dictionary
            mapping regular expressions to tuples of distribution names and their corresponding
            parameters.
        feature_names (pd.Index): The index of feature names in the input data.
        default_exogenous_prior (Tuple[dist.Distribution, ...]): The default prior to use for
            columns that do not match any regular expressions.
        effect_mode (str): The effect mode, either "multiplicative" or "additive".
        exogenous_permutation_matrix (ndarray): The permutation matrix used to map coefficients to
            their corresponding columns in the input data.
        exogenous_dists (List[Tuple[str, dist.Distribution]]): A list of tuples containing the name
            of the coefficient and the corresponding distribution.

    """

    def __init__(self,
                 exogenous_priors: Dict[str, Tuple[dist.Distribution, ...]],
                 feature_names: pd.Index,
                 default_exogenous_prior=(dist.Normal, 0, 1),
                 effect_mode="multiplicative",
                 **kwargs):
        self.exogenous_priors = exogenous_priors
        self.feature_names = pd.Index(feature_names)
        self.default_exogenous_prior = default_exogenous_prior
        self.effect_mode = effect_mode
        super().__init__(**kwargs)

        self.set_distributions_and_permutation_matrix()

    def compute_effect(self, trend, data):
        """
        Compute the effect on the trend using the sampled coefficients.

        Args:
            trend: The trend data.
            data: The input data.

        Returns:
            The computed effect.

        """
        coefficients = self.get_coefficients()
        if self.effect_mode == "multiplicative":
            return multiplicative_effect(trend, data, coefficients)
        return additive_effect(trend, data, coefficients)

    @property
    def features_with_default_priors(self):
        """
        Check the regular expressions in the exogenous priors and return the remaining regex.

        This function takes the exogenous priors and the input DataFrame `X`.
        It checks if any columns are already set based on the regular expressions in the exogenous priors.
        It returns the remaining regex that matches the columns that are not already set.

        Returns:
            str: The remaining regex that matches the columns that are not already set.

        Raises:
            ValueError: If any columns are already set.

        """
        already_set_columns = set()
        for regex, _ in self.exogenous_priors.items():
            columns = [column for column in self.feature_names if re.match(regex, column)]
            if already_set_columns.intersection(columns):
                raise ValueError(
                    "Columns {} are already set".format(
                        already_set_columns.intersection(columns)
                    )
                )
            already_set_columns = already_set_columns.union(columns)
        remaining_columns = self.feature_names.difference(already_set_columns)

        # Create a regex that matches all remaining columns
        remaining_regex = "|".join(remaining_columns)
        return remaining_regex

    def set_distributions_and_permutation_matrix(self):
        """
        Set the distributions and permutation matrix based on the exogenous priors and feature names.

        """
        if self.feature_names is None or len(self.feature_names) == 0:
            return [], jnp.array([])

        exogenous_dists = []
        exogenous_permutation_matrix = []
        exogenous_priors = self.exogenous_priors.copy()

        if self.features_with_default_priors:
            exogenous_priors[self.features_with_default_priors] = self.default_exogenous_prior

        for i, (regex, (Distribution, *args)) in enumerate(exogenous_priors.items()):
            # Find columns that match the regex
            columns = [column for column in self.feature_names if re.match(regex, column)]
            # Get idx of columns that match the regex
            idx = jnp.array([self.feature_names.get_loc(column) for column in columns])
            # Set the distribution for each column that matches the regex
            distribution: dist.Distribution = Distribution(
                    *[jnp.ones(len(idx)) * arg for arg in args]
                )

            name = "exogenous_coefficients_{}".format(i)

            if not len(idx):
                logging.warning(
                        "No columns in the DataFrame match the regex pattern: {}".format(regex)
                    )
                continue
            # Matrix of shape (len(columns), len(idx) that map len(idx) to the corresponding indexes
            exogenous_permutation_matrix.append(jnp.eye(len(self.feature_names))[idx].T)
            exogenous_dists.append((name, distribution))

        self.exogenous_permutation_matrix = jnp.concatenate(exogenous_permutation_matrix, axis=1)
        self.exogenous_dists = exogenous_dists

    def get_coefficients(self):
        """
        Get the sampled coefficients based on the exogenous distributions.

        Returns:
            The sampled coefficients.

        """
        parameters = []
        for regex, distribution in self.exogenous_dists:
            parameters.append(
                self.sample(
                    "exogenous_coefficients_{}".format(regex), distribution
                ).reshape((-1, 1))
            )

        return self.exogenous_permutation_matrix @ jnp.concatenate(parameters, axis=0)


class HillEffect(AbstractEffect):
    """
    Represents a Hill effect in a time series model.

    Attributes:
        half_max_prior: Prior distribution for the half-maximum parameter.
        slope_prior: Prior distribution for the slope parameter.
        max_effect_prior: Prior distribution for the maximum effect parameter.
        effect_mode: Mode of the effect (either "additive" or "multiplicative").
    """

    def __init__(
        self,
        half_max_prior=dist.Gamma(1, 1),
        slope_prior=dist.HalfNormal(10),
        max_effect_prior=dist.Gamma(1, 1),
        effect_mode="multiplicative",
        **kwargs,
    ):
        self.half_max_prior = half_max_prior
        self.slope_prior = slope_prior
        self.max_effect_prior = max_effect_prior
        self.effect_mode = effect_mode
        super().__init__(**kwargs)

    def compute_effect(self, trend, data):
        """
        Computes the effect using the log transformation.

        Args:
            trend: The trend component.
            data: The input data.

        Returns:
            The computed effect.
        """

        half_max = self.sample("half_max", self.half_max_prior)
        slope = self.sample("slope", self.slope_prior)
        max_effect = self.sample("max_effect", self.max_effect_prior)

        effect = max_effect * (1 / (1 + (data / half_max) ** -slope))

        if self.effect_mode == "additive":
            return effect
        return trend * effect


def matrix_multiplication(data, coefficients):
    return data @ coefficients.reshape((-1, 1))


def additive_effect(
    trend: jnp.ndarray, data: jnp.ndarray, coefficients: jnp.ndarray
) -> jnp.ndarray:
    return matrix_multiplication(data, coefficients)


def multiplicative_effect(
    trend: jnp.ndarray, data: jnp.ndarray, coefficients: jnp.ndarray
) -> jnp.ndarray:
    return trend * matrix_multiplication(data, coefficients)
