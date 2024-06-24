#  pylint: disable=g-import-not-at-top
import jax.numpy as jnp
import numpyro
from numpyro import distributions as dist
from prophetverse.effects.base import AbstractEffect
from prophetverse.utils.algebric_operations import _exponent_safe
from prophetverse.effects.effect_apply import additive_effect, multiplicative_effect


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
        scale_prior=None,
        rate_prior=None,
        effect_mode="multiplicative",
        **kwargs,
    ):
        if scale_prior is None:
            scale_prior = dist.Gamma(1, 1)
        if rate_prior is None:
            rate_prior = dist.Gamma(1, 1)
            
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
        prior (dist.Distribution): A numpyro distribution to use as prior. Defaults to dist.Normal(0, 1)
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
        prior=None,
        effect_mode="multiplicative",
        **kwargs):
        self.prior = prior or dist.Normal(0, 0.1)
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

        with numpyro.plate(f"{self.id}_plate", n_features, dim=-1):
            coefficients = self.sample(
                "coefs",
                self.prior
            )

        if coefficients.ndim == 1:
            coefficients = jnp.expand_dims(coefficients, axis=-1)

        if data.ndim == 3 and coefficients.ndim == 2:
            coefficients = jnp.expand_dims(coefficients, axis=0)
        if self.effect_mode == "multiplicative":
            return multiplicative_effect(trend, data, coefficients)
        return additive_effect(trend, data, coefficients)

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
        half_max_prior=None,
        slope_prior=None,
        max_effect_prior=None,
        effect_mode="multiplicative",
        **kwargs,
    ):
        
        if half_max_prior is None:
            half_max_prior = dist.Gamma(1, 1)
        if slope_prior is None:
            slope_prior = dist.HalfNormal(10)
        if max_effect_prior is None:
            max_effect_prior = dist.Gamma(1, 1)
            
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

        x = _exponent_safe(data / half_max, -slope)
        effect = max_effect / (1 + x)

        if self.effect_mode == "additive":
            return effect
        return trend * effect