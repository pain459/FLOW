import os
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

_initialized = False


def setup_telemetry(service: str, engine=None) -> None:
    global _initialized
    if not _initialized:
        provider = TracerProvider(
            resource=Resource.create({"service.name": service, "deployment.environment": "lab"})
        )
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if endpoint:
            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=endpoint, insecure=True, timeout=2),
                    max_queue_size=1024,
                    max_export_batch_size=128,
                    schedule_delay_millis=1000,
                )
            )
        trace.set_tracer_provider(provider)
        HTTPXClientInstrumentor().instrument()
        # Redis spans contain commands by default: suppress argument formatting.
        RedisInstrumentor().instrument(
            request_hook=lambda span, instance, args, kwargs: span.set_attribute(
                "db.statement", str(args[0]) if args else "REDIS"
            )
        )
        _initialized = True
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)


def shutdown_telemetry() -> None:
    provider = trace.get_tracer_provider()
    if hasattr(provider, "shutdown"):
        provider.shutdown()
