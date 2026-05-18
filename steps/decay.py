## Modified By: Callam
## Project: Lotto Generator
## Purpose of File: To Calculate Decay-Weighted Lottery Number Frequencies
## Description:
## This file applies a decay factor to historical lottery draw data, assigning more weight to recent draws
## and less weight to older ones. Decay is calculated draw-based rather than by calendar time — each draw's
## weight depends on how many draws ago it occurred. The normalized decay-weighted frequency distributions
## are stored in the data pipeline for downstream use in prediction models.

import numpy as np
import logging

from config import DECAY_PER_DRAW

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
NUM_MAIN = 40
NUM_POWERBALL = 10
TOTAL_NUMBERS = NUM_MAIN + NUM_POWERBALL  # 50


def calculate_decay_factors(pipeline, decay_rate: float = DECAY_PER_DRAW):
    """
    Calculates decay-weighted frequency distributions for main numbers (1-40)
    and Powerball numbers (1-10), normalizes separately, and concatenates into
    a single shape-(50,) array stored in the pipeline as 'decay_factors'.

    Draws are weighted by their position in the list: the most recent draw
    (last index) receives the highest weight, each prior draw gets exponentially
    less. The per-draw decay rate is DECAY_PER_DRAW from config, which is derived
    from a weekly half-life and accounts for DRAWS_PER_WEEK.
    """
    historical_data = pipeline.get_data("historical_data")
    if not historical_data:
        logging.warning("No historical data available for decay calculations.")
        pipeline.add_data("decay_factors", np.ones(TOTAL_NUMBERS) / TOTAL_NUMBERS)
        return

    total_draws = len(historical_data)

    main_frequency = np.zeros(NUM_MAIN, dtype=float)
    powerball_frequency = np.zeros(NUM_POWERBALL, dtype=float)

    # ---- Accumulate decay-weighted counts, most-recent-last order ----
    for i, draw in enumerate(historical_data):
        age = total_draws - i  # 1 for most recent, total_draws for oldest
        weight = decay_rate ** age

        # Main numbers
        for num in draw.get("numbers", []) or []:
            if isinstance(num, int) and 1 <= num <= NUM_MAIN:
                main_frequency[num - 1] += weight
            else:
                logging.warning(
                    f"Invalid main number {num!r} in draw at index {i}; ignored."
                )

        # Powerball(s)
        pb = draw.get("powerball")
        if pb is None:
            continue

        if isinstance(pb, list):
            pb_iter = pb
        else:
            pb_iter = [pb]

        for p in pb_iter:
            if isinstance(p, int) and 1 <= p <= NUM_POWERBALL:
                powerball_frequency[p - 1] += weight
            else:
                logging.warning(
                    f"Invalid Powerball value {p!r} in draw at index {i}; ignored."
                )

    # ---- Normalise separately and concatenate ----
    main_sum = main_frequency.sum()
    if main_sum > 0.0:
        main_frequency /= main_sum
    else:
        logging.warning(
            "Main frequency sum is zero after decay; assigning uniform main distribution."
        )
        main_frequency = np.ones(NUM_MAIN, dtype=float) / NUM_MAIN

    pb_sum = powerball_frequency.sum()
    if pb_sum > 0.0:
        powerball_frequency /= pb_sum
    else:
        logging.warning(
            "Powerball frequency sum is zero after decay; assigning uniform PB distribution."
        )
        powerball_frequency = np.ones(NUM_POWERBALL, dtype=float) / NUM_POWERBALL

    combined_frequency = np.concatenate([main_frequency, powerball_frequency])
    pipeline.add_data("decay_factors", combined_frequency)
    logging.info("Decay-weighted frequency calculation completed.")
