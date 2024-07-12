"""Module that stores abstract class of effects."""

from enum import Enum
from typing import Dict, List, Literal, Optional, Union

import jax.numpy as jnp
import numpyro
import pandas as pd
from skbase.base import BaseObject

from prophetverse.utils import series_to_tensor_or_array

__all__ = ["BaseEffect", "BaseAdditiveOrMultiplicativeEffect"]


EFFECT_APPLICATION_TYPE = Literal["additive", "multiplicative"]


class Stage(Enum):
    """
    Enum class for stages of the forecasting model.

    Used to indicate the stage of the model, either "train" or "predict", for the
    effect preparation steps.
    """

    TRAIN: str = "train"
    PREDICT: str = "predict"


class BaseEffect(BaseObject):
    """Base class for effects.

    Children classes should implement the following methods:

    * _initialize (optional): This method is called during `fit()` of the forecasting.
        It receives the exogenous variables dataframe, and should be used to initialize
        any necessary parameters or data structures.

    * _prepare_input_data (optional): This method is called during `fit()` and
        `predict()` of the forecasting model. It receives the exogenous variables
        dataframe, and should return a dictionary containing the data needed for the
        effect. Those data will be passed to the `apply` method as named arguments.
        By default the columns of the dataframe that match the regex pattern are
        selected, and the result is converted to a jnp.ndarray with key "data"

    * _apply: This method is called during `fit()` and `predict()` of the forecasting
        model. It receives the trend values as a jnp.ndarray, and the data needed for
        the effect as named arguments. It should return the effect values as a
        jnp.ndarray.


    Parameters
    ----------
    id : str, optional
        The id of the effect, by default "". Used to identify the effect in the model.
    regex : Optional[str], optional
        A regex pattern to match the columns of the exogenous variables dataframe,
        by default None. If None, and _tags["skip_apply_if_no_match"] is True, the
        effect will be skipped if no columns are found.
    effect_mode : EFFECT_APPLICATION_TYPE, optional
        The mode of the effect, either "additive" or "multiplicative", by default
        "multiplicative". If "multiplicative", the effect multiplies the trend values
        before returning them.
    """

    _tags = {
        "supports_multivariate": False,
        # If no columns are found, should
        # _apply be skipped?
        "skip_apply_if_no_match": True,
    }

    def __init__(
        self,
        id: str = "",
        regex: Optional[str] = None,
    ):
        self.id = id
        self.regex = regex
        self._input_feature_column_names: List[str] = []
        self._is_initialized = False

    @property
    def input_feature_column_names(self) -> List[str]:
        """Return the input feature columns names."""
        return self._input_feature_column_names

    @property
    def should_skip_apply(self) -> bool:
        """Return if the effect should be skipped by the forecaster.

        Returns
        -------
        bool
            If the effect should be skipped by the forecaster.
        """
        if not self._input_feature_column_names and self.get_tag(
            "skip_apply_if_no_match"
        ):
            return True
        return False

    def initialize(self, X: pd.DataFrame, scale: float = 1.0):
        """Initialize the effect.

        This method is called during `fit()` of the forecasting model.
        It receives the Exogenous variables DataFrame and should be used to initialize
        any necessary parameters or data structures, such as detecting the columns that
        match the regex pattern.

        This method MUST set _input_feature_columns_names to a list of column names

        Parameters
        ----------
        X : pd.DataFrame
            The DataFrame to initialize the effect.

        scale : float, optional
            The scale of the timeseries. For multivariate timeseries, this is
            a dataframe. For univariate, it is a simple float.

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If the effect does not support multivariate data and the DataFrame has more
            than one level of index.
        """
        if not self.get_tag("supports_multivariate"):
            if X.index.nlevels > 1:
                raise ValueError(
                    f"The effect of if {self.id} does not "
                    + "support multivariate data"
                )
        if self.regex is None:
            self._input_feature_column_names = []
        else:
            self._input_feature_column_names = self.match_columns(X.columns).tolist()

        self._initialize(X, scale=scale)
        self._is_initialized = True

    def _initialize(self, X: pd.DataFrame, scale: float = 1.0):
        """Customize the initialization of the effect.

        This method is called by the `initialize()` method and can be overridden by
        subclasses to provide additional initialization logic.

        Parameters
        ----------
        X : pd.DataFrame
            The DataFrame to initialize the effect.
        """
        pass

    def prepare_input_data(
        self, X: pd.DataFrame, stage: Stage = Stage.TRAIN
    ) -> Dict[str, jnp.ndarray]:
        """Prepare input data to be passed to numpyro model.

        This method is called during `fit()` and `predict()` of the forecasting model.
        It receives the Exogenous variables DataFrame and should return a dictionary
        containing the data needed for the effect. Those data will be passed to the
        `apply` method as named arguments.

        Parameters
        ----------
        X : pd.DataFrame
            The input DataFrame containing the exogenous variables for the training
            time indexes, if passed during fit, or for the forecasting time indexes, if
            passed during predict.



        Returns
        -------
        Dict[str, jnp.ndarray]
            A dictionary containing the data needed for the effect. The keys of the
            dictionary should be the names of the arguments of the `apply` method, and
            the values should be the corresponding data as jnp.ndarray.

        Raises
        ------
        ValueError
            If the effect has not been initialized.
        """
        if not self._is_initialized:
            raise ValueError("You must call initialize() before calling this method")

        # If apply should be skipped, return an empty dictionary
        if self.should_skip_apply:
            return {}

        X = X[self.input_feature_column_names]
        return self._prepare_input_data(X, stage=stage)

    def _prepare_input_data(
        self, X: pd.DataFrame, stage: Stage = Stage.TRAIN
    ) -> Dict[str, jnp.ndarray]:
        """Prepare the input data in a dict of jax arrays.

        This method is called by the `prepare_input_data()` method and can be overridden
        by subclasses to provide additional data preparation logic.

        Parameters
        ----------
        X : pd.DataFrame
            The input DataFrame containing the exogenous variables for the training
            time indexes, if passed during fit, or for the forecasting time indexes, if
            passed during predict.

        Returns
        -------
        Dict[str, jnp.ndarray]
            A dictionary containing the data needed for the effect. The keys of the
            dictionary should be the names of the arguments of the `apply` method, and
            the values should be the corresponding data as jnp.ndarray.
        """
        array = series_to_tensor_or_array(X)
        return {"data": array}

    def match_columns(self, columns: Union[pd.Index, List[str]]) -> pd.Index:
        """Match the columns of the DataFrame with the regex pattern.

        Parameters
        ----------
        columns : pd.Index
            Columns of the dataframe.

        Returns
        -------
        pd.Index
            The columns that match the regex pattern.

        Raises
        ------
        ValueError
            Indicates the abscence of required regex pattern.
        """
        if isinstance(columns, List):
            columns = pd.Index(columns)

        if self.regex is None:
            raise ValueError("To use this method, you must set the regex pattern")
        return columns[columns.str.match(self.regex)]

    def sample(self, name: str, *args, **kwargs):
        """Sample a random variable with a unique name."""
        return numpyro.sample(f"{self.id}__{name}", *args, **kwargs)

    def apply(self, trend: jnp.ndarray, **kwargs) -> jnp.ndarray:
        """Apply and return the effect values.

        Parameters
        ----------
        trend : jnp.ndarray
            An array containing the trend values.

        Returns
        -------
        jnp.ndarray
            The effect values.
        """
        x = self._apply(trend, **kwargs)

        return x

    def _apply(self, trend: jnp.ndarray, **kwargs) -> jnp.ndarray:
        """Apply the effect.

        This method is called by the `apply()` method and must be overridden by
        subclasses to provide the actual effect computation logic.

        Parameters
        ----------
        trend : jnp.ndarray
            An array containing the trend values.

        kwargs: dict
            Additional keyword arguments that may be needed to compute the effect.

        Returns
        -------
        jnp.ndarray
            The effect values.
        """
        raise NotImplementedError("Subclasses must implement _apply()")

    def __call__(self, trend: jnp.ndarray, **kwargs) -> jnp.ndarray:
        """Run the processes to calculate effect as a function."""
        return self.apply(trend, **kwargs)


class BaseAdditiveOrMultiplicativeEffect(BaseEffect):
    """
    Base class for effects that can be applied in additive or multiplicative mode.

    In additive mode, the effect is directly returned. In multiplicative mode,
    the effect is multiplied by the trend before being returned.

    Parameters
    ----------
    id : str, optional
        The id of the effect, by default "".
    regex : Optional[str], optional
        A regex pattern to match the columns of the exogenous variables dataframe,
        by default None. If None, and _tags["skip_apply_if_no_match"] is True, the
        effect will be skipped if no columns are found.
    effect_mode : EFFECT_APPLICATION_TYPE, optional. Can be "additive"
        or "multiplicative".
    """

    def __init__(self, id="", regex=None, effect_mode="multiplicative"):

        self.effect_mode = effect_mode
        super().__init__(id=id, regex=regex)

    def apply(self, trend: jnp.ndarray, **kwargs) -> jnp.ndarray:
        """Apply the effect.

        Parameters
        ----------
        trend : jnp.ndarray
            The trend of the model.

        Returns
        -------
        jnp.ndarray
            The computed effect.
        """
        x = super().apply(trend, **kwargs)
        if self.effect_mode == "additive":
            return x
        return trend * x
