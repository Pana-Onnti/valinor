"""Channel adapters for NotificationRouter."""

from shared.notifications.adapters.email import EmailAdapter
from shared.notifications.adapters.webhook import WebhookAdapter
from shared.notifications.adapters.whatsapp import WhatsAppAdapter

__all__ = ["EmailAdapter", "WebhookAdapter", "WhatsAppAdapter"]
