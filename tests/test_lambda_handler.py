"""The Lambda entrypoint.

Cheap, but it guards the one thing unit tests would otherwise miss: the
container's CMD points at `app.lambda_handler.handler`, so a broken import or a
renamed attribute here fails only at deploy time, in AWS, on a cold start.
"""

from mangum import Mangum


def test_handler_is_importable_and_wraps_the_app():
    from app.lambda_handler import handler

    assert isinstance(handler, Mangum)


def test_handler_serves_health_through_a_lambda_event():
    """Drive the handler with a Function URL event to prove the adapter wiring."""
    from app.lambda_handler import handler

    event = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": "/health",
        "rawQueryString": "",
        "headers": {"host": "test.lambda-url.eu-central-1.on.aws"},
        "requestContext": {
            "http": {
                "method": "GET",
                "path": "/health",
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
            },
            "stage": "$default",
        },
        "isBase64Encoded": False,
    }

    response = handler(event, None)

    assert response["statusCode"] == 200
    assert '"ok"' in response["body"]
