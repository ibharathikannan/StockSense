"""Date-block uncertainty diagnostics preserve cross-sectional dependence."""
import numpy as np
import pandas as pd

from data.forecasting.walkforward import GRID, paired_intervals


def test_grid_is_bounded_and_predeclared():
    assert len(GRID) == 12
    assert len({tuple(sorted(item.items())) for item in GRID}) == 12


def test_block_intervals_have_correct_gain_units_and_are_reproducible():
    frame = pd.DataFrame({'Date': np.repeat(pd.bdate_range('2024-01-01', periods=60), 2),
                          'target_return_10d': .02})

    class Bundle:
        metadata = {'training_median': 0.0}

        def predict(self, rows):
            return pd.DataFrame({'predicted_return_10d': np.full(len(rows), .01)})

    result = paired_intervals(Bundle(), frame, repeats=20)
    assert result == paired_intervals(Bundle(), frame, repeats=20)
    assert [row['block_sessions'] for row in result] == [10,20,40]
    for row in result:
        assert np.isclose(row['mae_gain_vs_median_pp'], 1)
        assert np.isclose(row['lower_95_pp'], 1)
        assert np.isclose(row['upper_95_pp'], 1)
