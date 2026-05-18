DRAWS_PER_WEEK = 2
# Ensures the same half-life in real time when draws occur twice per week
DECAY_PER_DRAW = 0.98 ** (1 / DRAWS_PER_WEEK)
