"""AWS Lambda entrypoint.

Mangum adapts the ASGI app to the Lambda event/response shape, so the exact
same FastAPI application serves both `uvicorn` locally and Lambda in AWS.

`lifespan="off"` because the app declares no startup/shutdown hooks; leaving it
on would run the lifespan protocol on every cold start for no benefit.
"""

from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="off")
