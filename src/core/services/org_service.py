"""Serviço de organização/identidade — neutro de canal.

Resolve a identidade de um canal para o usuário e a **organização ativa** internos,
e cuida do onboarding de equipe (criar empresa, entrar por código, papéis,
categorias e centros de custo definidos pela org).

Auto-provisiona uma org pessoal na primeira interação, para o uso individual
continuar funcionando; a partir daí o usuário pode criar/entrar em empresas e
alternar qual é a org ativa (onde seus gastos são lançados).
"""
import secrets
import string
from dataclasses import dataclass
from typing import Callable, Optional

from src.core.entities import (
    Category,
    Channel,
    ChannelIdentity,
    CostCenter,
    Membership,
    Organization,
    Role,
    User,
)
from src.core.ports.repositories import UnitOfWork

_CODE_ALPHABET = string.ascii_uppercase + string.digits
_CODE_LEN = 6


@dataclass(frozen=True)
class UserContext:
    """Identidade interna resolvida, passada às operações de negócio.

    `org_id` é a organização **ativa** do usuário (onde os gastos são lançados).
    `channel` é por onde ele falou — usado para endereçar notificações push.
    """

    user_id: int
    org_id: int
    display_name: str
    channel: Channel


class OrgService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]):
        self._uow_factory = uow_factory

    # --- Identidade / org ativa ---------------------------------------------

    async def resolve_context(
        self, channel: Channel, external_id: str, display_name: str
    ) -> UserContext:
        """Encontra (ou cria) o usuário e devolve sua org ativa."""
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_channel_identity(channel, external_id)
            if user is not None:
                org_id = user.active_org_id
                if org_id is None:
                    # Estado legado/inesperado: usa a org mais antiga como ativa.
                    org = await uow.organizations.get_primary_for_user(user.id)
                    if org is None:
                        org = await self._create_org(uow, user.id, f"{display_name} (pessoal)", Role.OWNER)
                    await uow.users.set_active_org(user.id, org.id)
                    org_id = org.id
                    await uow.commit()
                return UserContext(user.id, org_id, display_name, channel)

            # Primeira interação: usuário + org pessoal + vínculo de canal.
            user = await uow.users.add(User(name=display_name or "Usuário"))
            org = await self._create_org(uow, user.id, f"{display_name or 'Pessoal'} (pessoal)", Role.OWNER)
            await uow.users.set_active_org(user.id, org.id)
            await uow.users.add_channel_identity(
                ChannelIdentity(user_id=user.id, channel=channel, external_id=external_id)
            )
            await uow.commit()
            return UserContext(user.id, org.id, display_name, channel)

    # --- Aprovadores (para notificação push) --------------------------------

    async def approver_external_ids(
        self, org_id: int, channel: Channel, exclude_user_id: Optional[int] = None
    ) -> list[str]:
        """external_ids dos aprovadores (admin/owner) da org no canal dado.

        Usado para avisar quem pode aprovar que há gastos na fila. Quem não usa
        o canal (sem `ChannelIdentity`) simplesmente não recebe push.
        """
        async with self._uow_factory() as uow:
            memberships = await uow.memberships.list_for_org(org_id)
            ids: list[str] = []
            for mb in memberships:
                if mb.role not in (Role.OWNER, Role.ADMIN) or mb.user_id == exclude_user_id:
                    continue
                identity = await uow.users.get_channel_identity(mb.user_id, channel)
                if identity is not None:
                    ids.append(identity.external_id)
            return ids

    async def external_id_for(
        self, user_id: int, channel: Channel
    ) -> Optional[str]:
        """external_id de um usuário no canal (para avisar o autor da decisão)."""
        async with self._uow_factory() as uow:
            identity = await uow.users.get_channel_identity(user_id, channel)
            return identity.external_id if identity else None

    async def user_name(self, user_id: int) -> Optional[str]:
        """Nome de exibição de um usuário (para rotular gastos na fila de aprovação)."""
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            return user.name if user else None

    # --- Onboarding de equipe ------------------------------------------------

    async def create_organization(self, ctx: UserContext, name: str) -> Organization:
        """Cria uma empresa, torna o criador admin, gera código e a deixa ativa."""
        async with self._uow_factory() as uow:
            code = await self._unique_join_code(uow)
            org = await uow.organizations.add(Organization(name=name, join_code=code))
            await uow.memberships.add(
                Membership(org_id=org.id, user_id=ctx.user_id, role=Role.ADMIN)
            )
            await uow.users.set_active_org(ctx.user_id, org.id)
            await uow.commit()
            return org

    async def join_organization(self, ctx: UserContext, code: str) -> Optional[Organization]:
        """Entra numa empresa pelo código, como membro, e a deixa ativa.

        Retorna None se o código não existir. Idempotente se já for membro.
        """
        async with self._uow_factory() as uow:
            org = await uow.organizations.get_by_join_code(code.strip().upper())
            if org is None:
                return None
            existing = await uow.memberships.get(org.id, ctx.user_id)
            if existing is None:
                await uow.memberships.add(
                    Membership(org_id=org.id, user_id=ctx.user_id, role=Role.MEMBER)
                )
            await uow.users.set_active_org(ctx.user_id, org.id)
            await uow.commit()
            return org

    async def switch_active(self, ctx: UserContext, org_id: int) -> bool:
        """Alterna a org ativa, desde que o usuário seja membro dela."""
        async with self._uow_factory() as uow:
            if await uow.memberships.get(org_id, ctx.user_id) is None:
                return False
            await uow.users.set_active_org(ctx.user_id, org_id)
            await uow.commit()
            return True

    async def list_organizations(self, ctx: UserContext) -> list[tuple[Organization, Role]]:
        async with self._uow_factory() as uow:
            orgs = await uow.organizations.list_for_user(ctx.user_id)
            result: list[tuple[Organization, Role]] = []
            for org in orgs:
                membership = await uow.memberships.get(org.id, ctx.user_id)
                result.append((org, membership.role if membership else Role.MEMBER))
            return result

    async def get_role(self, ctx: UserContext) -> Optional[Role]:
        async with self._uow_factory() as uow:
            membership = await uow.memberships.get(ctx.org_id, ctx.user_id)
            return membership.role if membership else None

    async def is_admin(self, ctx: UserContext) -> bool:
        return await self.get_role(ctx) in (Role.OWNER, Role.ADMIN)

    # --- Categorias / centros de custo (definidos pela org) -----------------

    async def add_category(self, ctx: UserContext, name: str) -> Optional[Category]:
        """Adiciona categoria à org ativa. Só admin/owner. None se sem permissão.

        Idempotente: se a categoria já existir, devolve a existente (sem violar
        a unicidade nem quebrar o fluxo do admin).
        """
        if not await self.is_admin(ctx):
            return None
        name = name.strip()
        async with self._uow_factory() as uow:
            existing = await uow.categories.list_for_org(ctx.org_id)
            match = next((c for c in existing if c.name.lower() == name.lower()), None)
            if match is not None:
                return match
            category = await uow.categories.add(Category(org_id=ctx.org_id, name=name))
            await uow.commit()
            return category

    async def list_categories(self, ctx: UserContext) -> list[str]:
        async with self._uow_factory() as uow:
            return [c.name for c in await uow.categories.list_for_org(ctx.org_id)]

    async def add_cost_center(self, ctx: UserContext, name: str) -> Optional[CostCenter]:
        if not await self.is_admin(ctx):
            return None
        name = name.strip()
        async with self._uow_factory() as uow:
            existing = await uow.cost_centers.list_for_org(ctx.org_id)
            match = next((c for c in existing if c.name.lower() == name.lower()), None)
            if match is not None:
                return match
            cc = await uow.cost_centers.add(CostCenter(org_id=ctx.org_id, name=name))
            await uow.commit()
            return cc

    async def list_cost_centers(self, ctx: UserContext) -> list[str]:
        async with self._uow_factory() as uow:
            return [c.name for c in await uow.cost_centers.list_for_org(ctx.org_id)]

    # --- Helpers -------------------------------------------------------------

    @staticmethod
    async def _create_org(
        uow: UnitOfWork, user_id: int, name: str, role: Role
    ) -> Organization:
        org = await uow.organizations.add(Organization(name=name))
        await uow.memberships.add(Membership(org_id=org.id, user_id=user_id, role=role))
        return org

    @staticmethod
    async def _unique_join_code(uow: UnitOfWork) -> str:
        for _ in range(10):
            code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))
            if await uow.organizations.get_by_join_code(code) is None:
                return code
        raise RuntimeError("Não foi possível gerar um código de convite único")
