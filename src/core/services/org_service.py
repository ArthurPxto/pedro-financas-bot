"""Serviço de organização/identidade — neutro de canal.

Resolve a identidade de um canal (Telegram, WhatsApp, ...) para o usuário e a
organização internos. Auto-provisiona na primeira interação, para que o bot
de hoje (uso individual) continue funcionando sem onboarding explícito — o
onboarding de equipe é a Fase 1.
"""
from dataclasses import dataclass
from typing import Callable

from src.core.entities import (
    Channel,
    ChannelIdentity,
    Membership,
    Organization,
    Role,
    User,
)
from src.core.ports.repositories import UnitOfWork


@dataclass(frozen=True)
class UserContext:
    """Identidade interna resolvida, passada às operações de negócio.

    Substitui o `telegram_id` solto que circulava pelos handlers.
    """

    user_id: int
    org_id: int
    display_name: str


class OrgService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]):
        self._uow_factory = uow_factory

    async def resolve_context(
        self, channel: Channel, external_id: str, display_name: str
    ) -> UserContext:
        """Encontra (ou cria) usuário + org para uma identidade de canal."""
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_channel_identity(channel, external_id)
            if user is not None:
                org = await uow.organizations.get_primary_for_user(user.id)
                # Defensivo: usuário sem org (estado inesperado) ganha uma pessoal.
                if org is None:
                    org = await self._create_personal_org(uow, user, display_name)
                    await uow.commit()
                return UserContext(user.id, org.id, display_name)

            # Primeira interação: cria usuário + org pessoal + vínculo de canal.
            user = await uow.users.add(User(name=display_name or "Usuário"))
            org = await self._create_personal_org(uow, user, display_name)
            await uow.users.add_channel_identity(
                ChannelIdentity(user_id=user.id, channel=channel, external_id=external_id)
            )
            await uow.commit()
            return UserContext(user.id, org.id, display_name)

    @staticmethod
    async def _create_personal_org(
        uow: UnitOfWork, user: User, display_name: str
    ) -> Organization:
        org = await uow.organizations.add(
            Organization(name=f"{display_name or 'Pessoal'} (pessoal)")
        )
        await uow.memberships.add(
            Membership(org_id=org.id, user_id=user.id, role=Role.OWNER)
        )
        return org
