from app.main import create_app


def test_graphql_operations_listed_in_openapi():
    app = create_app()
    schema = app.openapi()
    paths = schema["paths"]

    assert "/graphql/queries/status" in paths
    assert "/graphql/mutations/login" in paths
    assert "/graphql/queries/companies" in paths
    assert "/graphql/mutations/createProject" in paths

    status_post = paths["/graphql/queries/status"]["post"]
    assert status_post["summary"] == "GraphQL query: status"
    assert "graphql-system" in status_post["tags"]


def test_graphql_swagger_route_count():
    app = create_app()
    paths = app.openapi()["paths"]
    graphql_ops = [
        p
        for p in paths
        if p.startswith("/graphql/queries/") or p.startswith("/graphql/mutations/")
    ]
    assert len(graphql_ops) >= 57
