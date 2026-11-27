"""The /prediction page links one heatmap per threshold and correlation method.

These images are committed to git (see predictionPlots.py), so a deploy from a
fresh checkout serves them. This test fails if one goes missing again.
"""
import re

import pytest

from config import WORK_DIR


TEMPLATE = WORK_DIR / "templates" / "prediction.html"
PLOT_DIR = WORK_DIR / "static" / "images" / "plots"
METHODS = ( "pearson", "kendall", "spearman" )


def template_thresholds():
	match = re.search( r"\[([\d,\s]+)\]\.map\(option", TEMPLATE.read_text( encoding = "utf-8" ) )
	assert match, "threshold list not found in prediction.html"
	return [ int( value ) for value in match.group( 1 ).split( "," ) ]


def test_thresholds_match_the_plot_script():
	predictionPlots = pytest.importorskip( "predictionPlots" )  # needs matplotlib and seaborn
	assert tuple( template_thresholds() ) == predictionPlots.THRESHOLDS


@pytest.mark.parametrize( "method", METHODS )
def test_every_linked_plot_exists( method ):
	for threshold in template_thresholds():
		path = PLOT_DIR / f"plot{threshold}-{method}.jpg"
		assert path.is_file() and path.stat().st_size > 0, f"missing {path.relative_to( WORK_DIR )}"


def test_page_links_the_default_plots( client ):
	page = client.get( "/prediction" ).get_data( as_text = True )
	for method in METHODS:
		assert f"/static/images/plots/plot35-{method}.jpg" in page
