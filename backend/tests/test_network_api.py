"""The station and network endpoints, against the real CSV."""

from tests.conftest import START


def test_stations_lists_all_twenty_six(client):
    response = client.get("/stations")
    assert response.status_code == 200

    body = response.json()
    assert body["count"] == 26
    assert len(body["stations"]) == 26

    names = [s["name"] for s in body["stations"]]
    assert START in names
    assert len(set(names)) == 26


def test_station_fields_come_from_the_dataset(client):
    from app.dataio.network import get_network

    network = get_network()
    station = next(
        s for s in client.get("/stations").json()["stations"]
        if s["name"] == START
    )
    source = network.stations[START]

    assert station["type"] == source.type_label
    assert station["latitude"] == source.latitude
    assert station["longitude"] == source.longitude
    assert station["connections"] == len(network.adjacency[START])


def test_network_returns_the_full_graph(client):
    response = client.get("/network")
    assert response.status_code == 200

    body = response.json()
    assert body["summary"]["stations"] == 26
    assert body["summary"]["routable_lines"] == 38
    assert body["summary"]["connected"] is True
    assert len(body["stations"]) == 26
    assert len(body["transmission_lines"]) == 38
    assert body["dataset_path"].endswith(".csv")


def test_transmission_lines_carry_the_csv_attributes(client):
    lines = client.get("/network").json()["transmission_lines"]
    for line in lines:
        assert line["source"] != line["destination"]
        assert line["distance_km"] > 0
    # Every line the dataset marks routable is present, none invented.
    from app.dataio.network import get_network
    assert len(lines) == len(get_network().edges)


def test_resolve_accepts_an_exact_name(client):
    response = client.post("/stations/resolve", json={"start": START})
    assert response.status_code == 200
    assert response.json() == {
        "requested": START, "resolved": START, "matched_exactly": True
    }


def test_resolve_accepts_a_unique_partial_name(client):
    response = client.post("/stations/resolve", json={"start": "mysuru"})
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] == START
    assert body["matched_exactly"] is False


def test_resolve_rejects_an_unknown_station(client):
    response = client.post("/stations/resolve", json={"start": "Atlantis"})
    assert response.status_code == 422

    detail = response.json()["detail"]
    assert detail["error"] == "unknown_start_station"
    assert detail["station_count"] == 26
    assert "/stations" in detail["hint"]


def test_resolve_rejects_an_ambiguous_station(client):
    response = client.post("/stations/resolve", json={"start": "Substation"})
    assert response.status_code == 422

    detail = response.json()["detail"]
    assert detail["error"] == "ambiguous_start_station"
    assert len(detail["suggestions"]) > 1


def test_resolve_rejects_an_empty_station(client):
    response = client.post("/stations/resolve", json={"start": ""})
    assert response.status_code == 422
