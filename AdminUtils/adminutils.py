import discord
from discord import app_commands
from datetime import timedelta
from typing import Optional, List
from redbot.core import commands


def has_perms(**perms):
    return commands.has_permissions(**perms)


class AdminUtils(commands.Cog):
    """Admin-Utilities als Slash/Hybrid-Commands"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # kleiner Helper, damit ephemeral nur bei Slash benutzt wird
    async def _reply(self, ctx: commands.Context, content: str, **kwargs):
        if getattr(ctx, "interaction", None) is not None:
            # Slash/Hybrid via Interaction -> ephemeral erlaubt
            await ctx.reply(content, ephemeral=True, **kwargs)
        else:
            # Prefix -> ohne ephemeral senden
            # (reply() statt send(), damit Thread/Reply-Verhalten erhalten bleibt)
            await ctx.reply(content, **{k: v for k, v in kwargs.items() if k != "ephemeral"})

    # ---- KICK ----
    @commands.hybrid_command(name="kick", description="Kicke ein Mitglied.")
    @commands.bot_has_guild_permissions(kick_members=True)
    @has_perms(kick_members=True)
    @app_commands.describe(member="Mitglied zum Kicken", reason="Grund")
    async def kick(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: Optional[str] = None
    ):
        await member.kick(reason=reason or f"Kicked by {ctx.author}")
        await self._reply(ctx, f"✅ {member.mention} wurde gekickt. Grund: {reason or '—'}")

    # ---- BAN ----
    @commands.hybrid_command(name="ban", description="Bannt ein Mitglied.")
    @commands.bot_has_guild_permissions(ban_members=True)
    @has_perms(ban_members=True)
    @app_commands.describe(
        member="Mitglied zum Bannen",
        reason="Grund",
        delete_message_days="Lösche Nachrichten der letzten X Tage (0-7)"
    )
    async def ban(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: Optional[str] = None,
        delete_message_days: app_commands.Range[int, 0, 7] = 0
    ):
        # discord.py 2.x: delete_message_seconds ist korrekt
        await ctx.guild.ban(
            member,
            reason=reason or f"Banned by {ctx.author}",
            delete_message_seconds=delete_message_days * 24 * 3600
        )
        await self._reply(
            ctx,
            f"✅ {member.mention} wurde gebannt. Grund: {reason or '—'} | "
            f"Nachrichten: {delete_message_days} Tage"
        )

    # ---- TIMEOUT ----
    @commands.hybrid_command(name="timeout", description="Timeout für ein Mitglied (in Minuten).")
    @commands.bot_has_guild_permissions(moderate_members=True)
    @has_perms(moderate_members=True)
    @app_commands.describe(
        member="Mitglied",
        minutes="Dauer in Minuten",
        reason="Grund"
    )
    async def timeout(
        self,
        ctx: commands.Context,
        member: discord.Member,
        minutes: app_commands.Range[int, 1, 40320],  # bis 28 Tage
        *,
        reason: Optional[str] = None
    ):
        until = discord.utils.utcnow() + timedelta(minutes=minutes)
        await member.timeout(until, reason=reason or f"Timeout by {ctx.author}")
        await self._reply(ctx, f"✅ {member.mention} ist {minutes} Minuten im Timeout. Grund: {reason or '—'}")

    # ---- PURGE (mit Ausnahmen) ----
    @commands.hybrid_command(name="purge", description="Lösche X Nachrichten, optional mit Ausnahmen.")
    @commands.bot_has_guild_permissions(manage_messages=True, read_message_history=True)
    @has_perms(manage_messages=True)
    @app_commands.describe(
        amount="Anzahl Nachrichten (1-500)",
        except_users="User, deren Nachrichten nicht gelöscht werden sollen (Mentions oder IDs, getrennt durch Leerzeichen)."
    )
    async def purge(
        self,
        ctx: commands.Context,
        amount: app_commands.Range[int, 1, 500],
        *,
        except_users: Optional[str] = None
    ):
        # Liste von IDs aus Mentions/Namen bauen
        except_ids: List[int] = []
        if except_users:
            for u in except_users.split():
                uid = None
                if u.startswith("<@") and u.endswith(">"):
                    try:
                        uid = int(u.strip("<@!>"))
                    except ValueError:
                        uid = None
                elif u.isdigit():
                    uid = int(u)
                else:
                    m = discord.utils.find(lambda m: str(m).lower() == u.lower(), ctx.guild.members)
                    if m:
                        uid = m.id
                if uid:
                    except_ids.append(uid)

        deleted = 0
        async for msg in ctx.channel.history(limit=amount, oldest_first=False):
            if msg.pinned:
                continue
            if msg.author.id in except_ids:
                continue
            try:
                await msg.delete()
                deleted += 1
            except discord.HTTPException:
                pass

        await self._reply(ctx, f"✅ {deleted} Nachrichten gelöscht. Ausnahmen: {len(except_ids)}")

    # ---- MESSAGE MOVE (kopieren + optional löschen) ----
    @commands.hybrid_command(
        name="messagemove",
        description="Kopiert eine Nachricht in einen Ziel-Channel und löscht das Original (optional)."
    )
    @commands.bot_has_guild_permissions(manage_messages=True, read_message_history=True)
    @has_perms(manage_messages=True)
    @app_commands.describe(
        source_channel="Quell-Channel",
        message_id="ID der Nachricht im Quell-Channel",
        destination="Ziel-Channel",
        delete_original="Originalnachricht nach dem Kopieren löschen?"
    )
    async def messagemove(
        self,
        ctx: commands.Context,
        source_channel: discord.TextChannel,
        message_id: int,
        destination: discord.TextChannel,
        delete_original: Optional[bool] = True
    ):
        try:
            msg = await source_channel.fetch_message(message_id)
        except discord.NotFound:
            return await self._reply(ctx, "❌ Nachricht nicht gefunden.")
        except discord.Forbidden:
            return await self._reply(ctx, "❌ Keine Berechtigung, die Nachricht zu lesen.")

        content = (
            f"**Nachricht verschoben aus** {source_channel.mention} "
            f"von {msg.author.mention}:\n{msg.content or ''}"
        )

        files = []
        for a in msg.attachments:
            try:
                files.append(await a.to_file())
            except discord.HTTPException:
                pass

        await destination.send(content=content, files=files if files else None)

        if delete_original:
            try:
                await msg.delete()
            except discord.HTTPException:
                pass

        await self._reply(
            ctx,
            f"✅ Nachricht nach {destination.mention} kopiert"
            f"{' und Original gelöscht' if delete_original else ''}."
        )
