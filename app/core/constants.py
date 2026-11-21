"""Project-wide constants."""
from __future__ import annotations

# Pagination defaults
DEFAULT_PAGE_SIZE: int = 5
MAX_PAGE_SIZE: int = 20

# Telegram limits
MAX_MESSAGE_LENGTH: int = 4096
MAX_CAPTION_LENGTH: int = 1024

# Task input validation
TASK_TITLE_MIN_LENGTH: int = 3
TASK_TITLE_MAX_LENGTH: int = 200
TASK_DESCRIPTION_MIN_LENGTH: int = 3
TASK_DESCRIPTION_MAX_LENGTH: int = 4000
COMMENT_MAX_LENGTH: int = 4000

# User display-name input
USER_NAME_MIN_LENGTH: int = 2
USER_NAME_MAX_LENGTH: int = 100

# Reminders
REMINDER_24H_BEFORE_SECONDS: int = 24 * 60 * 60
REMINDER_2H_BEFORE_SECONDS: int = 2 * 60 * 60
