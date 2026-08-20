"""
deep_predictor.py
=================
Production LSTM for lottery time-series prediction (NZ Lotto, 6/40 + bonus).

The draw history is treated as a time-series classification problem: the
last 10 draws (each encoded as 12 features) form one input sequence of
shape (batch, 10, 12), and the model outputs a probability distribution
over the 40 main numbers for the next draw.

Features per timestep (12)
--------------------------
- 6 main numbers, normalised by pool size (n / 40)
- 1 bonus number, normalised by pool size (0.0 when no bonus is recorded)
- draw_sum / max_possible_sum      (max sum = 35+36+37+38+39+40 = 225)
- odd_count / 6
- even_count / 6
- max_gap / 40                     (largest gap between consecutive numbers)
- block_entropy                    (Shannon entropy across 5 blocks of 8
                                    numbers, normalised by log2(5) -> [0, 1])

Architecture
------------
    Input(10, 12)
      -> Masking(mask_value=0.0)            # ignores padded timesteps
      -> LSTM(128, return_sequences=True, dropout=0.2, recurrent_dropout=0.2)
      -> LSTM(64,  dropout=0.2, recurrent_dropout=0.2)
      -> Dense(128, relu) -> Dropout(0.3)
      -> Dense(40, softmax)

Loss is weighted categorical cross-entropy with per-class weights
``1 / sqrt(frequency)`` computed over the FULL draw history, so rarely
drawn numbers contribute more to the loss. Optimizer is AdamW
(lr=1e-3, weight_decay=1e-4). Training uses an 80/20 temporal split
(never shuffled), Gaussian-noise augmentation (sigma=0.01) on the
training features, and EarlyStopping / ReduceLROnPlateau /
ModelCheckpoint / TensorBoard callbacks. The best model is checkpointed
to ``data/models/lstm_best.keras`` and metrics are logged to
``data/logs/lstm`` (TensorBoard event files plus a ``history.json``
fallback the dashboard can read without TensorBoard installed).

Dependencies
------------
- numpy                    (required)
- tensorflow >= 2.16       (optional — enables the real LSTM)

If TensorFlow is NOT installed, ``create_predictor()`` returns
:class:`StubDeepPredictor`, which logs a warning and returns uniform
probabilities (1/40 per number). Install the real dependency with::

    pip install tensorflow

Usage
-----
    from deep_predictor import create_predictor, build_training_data

    predictor = create_predictor()
    predictor.train(draws)                       # draws: [[n1..n6, bonus?], ...]
    result = predictor.predict_next_draw(draws[-10:])
    # {"top_20": [(num, prob), ...], "top_6": [...], "entropy": float,
    #  "model_version": str, "generated_at": iso_timestamp}
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np

logger = logging.getLogger(__name__)

MODEL_VERSION = "lstm-2.0.0"

# ---------------------------------------------------------------------------
# Optional TensorFlow dependency
# ---------------------------------------------------------------------------
try:
    import tensorflow as tf
    from tensorflow import keras

    HAS_TF = True
except ImportError:
    tf = None
    keras = None
    HAS_TF = False
    logger.warning(
        "TensorFlow not installed — deep_predictor will use StubDeepPredictor "
        "(uniform probabilities). Install with: pip install tensorflow"
    )

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
WINDOW = 10  # timesteps: last N draws form one input sequence
NUM_MAIN = 6  # main numbers per draw
POOL_SIZE = 40  # NZ Lotto main pool (1..40)
NUM_BLOCKS = 5  # entropy blocks (8 numbers each)
BLOCK_SIZE = POOL_SIZE // NUM_BLOCKS
MAX_POSSIBLE_SUM = float(sum(range(POOL_SIZE - NUM_MAIN + 1, POOL_SIZE + 1)))  # 225
NUM_FEATURES = 12

FEATURE_NAMES = [
    "n1",
    "n2",
    "n3",
    "n4",
    "n5",
    "n6",
    "bonus",
    "draw_sum",
    "odd_count",
    "even_count",
    "max_gap",
    "block_entropy",
]

EPOCHS = 100
BATCH_SIZE = 32
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
NOISE_SIGMA = 0.01  # Gaussian augmentation noise on training features
TRAIN_FRACTION = 0.8  # temporal split — never shuffle time series
EARLY_STOP_PATIENCE = 10
LR_PATIENCE = 5
LR_FACTOR = 0.5

DEFAULT_MODEL_PATH = Path("data/models/lstm_best.keras")
TENSORBOARD_LOG_DIR = Path("data/logs/lstm")
HISTORY_PATH = Path("data/logs/lstm/history.json")


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------
def engineer_features(draw: Sequence[int]) -> np.ndarray:
    """Encode one draw as the 12-feature timestep vector.

    Args:
        draw: At least 6 integers (the main numbers). An optional 7th
            element is treated as the bonus number (0.0 when absent).

    Returns:
        np.ndarray of shape (12,), float32, all values in [0, 1].
    """
    if len(draw) < NUM_MAIN:
        raise ValueError(
            f"Each draw needs at least {NUM_MAIN} numbers, got {len(draw)}."
        )

    main = sorted(int(n) for n in draw[:NUM_MAIN])
    bonus = int(draw[NUM_MAIN]) if len(draw) > NUM_MAIN and draw[NUM_MAIN] else 0

    draw_sum = sum(main) / MAX_POSSIBLE_SUM
    odd_count = sum(1 for n in main if n % 2 == 1) / NUM_MAIN
    even_count = 1.0 - odd_count
    gaps = [b - a for a, b in zip(main, main[1:], strict=False)]
    max_gap = (max(gaps) if gaps else 0) / POOL_SIZE

    # Shannon entropy across 5 blocks of 8 numbers, normalised to [0, 1]
    block_counts = np.zeros(NUM_BLOCKS, dtype=np.float64)
    for n in main:
        block = min((n - 1) // BLOCK_SIZE, NUM_BLOCKS - 1)
        block_counts[block] += 1
    probs = block_counts / block_counts.sum()
    nonzero = probs[probs > 0]
    block_entropy = float(-np.sum(nonzero * np.log2(nonzero)) / math.log2(NUM_BLOCKS))

    features = [n / POOL_SIZE for n in main] + [
        bonus / POOL_SIZE,
        draw_sum,
        odd_count,
        even_count,
        max_gap,
        block_entropy,
    ]
    return np.asarray(features, dtype=np.float32)


def build_training_data(
    draws: list[list[int]], window: int = WINDOW
) -> tuple[np.ndarray, np.ndarray]:
    """Sliding window over chronological draws.

    Args:
        draws: Chronological list of draws; each draw is a list of at
            least 6 main numbers plus an optional 7th bonus number.
        window: Number of timesteps per input sequence.

    Returns:
        x: (n_samples, window, 12) float32 feature sequences.
        y: (n_samples, 40) float32 soft targets — 1/6 on each drawn
           number, i.e. a valid distribution for categorical cross-entropy.
    """
    x, y = [], []
    for i in range(len(draws) - window):
        x.append([engineer_features(d) for d in draws[i : i + window]])
        vec = np.zeros(POOL_SIZE, dtype=np.float32)
        for n in draws[i + window][:NUM_MAIN]:
            if 1 <= int(n) <= POOL_SIZE:
                vec[int(n) - 1] = 1.0 / NUM_MAIN
        y.append(vec)
    return (
        np.asarray(x, dtype=np.float32).reshape(-1, window, NUM_FEATURES),
        np.asarray(y, dtype=np.float32),
    )


def compute_class_weights(draws: list[list[int]]) -> np.ndarray:
    """Per-number weights ``1 / sqrt(frequency)`` over the FULL history.

    Rare numbers get higher weight to counter class imbalance. Weights
    are normalised to mean 1.0 for stable loss magnitudes, and numbers
    never drawn receive the maximum (rarest) weight.

    Returns:
        np.ndarray of shape (40,), float32.
    """
    freq = np.zeros(POOL_SIZE, dtype=np.float64)
    for draw in draws:
        for n in draw[:NUM_MAIN]:
            if 1 <= int(n) <= POOL_SIZE:
                freq[int(n) - 1] += 1.0

    positive = freq[freq > 0]
    fallback = positive.min() if len(positive) else 1.0
    safe_freq = np.where(freq > 0, freq, fallback)
    weights = 1.0 / np.sqrt(safe_freq)
    weights /= weights.mean()
    return weights.astype(np.float32)


def weighted_categorical_crossentropy(
    class_weights: np.ndarray,
) -> Callable[[tf.Tensor, tf.Tensor], tf.Tensor]:
    """Build a weighted categorical cross-entropy loss.

    loss = -sum_i(w_i * y_i * log(p_i)) with w from
    :func:`compute_class_weights`. The batch mean is taken by Keras.
    """
    weights = tf.constant(np.asarray(class_weights, dtype=np.float32))

    def loss(y_true: tf.Tensor, y_pred: tf.Tensor) -> tf.Tensor:
        y_pred = tf.clip_by_value(y_pred, 1e-7, 1.0)
        return -tf.reduce_sum(y_true * tf.math.log(y_pred) * weights, axis=-1)

    return loss


# ---------------------------------------------------------------------------
# Model construction
# ---------------------------------------------------------------------------
def build_model(class_weights: np.ndarray, window: int = WINDOW) -> keras.Model:
    """Masking -> LSTM(128) -> LSTM(64) -> Dense(128) -> Dropout -> Dense(40)."""
    model = keras.Sequential(
        [
            keras.layers.Input(shape=(window, NUM_FEATURES)),
            keras.layers.Masking(mask_value=0.0),
            keras.layers.LSTM(
                128, return_sequences=True, dropout=0.2, recurrent_dropout=0.2
            ),
            keras.layers.LSTM(64, dropout=0.2, recurrent_dropout=0.2),
            keras.layers.Dense(128, activation="relu"),
            keras.layers.Dropout(0.3),
            keras.layers.Dense(POOL_SIZE, activation="softmax"),
        ]
    )
    model.compile(
        optimizer=keras.optimizers.AdamW(
            learning_rate=LEARNING_RATE, weight_decay=WEIGHT_DECAY
        ),
        loss=weighted_categorical_crossentropy(class_weights),
        metrics=["accuracy"],
    )
    return model


def load_training_history() -> dict[str, Any] | None:
    """Read the training loss curve for the dashboard.

    Prefers TensorBoard event files under ``data/logs/lstm`` (parsed via
    tensorboard's EventAccumulator when available); falls back to the
    ``history.json`` written after every training run.

    Returns:
        {"loss": [...], "val_loss": [...]} or None when nothing is logged.
    """
    if TENSORBOARD_LOG_DIR.exists():
        try:
            from tensorboard.backend.event_processing.event_accumulator import (
                EventAccumulator,
            )

            acc = EventAccumulator(str(TENSORBOARD_LOG_DIR))
            acc.Reload()
            tags = acc.Tags().get("scalars", [])
            if "epoch_loss" in tags:
                history = {
                    "loss": [e.value for e in acc.Scalars("epoch_loss")],
                    "val_loss": [e.value for e in acc.Scalars("epoch_val_loss")]
                    if "epoch_val_loss" in tags
                    else [],
                }
                if history["loss"]:
                    return history
        except ImportError:
            pass  # tensorboard not installed — fall through to history.json
        except Exception as exc:  # corrupt/partial event files
            logger.debug("Could not parse TensorBoard logs: %s", exc)

    if HISTORY_PATH.exists():
        try:
            return cast(dict[str, Any], json.loads(HISTORY_PATH.read_text()))
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("Could not read %s: %s", HISTORY_PATH, exc)
    return None


# ---------------------------------------------------------------------------
# Predictor
# ---------------------------------------------------------------------------
class DeepPredictor:
    """LSTM over draw sequences -> probability distribution over 1..40."""

    def __init__(
        self,
        model_path: Path | str = DEFAULT_MODEL_PATH,
        window: int = WINDOW,
    ) -> None:
        if not HAS_TF:
            raise RuntimeError(
                "TensorFlow is not installed — use create_predictor(), which "
                "returns StubDeepPredictor instead."
            )
        self.model_path = Path(model_path)
        self.window = window
        self.model: keras.Model | None = None
        self.is_stub = False

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    def train(
        self,
        draws: list[list[int]],
        epochs: int = EPOCHS,
        batch_size: int = BATCH_SIZE,
        seed: int = 42,
    ) -> dict[str, Any]:
        """Build training data (sliding window), augment, and fit.

        The 80/20 split is temporal — never shuffled. Gaussian noise
        (sigma=0.01) is added to the training features only. Class
        weights are computed from the FULL history, not just the
        training split.

        Returns:
            Training summary dict (samples, epochs run, paths).
        """
        if len(draws) < self.window + 2:
            raise ValueError(
                f"Need at least {self.window + 2} draws to train, got {len(draws)}."
            )

        x, y = build_training_data(draws, self.window)
        class_weights = compute_class_weights(draws)

        # Temporal 80/20 split — no shuffle, time series
        split = max(1, int(TRAIN_FRACTION * len(x)))
        if len(x) - split < 1:
            x_train, y_train, x_val, y_val = x, y, None, None
        else:
            x_train, x_val = x[:split], x[split:]
            y_train, y_val = y[:split], y[split:]

        # Augmentation: Gaussian noise on numerical features (train only)
        rng = np.random.default_rng(seed)
        x_train = x_train + rng.normal(0.0, NOISE_SIGMA, x_train.shape).astype(
            np.float32
        )

        self.model = build_model(class_weights, self.window)
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        TENSORBOARD_LOG_DIR.mkdir(parents=True, exist_ok=True)

        has_val = x_val is not None
        monitor = "val_loss" if has_val else "loss"
        callbacks = [
            keras.callbacks.EarlyStopping(
                monitor=monitor,
                patience=EARLY_STOP_PATIENCE,
                restore_best_weights=True,
                verbose=1,
            ),
            keras.callbacks.ReduceLROnPlateau(
                monitor=monitor,
                patience=LR_PATIENCE,
                factor=LR_FACTOR,
                verbose=1,
            ),
            keras.callbacks.ModelCheckpoint(
                str(self.model_path),
                monitor=monitor,
                save_best_only=True,
                verbose=1,
            ),
            keras.callbacks.TensorBoard(log_dir=str(TENSORBOARD_LOG_DIR)),
        ]

        history = self.model.fit(
            x_train,
            y_train,
            epochs=epochs,
            batch_size=batch_size,
            validation_data=(x_val, y_val) if has_val else None,
            callbacks=callbacks,
            verbose=1,
            shuffle=False,
        )

        # JSON fallback so the dashboard can plot loss without TensorBoard
        try:
            HISTORY_PATH.write_text(
                json.dumps(
                    {
                        "loss": [float(v) for v in history.history.get("loss", [])],
                        "val_loss": [
                            float(v) for v in history.history.get("val_loss", [])
                        ],
                    }
                )
            )
        except OSError as exc:
            logger.debug("Could not write %s: %s", HISTORY_PATH, exc)

        return {
            "stub": False,
            "samples": len(x),
            "train_samples": len(x_train),
            "val_samples": len(x_val) if x_val is not None else 0,
            "epochs_run": len(history.history.get("loss", [])),
            "model_path": str(self.model_path),
            "model_version": MODEL_VERSION,
        }

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def load(self) -> bool:
        """Load the checkpointed model from disk, if present."""
        if not self.model_path.exists():
            return False
        # compile=False: the weighted loss closure is not needed for inference
        self.model = keras.models.load_model(self.model_path, compile=False)
        return True

    def _ensure_model(self) -> bool:
        if self.model is not None:
            return True
        try:
            return self.load()
        except Exception as exc:
            logger.warning("Could not load LSTM checkpoint: %s", exc)
            return False

    def _prepare_sequence(self, last_draws: list[list[int]]) -> np.ndarray:
        """Encode the most recent draws as one (1, window, 12) sequence.

        Left-pads with all-zero timesteps when fewer than ``window`` draws
        are available — the Masking layer ignores those rows.
        """
        recent = [engineer_features(d) for d in last_draws[-self.window :]]
        pad = self.window - len(recent)
        if pad > 0:
            recent = [np.zeros(NUM_FEATURES, dtype=np.float32)] * pad + recent
        return np.asarray([recent], dtype=np.float32)

    def predict_proba(self, last_draws: list[list[int]]) -> np.ndarray:
        """Raw probability vector over numbers 1..40 (sums to 1.0).

        Falls back to the uniform distribution with a warning when no
        trained model is available.
        """
        if not self._ensure_model():
            logger.warning(
                "No trained LSTM model at %s — returning uniform probabilities.",
                self.model_path,
            )
            return np.full(POOL_SIZE, 1.0 / POOL_SIZE, dtype=np.float32)
        x = self._prepare_sequence(last_draws)
        model = cast(keras.Model, self.model)
        probs: np.ndarray = model.predict(x, verbose=0)[0].astype(np.float64)
        return probs

    def predict_next_draw(self, last_10_draws: list[list[int]]) -> dict[str, Any]:
        """Full inference payload for the most recent draws.

        Args:
            last_10_draws: Up to 10 most recent draws (chronological),
                each a list of 6 main numbers plus optional bonus.

        Returns:
            {"top_20": [(num, prob), ...], "top_6": [n, ...],
             "entropy": float, "model_version": str, "generated_at": iso}
        """
        probs = self.predict_proba(last_10_draws)

        ranked = sorted(
            ((i + 1, float(p)) for i, p in enumerate(probs)),
            key=lambda t: t[1],
            reverse=True,
        )
        top_6 = sorted(n for n, _ in ranked[:NUM_MAIN])  # no duplicates by construction
        entropy = float(-np.sum(probs * np.log(np.clip(probs, 1e-12, None))))

        return {
            "top_20": ranked[:20],
            "top_6": top_6,
            "entropy": entropy,
            "model_version": MODEL_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    # ------------------------------------------------------------------
    # Dashboard helpers
    # ------------------------------------------------------------------
    def entropy_over_time(
        self, draws: list[list[int]], max_points: int = 60
    ) -> list[tuple[int, float]]:
        """Prediction entropy for rolling windows over the draw history.

        Returns [(draw_index, entropy), ...] for up to ``max_points``
        most recent windows. Lower entropy = more confident prediction.
        """
        if len(draws) < self.window + 1:
            return []
        indices = range(self.window, len(draws))
        if max_points and len(indices) > max_points:
            indices = indices[-max_points:]
        points = []
        for i in indices:
            probs = self.predict_proba(draws[i - self.window : i])
            entropy = float(-np.sum(probs * np.log(np.clip(probs, 1e-12, None))))
            points.append((i, entropy))
        return points

    def feature_saliency(
        self, draws: list[list[int]], max_samples: int = 32
    ) -> dict[str, float] | None:
        """Gradient-based feature importance (the model has no attention
        layer, so saliency = mean |d output / d input| per feature).

        Returns {feature_name: importance} normalised to sum 1, or None
        when no trained model is available.
        """
        if not self._ensure_model():
            return None
        x_windows, _ = build_training_data(draws, self.window)
        if len(x_windows) == 0:
            return None
        x_windows = x_windows[-max_samples:]
        x = tf.constant(x_windows)
        model = cast(keras.Model, self.model)
        with tf.GradientTape() as tape:
            tape.watch(x)
            preds = model(x, training=False)
            top = tf.reduce_max(preds, axis=-1)
        grads = tape.gradient(top, x)
        importance = tf.reduce_mean(tf.abs(grads), axis=(0, 1)).numpy()
        total = float(importance.sum())
        if total > 0:
            importance = importance / total
        return {
            name: float(v) for name, v in zip(FEATURE_NAMES, importance, strict=True)
        }


# ---------------------------------------------------------------------------
# Stub (used when TensorFlow is unavailable)
# ---------------------------------------------------------------------------
class StubDeepPredictor:
    """Drop-in replacement that logs a warning and returns uniform
    probabilities, so the pipeline keeps working without TensorFlow."""

    is_stub = True

    def __init__(
        self,
        model_path: Path | str = DEFAULT_MODEL_PATH,
        window: int = WINDOW,
    ) -> None:
        self.model_path = Path(model_path)
        self.window = window
        logger.warning(
            "StubDeepPredictor active — TensorFlow not installed, "
            "all predictions are uniform (1/%d per number).",
            POOL_SIZE,
        )

    def train(self, draws: list[list[int]], **kwargs: Any) -> dict[str, Any]:
        logger.warning("StubDeepPredictor.train() is a no-op (TensorFlow missing).")
        return {
            "stub": True,
            "samples": max(0, len(draws) - self.window),
            "epochs_run": 0,
        }

    def load(self) -> bool:
        return False

    def predict_proba(self, last_draws: list[list[int]]) -> np.ndarray:
        return np.full(POOL_SIZE, 1.0 / POOL_SIZE, dtype=np.float64)

    def predict_next_draw(self, last_10_draws: list[list[int]]) -> dict[str, Any]:
        probs = self.predict_proba(last_10_draws)
        ranked = [(n, float(probs[n - 1])) for n in range(1, POOL_SIZE + 1)]
        return {
            "top_20": ranked[:20],
            "top_6": list(range(1, NUM_MAIN + 1)),
            "entropy": float(math.log(POOL_SIZE)),  # maximum entropy = uniform
            "model_version": f"{MODEL_VERSION}-stub",
            "generated_at": datetime.now(UTC).isoformat(),
        }

    def entropy_over_time(
        self, draws: list[list[int]], max_points: int = 60
    ) -> list[tuple[int, float]]:
        if len(draws) < self.window + 1:
            return []
        indices = range(self.window, len(draws))
        if max_points and len(indices) > max_points:
            indices = indices[-max_points:]
        return [(i, float(math.log(POOL_SIZE))) for i in indices]

    def feature_saliency(self, draws: list[list[int]], max_samples: int = 32) -> None:
        return None


_default_predictor: DeepPredictor | StubDeepPredictor | None = None


def create_predictor(
    model_path: Path | str = DEFAULT_MODEL_PATH,
    use_cache: bool = True,
) -> DeepPredictor | StubDeepPredictor:
    """Factory: real LSTM when TensorFlow is installed, stub otherwise.

    Caches one process-wide instance by default (model loading is
    expensive); pass ``use_cache=False`` for a fresh instance.
    """
    global _default_predictor
    if use_cache and _default_predictor is not None:
        return _default_predictor
    cls: type[DeepPredictor | StubDeepPredictor] = (
        DeepPredictor if HAS_TF else StubDeepPredictor
    )
    predictor = cls(model_path=model_path)
    if use_cache:
        _default_predictor = predictor
    return predictor


def predict_next_draw(last_10_draws: list[list[int]]) -> dict[str, Any]:
    """Module-level convenience wrapper around the cached predictor."""
    return create_predictor().predict_next_draw(last_10_draws)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print(f"TensorFlow available: {HAS_TF} (stub mode: {not HAS_TF})")

    # 100 synthetic draws with a mild bias toward low numbers
    rng = np.random.default_rng(42)
    number_probs = np.array([1.0 / (n**0.3) for n in range(1, POOL_SIZE + 1)])
    number_probs /= number_probs.sum()
    synthetic_draws = [
        sorted(
            rng.choice(
                range(1, POOL_SIZE + 1), size=6, replace=False, p=number_probs
            ).tolist()
        )
        + [int(rng.integers(1, 11))]  # bonus
        for _ in range(100)
    ]

    predictor = create_predictor(use_cache=False)
    summary = predictor.train(synthetic_draws, epochs=5 if HAS_TF else 1)
    print(
        f"Training summary: {summary['samples']} samples, "
        f"{summary['epochs_run']} epoch(s), stub={summary['stub']}"
    )

    last_10 = synthetic_draws[-WINDOW:]

    # 1. Output probabilities sum to ~1.0
    probs = predictor.predict_proba(last_10)
    total = float(probs.sum())
    assert abs(total - 1.0) < 1e-4, f"probabilities sum to {total}, expected ~1.0"
    print(f"[OK] probabilities sum to {total:.6f}")

    # 2. top_6 has no duplicates
    result = predictor.predict_next_draw(last_10)
    assert len(result["top_6"]) == 6, f"top_6 has {len(result['top_6'])} numbers"
    assert len(set(result["top_6"])) == 6, f"top_6 has duplicates: {result['top_6']}"
    print(f"[OK] top_6 = {result['top_6']} (unique)")

    # 3. Inference < 200ms on CPU (after one warm-up call)
    predictor.predict_next_draw(last_10)
    start = time.perf_counter()
    predictor.predict_next_draw(last_10)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 200, f"inference took {elapsed_ms:.1f}ms, expected < 200ms"
    print(f"[OK] inference took {elapsed_ms:.1f}ms (< 200ms)")

    print(f"\nEntropy: {result['entropy']:.4f} (max = {math.log(POOL_SIZE):.4f})")
    print("Top 20 predicted numbers (number: probability):")
    for num, prob in result["top_20"]:
        print(f"  {num:2d}: {prob:.4f}")
    print("\nAll self-test checks passed.")
