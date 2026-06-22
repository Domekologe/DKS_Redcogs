"""Laufzeit-Kontext, der jedem Widget-/Panel-/Page-Handler übergeben wird."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import discord
    from redbot.core.bot import Red


@dataclass
class DashboardContext:
    """Sicherer Kontext für einen einzelnen Dashboard-Aufruf.

    Wird vom Gateway erzeugt, nachdem die Identität (Discord-User) und die Rechte
    serverseitig validiert wurden. Handler dürfen sich darauf verlassen, dass der
    Zugriff bereits autorisiert ist.
    """

    bot: "Red"
    user: "discord.User"
    guild: Optional["discord.Guild"] = None
    member: Optional["discord.Member"] = None
    locale: str = "en-US"
    # rohe, vom BFF gelieferte Request-Parameter (bereits typvalidiert)
    params: Optional[dict] = None

    @property
    def is_guild_context(self) -> bool:
        return self.guild is not None
