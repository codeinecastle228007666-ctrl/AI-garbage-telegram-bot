from enum import Enum


class NotificationType(str, Enum):
    """Доступные типы уведомлений."""

    DAILY_DIGEST = "daily_digest"
    WEEKLY_REPORT = "weekly_report"
    SYSTEM_ALERT = "system_alert"
    PROMO = "promo"
    CUSTOM = "custom"


NOTIFICATION_CHOICES = {
    NotificationType.DAILY_DIGEST: "Ежедневный дайджест",
    NotificationType.WEEKLY_REPORT: "Еженедельный отчёт",
    NotificationType.SYSTEM_ALERT: "Системные оповещения",
    NotificationType.PROMO: "Акции и новости",
    NotificationType.CUSTOM: "Пользовательские",
}
