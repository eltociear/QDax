"""Tests MAP Elites implementation"""

import functools
from typing import Dict

import jax
import jax.numpy as jnp
import pytest

from qdax import environments
from qdax.core.containers.mapelites_repertoire import (
    MapElitesRepertoire,
    compute_cvt_centroids,
)
from qdax.core.emitters.mutation_operators import isoline_variation
from qdax.core.emitters.standard_emitters import MixingEmitter
from qdax.core.map_elites import MAPElites
from qdax.core.neuroevolution.mdp_utils import init_population_controllers
from qdax.tasks.brax_envs import create_default_brax_task_components


@pytest.mark.parametrize(
    "env_name, batch_size, is_task_reset_based",
    [
        ("walker2d_uni", 1, False),
        ("walker2d_uni", 1, True),
    ],
)
def test_map_elites(env_name: str, batch_size: int, is_task_reset_based: bool) -> None:
    batch_size = batch_size
    env_name = env_name
    episode_length = 100
    num_iterations = 5
    seed = 42
    num_init_cvt_samples = 1000
    num_centroids = 50
    min_bd = 0.0
    max_bd = 1.0

    # Init a random key
    random_key = jax.random.PRNGKey(seed)

    env, policy_network, scoring_fn = create_default_brax_task_components(
        env_name=env_name,
        batch_size=batch_size,
        random_key=random_key,
    )

    # Define emitter
    variation_fn = functools.partial(isoline_variation, iso_sigma=0.05, line_sigma=0.1)
    mixing_emitter = MixingEmitter(
        mutation_fn=lambda x, y: (x, y),
        variation_fn=variation_fn,
        variation_percentage=1.0,
        batch_size=batch_size,
    )

    # Get minimum reward value to make sure qd_score are positive
    reward_offset_for_qd_score_metric = environments.reward_offset[env_name]

    # Define a metrics function
    def metrics_fn(repertoire: MapElitesRepertoire) -> Dict:
        # Get metrics
        grid_empty = repertoire.fitnesses == -jnp.inf
        qd_score = jnp.sum(repertoire.fitnesses, where=~grid_empty)
        # Add offset for positive qd_score
        qd_score += (
            reward_offset_for_qd_score_metric
            * episode_length
            * jnp.sum(1.0 - grid_empty)
        )
        coverage = 100 * jnp.mean(1.0 - grid_empty)
        max_fitness = jnp.max(repertoire.fitnesses)

        return {"qd_score": qd_score, "max_fitness": max_fitness, "coverage": coverage}

    # Instantiate MAP-Elites
    map_elites = MAPElites(
        scoring_function=scoring_fn,
        emitter=mixing_emitter,
        metrics_function=metrics_fn,
    )

    # Compute the centroids
    centroids, random_key = compute_cvt_centroids(
        num_descriptors=env.behavior_descriptor_length,
        num_init_cvt_samples=num_init_cvt_samples,
        num_centroids=num_centroids,
        minval=min_bd,
        maxval=max_bd,
        random_key=random_key,
    )

    # Init population of controllers
    init_variables = init_population_controllers(
        policy_network, env, batch_size, random_key
    )

    # Compute initial repertoire
    repertoire, emitter_state, random_key = map_elites.init(
        init_variables, centroids, random_key
    )

    # Run the algorithm
    (repertoire, emitter_state, random_key,), metrics = jax.lax.scan(
        map_elites.scan_update,
        (repertoire, emitter_state, random_key),
        (),
        length=num_iterations,
    )

    pytest.assume(repertoire is not None)


if __name__ == "__main__":
    test_map_elites(env_name="pointmaze", batch_size=10)