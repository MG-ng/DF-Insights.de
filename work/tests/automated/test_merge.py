"""Unit tests for merging SMARD rows with computed-view rows (psqlDatabase.QueryComplex.merge)."""
from psqlDatabase.QueryComplex import merge


KEY_A = (1000, "DE", "day")
KEY_B = (2000, "DE", "day")
KEY_C = (3000, "DE", "day")


def rows_by_key( rows ):
	return { tuple( row[:3] ): tuple( row[3:] ) for row in rows }


def test_merge_combines_rows_with_the_same_key():
	smard = ( [ KEY_A + (1, 2) ], [ "ts", "region", "resolution", "s1", "s2" ] )
	view = ( [ KEY_A + (3,) ], [ "ts", "region", "resolution", "v1" ] )
	assert rows_by_key( merge( smard, view ) ) == { KEY_A: (1, 2, 3) }


def test_merge_fills_missing_sides_with_none():
	smard = ( [ KEY_A + (1, 2), KEY_B + (4, 5) ], [ "ts", "region", "resolution", "s1", "s2" ] )
	view = ( [ KEY_B + (6,), KEY_C + (7,) ], [ "ts", "region", "resolution", "v1" ] )
	assert rows_by_key( merge( smard, view ) ) == {
		KEY_A: (1, 2, None),
		KEY_B: (4, 5, 6),
		KEY_C: (None, None, 7),
	}


def test_merge_of_empty_results_is_empty():
	columns = [ "ts", "region", "resolution", "x" ]
	assert merge( ( [], columns ), ( [], columns ) ) == []
