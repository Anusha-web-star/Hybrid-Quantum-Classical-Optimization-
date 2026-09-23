"""The graph endpoints, including one run that actually writes the images."""

from tests.conftest import FAST_HYBRID, START


def test_graphs_lists_the_three_images(client):
    response = client.get("/graphs")
    assert response.status_code == 200

    body = response.json()
    names = {graph["name"] for graph in body["graphs"]}
    assert names == {"nn_route", "qaoa_route", "comparison"}
    for graph in body["graphs"]:
        assert graph["filename"].endswith(".png")
        assert graph["url"] == f"/graphs/{graph['name']}"


def test_unknown_graph_name_is_a_404(client):
    response = client.get("/graphs/not_a_graph")
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "unknown_graph"


def test_compare_writes_the_images_and_serves_them(client, outputs_dir):
    """End to end: run the comparison, then fetch a generated PNG."""
    response = client.post(
        "/solve/compare",
        json={"start": START, "render_graphs": True, **FAST_HYBRID},
    )
    assert response.status_code == 200

    graphs = response.json()["graphs"]
    assert graphs["urls"] == {
        "nn_route": "/graphs/nn_route",
        "qaoa_route": "/graphs/qaoa_route",
        "comparison": "/graphs/comparison",
    }

    for name in ("nn_route", "qaoa_route", "comparison"):
        assert graphs[name].startswith(str(outputs_dir))
        assert (outputs_dir / graphs[name].rsplit("\\", 1)[-1]).is_file()

    listing = {g["name"]: g for g in client.get("/graphs").json()["graphs"]}
    assert all(listing[name]["exists"] for name in listing)

    image = client.get("/graphs/comparison")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(image.content) > 1000


def test_missing_image_is_a_404(client, outputs_dir):
    """An empty outputs folder must say so, not raise."""
    response = client.get("/graphs/comparison")
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "graph_not_generated"
