"""Route tests that need no database: pages render and invalid input is rejected before any query runs."""
import pytest


@pytest.mark.parametrize( "path", [ "/", "/features", "/usage", "/prediction", "/trade", "/about" ] )
def test_pages_render( client, path ):
	response = client.get( path )
	assert response.status_code == 200
	assert b"<html" in response.data.lower()


def test_robots_txt( client ):
	response = client.get( "/robots.txt" )
	assert response.status_code == 200
	assert response.mimetype == "text/plain"


def test_security_txt( client ):
	response = client.get( "/.well-known/security.txt" )
	assert response.status_code == 200
	assert b"Contact:" in response.data


@pytest.mark.parametrize( "query", [
	"region=XX",
	"resolution=minute",
	"filters=999999",
	"startTime=2000&endTime=1000",
	"startTime=-1",
	"endTime=3000000000000",
] )
def test_api_rejects_invalid_input( client, query ):
	assert client.get( f"/api?{query}" ).status_code == 404


@pytest.mark.parametrize( "route", [ "/search", "/trend" ] )
@pytest.mark.parametrize( "query", [
	"region=XX",
	"resolution=minute",
	"maxShare=1.5",
	"maxShare=-0.1",
	"min_duration_ms=-1",
	"startTime=2000&endTime=1000",
] )
def test_dunkelflaute_routes_reject_invalid_input( client, route, query ):
	assert client.get( f"{route}?{query}" ).status_code == 404


@pytest.mark.parametrize( "table", [ "smard_data_collection", "computed_data_dunkelflauten_enriched", "pg_user" ] )
def test_enriched_df_rejects_unknown_tables( client, table ):
	assert client.get( f"/enrichedDF?tableName={table}" ).status_code == 404


@pytest.mark.parametrize( "path", [ "/", "/about", "/features" ] )
def test_pages_send_a_content_security_policy( client, path ):
	headers = client.get( path ).headers
	policy = headers.get( "Content-Security-Policy" ) or headers.get( "Content-Security-Policy-Report-Only" )
	assert policy, "pages must send a CSP header (enforced or report-only)"
	assert "default-src 'self'" in policy
	assert "frame-ancestors 'none'" in policy
	assert "object-src 'none'" in policy



def test_trade_page_is_linked_and_has_disclaimer( client ):
	assert b'href="/trade"' in client.get( "/" ).data
	page = client.get( "/trade" ).data
	assert b"Not financial, tax or legal advice" in page
	assert b'id="sources"' in page
