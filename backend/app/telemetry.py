"""Optional Azure Application Insights via OpenTelemetry."""

from app.utils.logger import get_logger

logger = get_logger(__name__)


def setup_application_insights(connection_string: str) -> bool:
    """Configure Azure Monitor when connection string is set. Returns True if active."""
    conn = connection_string.strip()
    if not conn:
        return False
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError:
        logger.warning(
            "application_insights_skipped",
            reason="install azure-monitor-opentelemetry",
        )
        return False
    try:
        configure_azure_monitor(connection_string=conn)
        logger.info("application_insights_enabled")
        return True
    except Exception as exc:
        logger.warning("application_insights_failed", error=str(exc))
        return False
