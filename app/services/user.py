"""User service: registration, role management and access checks."""
from __future__ import annotations

from app.core.constants import USER_NAME_MAX_LENGTH, USER_NAME_MIN_LENGTH
from app.core.logging import get_logger
from app.db.models import Role, User
from app.repositories import UserDependencies, UserRepository

logger = get_logger(__name__)


class UserServiceError(Exception):
    """Domain-level error in :class:`UserService`."""


class UserService:
    """Encapsulates user-related business logic."""

    def __init__(self, repo: UserRepository, *, admin_ids: list[int]) -> None:
        self._repo = repo
        self._admin_ids = set(admin_ids)

    @staticmethod
    def validate_full_name(name: str) -> str:
        """Trim + length-check a display name.

        Raises :class:`UserServiceError` when the name doesn't fit the
        configured ``USER_NAME_MIN_LENGTH``/``USER_NAME_MAX_LENGTH``
        window.
        """
        name = (name or "").strip()
        if not (USER_NAME_MIN_LENGTH <= len(name) <= USER_NAME_MAX_LENGTH):
            raise UserServiceError(
                f"Имя должно содержать "
                f"{USER_NAME_MIN_LENGTH}–{USER_NAME_MAX_LENGTH} символов."
            )
        return name

    async def get_or_bootstrap_admin(
        self, *, telegram_id: int, full_name: str
    ) -> User | None:
        """Ensure that statically-configured admins exist in DB and return user.

        Returns ``None`` if the user is not registered and not in the admin list.
        """
        existing = await self._repo.get_by_telegram_id(telegram_id)
        if existing is not None:
            if existing.role != Role.ADMIN and telegram_id in self._admin_ids:
                existing.role = Role.ADMIN
                existing.is_active = True
            return existing

        if telegram_id in self._admin_ids:
            logger.info("Bootstrapping admin", telegram_id=telegram_id)
            return await self._repo.create(
                telegram_id=telegram_id, role=Role.ADMIN, full_name=full_name
            )
        return None

    async def assign_role(
        self, *, telegram_id: int, role: Role, full_name: str
    ) -> User:
        """Assign or update a user role (admin operation)."""
        logger.info(
            "Assigning role", telegram_id=telegram_id, role=role.value, name=full_name
        )
        return await self._repo.upsert_role(
            telegram_id=telegram_id, role=role, full_name=full_name
        )

    async def set_active(self, user_id: int, *, is_active: bool) -> None:
        await self._repo.set_active(user_id, is_active=is_active)
        logger.info("User active flag changed", user_id=user_id, is_active=is_active)

    async def rename(self, *, user_id: int, full_name: str) -> User:
        """Change a user's display name. Admin-only operation in
        practice; the handler enforces role-level access."""
        name = self.validate_full_name(full_name)
        updated = await self._repo.rename(user_id, full_name=name)
        if updated is None:
            raise UserServiceError("Пользователь не найден.")
        logger.info("User renamed", user_id=user_id, new_name=name)
        return updated

    # ---- Admin moderation ---------------------------------------------

    def _check_admin_action(self, *, actor: User, target: User) -> None:
        """Common safety checks for moderation actions."""
        if actor.role != Role.ADMIN:
            raise UserServiceError("Только администратор может выполнять это действие.")
        if actor.id == target.id:
            raise UserServiceError("Нельзя выполнять это действие над собой.")
        if target.role == Role.ADMIN:
            raise UserServiceError("Нельзя выполнять это действие над администратором.")

    async def dependencies(self, user_id: int) -> UserDependencies:
        """Return cross-table reference counts for a user."""
        return await self._repo.dependencies(user_id)

    async def block(self, *, target: User, actor: User) -> None:
        """Deactivate a user — they keep their data and history but
        can no longer interact with the bot."""
        self._check_admin_action(actor=actor, target=target)
        if not target.is_active:
            raise UserServiceError("Пользователь уже заблокирован.")
        await self._repo.set_active(target.id, is_active=False)
        logger.info("User blocked", user_id=target.id, actor_id=actor.id)

    async def unblock(self, *, target: User, actor: User) -> None:
        """Re-activate a previously blocked user."""
        if actor.role != Role.ADMIN:
            raise UserServiceError("Только администратор может выполнять это действие.")
        if target.is_active:
            raise UserServiceError("Пользователь уже активен.")
        await self._repo.set_active(target.id, is_active=True)
        logger.info("User unblocked", user_id=target.id, actor_id=actor.id)

    async def delete(self, *, target: User, actor: User) -> UserDependencies:
        """Hard-delete a user.

        * Tasks where the user is the customer are deleted cascading
          (together with their comments and attachments).
        * Tasks where the user is the designer have ``designer_id``
          set to ``NULL`` via FK ``ON DELETE SET NULL``.  Callers that
          want active tasks redistributed to other designers should do
          so **before** invoking this method.
        * Comments and attachments authored by the user in *other*
          people's tasks survive; their author/uploader columns become
          ``NULL`` (the UI shows comments anonymously by role anyway).

        Returns the dependency snapshot, so the caller can show
        "removed N tasks / kept M comments" feedback.
        """
        self._check_admin_action(actor=actor, target=target)
        deps = await self._repo.dependencies(target.id)
        deleted = await self._repo.delete(target.id)
        if not deleted:
            raise UserServiceError("Пользователь не найден.")
        logger.info(
            "User deleted",
            user_id=target.id,
            actor_id=actor.id,
            cascaded_tasks=deps.tasks_as_customer,
            orphaned_comments=deps.comments,
            orphaned_attachments=deps.attachments,
        )
        return deps

    async def list_designers(self) -> list[User]:
        return await self._repo.list_by_role(Role.DESIGNER)

    async def list_customers(self) -> list[User]:
        return await self._repo.list_by_role(Role.CUSTOMER)

    async def list_all(self) -> list[User]:
        return await self._repo.list_all()

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return await self._repo.get_by_telegram_id(telegram_id)

    async def get_by_id(self, user_id: int) -> User | None:
        return await self._repo.get_by_id(user_id)

    async def role_counts(self) -> dict[Role, int]:
        return await self._repo.count_by_role()
