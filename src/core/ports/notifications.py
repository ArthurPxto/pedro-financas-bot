"""Port de notificação proativa (push).

Diferente do `ChannelResponder` (que responde dentro de uma conversa em curso),
aqui o núcleo precisa **iniciar** o contato — avisar um aprovador que há gastos
na fila, ou avisar o autor que seu gasto foi decidido. O destinatário é
identificado pelo `external_id` do canal (ex.: chat id do Telegram).

O adapter de canal implementa este port. O núcleo nunca conhece chat ids nem
tokens — só o `external_id` que já guarda em `ChannelIdentity`.
"""
from abc import ABC, abstractmethod

from src.core.entities import Channel


class Notifier(ABC):
    @abstractmethod
    async def notify(self, channel: Channel, external_id: str, text: str) -> bool:
        """Envia uma mensagem proativa a um usuário do canal.

        Retorna False se não foi possível entregar (ex.: usuário nunca iniciou
        conversa com o bot, ou bloqueou) — o fluxo de negócio não deve quebrar
        por causa de uma notificação não entregue.
        """
