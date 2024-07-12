"""Definition of Log Effect class."""

from typing import Optional

import jax.numpy as jnp
from numpyro import distributions as dist
from numpyro.distributions import Distribution

from prophetverse.effects.base import (
    EFFECT_APPLICATION_TYPE,
    BaseAdditiveOrMultiplicativeEffect,
)

__all__ = ["LogEffect"]


class LogEffect(BaseAdditiveOrMultiplicativeEffect):
    """Represents a log effect as effect = scale * log(rate * data + 1).

    Parameters
    ----------
    scale_prior : Optional[Distribution], optional
        The prior distribution for the scale parameter., by default Gamma
    rate_prior : Optional[Distribution], optional
        The prior distribution for the rate parameter., by default Gamma
    effect_mode : effects_application, optional
        Either "additive" or "multiplicative", by default "multiplicative"
    """

    def __init__(
        self,
        id: str = "",
        regex: Optional[str] = None,
        effect_mode: EFFECT_APPLICATION_TYPE = "multiplicative",
        scale_prior: Optional[Distribution] = None,
        rate_prior: Optional[Distribution] = None,
        **kwargs,
    ):
        self.scale_prior = scale_prior or dist.Gamma(1, 1)
        self.rate_prior = rate_prior or dist.Gamma(1, 1)
        super().__init__(id=id, regex=regex, effect_mode=effect_mode, **kwargs)

    def _apply(  # type: ignore[override]
        self, trend: jnp.ndarray, **kwargs
    ) -> jnp.ndarray:
        """Compute the effect using the log transformation.

        Parameters
        ----------
        trend : jnp.ndarray
            The trend component.
        data : jnp.ndarray
            The input data.

        Returns
        -------
        jnp.ndarray
            The computed effect based on the given trend and data.
        """
        data: jnp.ndarray = kwargs.pop("data")

        scale = self.sample("log_scale", self.scale_prior)
        rate = self.sample("log_rate", self.rate_prior)
        effect = scale * jnp.log(jnp.clip(rate * data + 1, 1e-8, None))

        return effect
