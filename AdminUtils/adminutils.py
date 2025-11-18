import discord
import asyncio
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
            # Slash/Hybrid via Interaction -> immer ephemeral
            await ctx.reply(content, ephemeral=True, **kwargs)
        else:
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
        # 0) Sofort defer für Slash/Hybrid, damit nichts „hängt“
        deferred = False
        if getattr(ctx, "interaction", None) is not None:
            try:
                await ctx.interaction.response.defer(ephemeral=True, thinking=True)
                deferred = True
            except discord.InteractionResponded:
                pass  # schon deferred

        # 1) Ausnahme-IDs sammeln
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
                    # Versuche mehrere sinnvolle Matching-Varianten
                    u_lower = u.lower()

                    # 1) Display-Name exakte Übereinstimmung
                    m = discord.utils.find(lambda m: m.display_name.lower() == u_lower, ctx.guild.members)
                    if m:
                        uid = m.id
                    else:
                        # 2) Username exakte Übereinstimmung
                        m = discord.utils.find(lambda m: m.name.lower() == u_lower, ctx.guild.members)
                        if m:
                            uid = m.id
                        else:
                            # 3) Display-Name contains (fuzzy)
                            m = discord.utils.find(lambda m: u_lower in m.display_name.lower(), ctx.guild.members)
                            if m:
                                uid = m.id
                            else:
                                # 4) Username contains (fuzzy)
                                m = discord.utils.find(lambda m: u_lower in m.name.lower(), ctx.guild.members)
                                if m:
                                    uid = m.id

                if uid:
                    except_ids.append(uid)

        def _check(m: discord.Message) -> bool:
            if m.pinned:
                return False
            if m.author.id in except_ids:
                return False
            return True

        total_target = amount
        total_deleted = 0
        progress_msg = None

        async def update_progress():
            nonlocal progress_msg
            text = f"🧹 Lösche… {total_deleted}/{total_target} erledigt."
            if getattr(ctx, "interaction", None) is not None:
                # Bei Hybrid/Slash: Folge-Nachricht (ephemeral) oder editieren
                if progress_msg is None:
                    progress_msg = await ctx.send(text)  # wird als Followup gesendet
                else:
                    try:
                        await progress_msg.edit(content=text)
                    except discord.HTTPException:
                        pass
            else:
                # Bei Prefix: tippen anzeigen, nicht spammen
                await ctx.typing()

        await update_progress()

        # 2) Schneller Bulk-Pass (nur <14 Tage)
        try:
            recent_deleted = await ctx.channel.purge(
                limit=amount,
                check=_check,
                bulk=True
            )
        except discord.Forbidden:
            return await self._reply(ctx, "❌ Keine Berechtigung zum Löschen.")
        except discord.HTTPException:
            # Fallback: wenn purge scheitert, einfach weiter mit Einzel-Löschung
            recent_deleted = []

        total_deleted += len(recent_deleted)
        await update_progress()

        # 3) Falls noch nicht genug: ältere Nachrichten einzeln löschen
        remaining = total_target - total_deleted
        if remaining > 0:
            # Wir iterieren die letzten `amount * 3` Nachrichten (Heuristik),
            # um genug ältere Kandidaten zu finden.
            scanned = 0
            async for msg in ctx.channel.history(limit=amount * 3, oldest_first=False):
                if scanned >= amount:
                    break
                scanned += 1

                if not _check(msg):
                    continue

                # Alles, was purge NICHT erwischt (>=14 Tage), einzeln löschen
                too_old = (discord.utils.utcnow() - msg.created_at) >= timedelta(days=14)
                if too_old:
                    try:
                        await msg.delete()
                        total_deleted += 1
                        remaining -= 1
                    except discord.HTTPException:
                        pass

                    # Event-Loop freigeben & Fortschritt updaten
                    if total_deleted % 25 == 0:
                        await update_progress()
                        await asyncio.sleep(0)

                    if remaining <= 0:
                        break

        # 4) Abschluss
        if progress_msg is not None:
            try:
                await progress_msg.edit(content=f"✅ {total_deleted} Nachrichten gelöscht. Ausnahmen: {len(except_ids)}")
            except discord.HTTPException:
                pass

        # Falls wir nie eine Followup-Msg geschickt haben (Prefix oder kein progress_msg):
        if progress_msg is None:
            await self._reply(ctx, f"✅ {total_deleted} Nachrichten gelöscht. Ausnahmen: {len(except_ids)}")



    # ---- Fast Purge (instant Purge but only for the last 14 days) ----
    @commands.hybrid_command(
        name="purgefast",
        description="Löscht schnell Nachrichten der letzten 14 Tage (Bulk)."
    )
    @commands.bot_has_guild_permissions(manage_messages=True, read_message_history=True)
    @has_perms(manage_messages=True)
    @app_commands.describe(
        amount="Anzahl Nachrichten (1-500)",
        except_users="User, deren Nachrichten NICHT gelöscht werden sollen (Mentions oder IDs, getrennt durch Leerzeichen)."
    )
    async def purgefast(
        self,
        ctx: commands.Context,
        amount: app_commands.Range[int, 1, 500],
        *,
        except_users: Optional[str] = None
    ):
        # Slash/Hybrid sofort defer, damit nichts „hängt“
        if getattr(ctx, "interaction", None) is not None:
            try:
                await ctx.interaction.response.defer(ephemeral=True, thinking=True)
            except discord.InteractionResponded:
                pass

        # Ausnahme-IDs sammeln (gleiches Schema wie beim normalen purge)
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
                    # Versuche mehrere sinnvolle Matching-Varianten
                    u_lower = u.lower()

                    # 1) Display-Name exakte Übereinstimmung
                    m = discord.utils.find(lambda m: m.display_name.lower() == u_lower, ctx.guild.members)
                    if m:
                        uid = m.id
                    else:
                        # 2) Username exakte Übereinstimmung
                        m = discord.utils.find(lambda m: m.name.lower() == u_lower, ctx.guild.members)
                        if m:
                            uid = m.id
                        else:
                            # 3) Display-Name contains (fuzzy)
                            m = discord.utils.find(lambda m: u_lower in m.display_name.lower(), ctx.guild.members)
                            if m:
                                uid = m.id
                            else:
                                # 4) Username contains (fuzzy)
                                m = discord.utils.find(lambda m: u_lower in m.name.lower(), ctx.guild.members)
                                if m:
                                    uid = m.id

                if uid:
                    except_ids.append(uid)

        def _check(m: discord.Message) -> bool:
            if m.pinned:
                return False
            if m.author.id in except_ids:
                return False
            # WICHTIG: Bulk löscht nur Nachrichten <14 Tage – ältere werden von Discord ignoriert.
            return True

        try:
            deleted = await ctx.channel.purge(
                limit=amount,
                check=_check,
                bulk=True  # -> sehr schnell (aber nur ≤ 14 Tage)
            )
        except discord.Forbidden:
            return await self._reply(ctx, "❌ Keine Berechtigung zum Löschen.")
        except discord.HTTPException as e:
            return await self._reply(ctx, f"❌ HTTP-Fehler beim Löschen: {e}")

        await self._reply(
            ctx,
            f"✅ {len(deleted)} Nachrichten (≤14 Tage) gelöscht. Ausnahmen: {len(except_ids)}"
        )
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
        
        
        
    # ---- MOVE MEMBER ALL ----
    @commands.hybrid_command(
        name="move-memberall",
        description="Verschiebe alle Mitglieder aus einem VoiceChannel in einen anderen."
    )
    @commands.bot_has_guild_permissions(move_members=True)
    @has_perms(move_members=True)
    @app_commands.describe(
        source_channel="VoiceChannel aus dem verschoben werden soll",
        dest_channel="VoiceChannel in den verschoben werden soll"
    )
    async def move_memberall(
        self,
        ctx: commands.Context,
        source_channel: discord.VoiceChannel,
        dest_channel: discord.VoiceChannel
    ):
        if not ctx.interaction:
            return await self._reply(ctx, "❌ Dieses Kommando nur als Slash möglich.")

        # sofort defer -> Discord zufrieden
        await ctx.interaction.response.defer(ephemeral=True, thinking=True)

        moved, failed = [], []
        for member in source_channel.members:
            try:
                await member.move_to(dest_channel)
                moved.append(member.display_name)
            except Exception:
                failed.append(member.display_name)

        msg = f"✅ Verschoben: {', '.join(moved)}" if moved else "❌ Niemand verschoben."
        if failed:
            msg += f"\n⚠️ Fehlgeschlagen: {', '.join(failed)}"

        await ctx.interaction.followup.send(msg, ephemeral=True)


    # ---- MOVE MEMBER (Select Menü + Bestätigung) ----
    @commands.hybrid_command(
        name="move-member",
        description="Verschiebe ausgewählte Mitglieder aus einem VoiceChannel in einen anderen."
    )
    @commands.bot_has_guild_permissions(move_members=True)
    @has_perms(move_members=True)
    @app_commands.describe(
        source_channel="VoiceChannel aus dem verschoben werden soll",
        dest_channel="VoiceChannel in den verschoben werden soll"
    )
    async def move_member(
        self,
        ctx: commands.Context,
        source_channel: discord.VoiceChannel,
        dest_channel: discord.VoiceChannel
    ):
        if not ctx.interaction:
            return await self._reply(ctx, "❌ Dieses Kommando nur als Slash möglich.")

        members = source_channel.members
        if not members:
            await ctx.interaction.response.defer(ephemeral=True, thinking=True)
            return await ctx.interaction.followup.send("❌ Im Quellchannel sind keine Mitglieder.", ephemeral=True)

        # sofort defer
        await ctx.interaction.response.defer(ephemeral=True, thinking=True)

        # Optionen (max. 25 wegen Discord-Limit)
        options = [
            discord.SelectOption(label=m.display_name, value=str(m.id))
            for m in members[:25]
        ]

        class MemberSelect(discord.ui.View):
            def __init__(self, ctx, options, timeout=60):
                super().__init__(timeout=timeout)
                self.ctx = ctx
                self.selected: list[int] = []
                self.confirmed = False

                # Menü direkt hier hinzufügen (das reicht!)
                self.select_menu = discord.ui.Select(
                    placeholder="Wähle Mitglieder zum Verschieben",
                    options=options,
                    min_values=1,
                    max_values=len(options),
                )
                self.select_menu.callback = self.select_callback
                self.add_item(self.select_menu)

            async def select_callback(self, interaction: discord.Interaction):
                if interaction.user.id != self.ctx.author.id:
                    return await interaction.response.send_message("❌ Nicht dein Kommando.", ephemeral=True)
                self.selected = [int(v) for v in self.select_menu.values]
                await interaction.response.send_message("✅ Auswahl gespeichert. Bitte 'Bestätigen' klicken.", ephemeral=True)

            @discord.ui.button(label="Bestätigen", style=discord.ButtonStyle.success)
            async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != self.ctx.author.id:
                    return await interaction.response.send_message("❌ Nicht für dich.", ephemeral=True)
                if not self.selected:
                    return await interaction.response.send_message("❌ Keine Auswahl getroffen.", ephemeral=True)
                self.confirmed = True
                self.stop()
                for child in self.children:
                    child.disabled = True
                # Bei ephemeral Messages kein edit möglich, also einfach nur stoppen
                try:
                    await interaction.message.edit(view=self)
                except discord.NotFound:
                    pass

                await interaction.response.send_message("✅ Bestätigt, verschiebe Mitglieder…", ephemeral=True)

            @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.danger)
            async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != self.ctx.author.id:
                    return await interaction.response.send_message("❌ Nicht für dich.", ephemeral=True)
                self.confirmed = False
                self.stop()
                for child in self.children:
                    child.disabled = True
                # Bei ephemeral Messages kein edit möglich, also einfach nur stoppen
                try:
                    await interaction.message.edit(view=self)
                except discord.NotFound:
                    pass

                await interaction.response.send_message("❌ Abgebrochen.", ephemeral=True)


        # View über followup schicken (da wir schon deferred haben)
        view = MemberSelect(ctx, options)
        await ctx.interaction.followup.send(
            "➡️ Wähle die Mitglieder und bestätige oder breche ab:",
            view=view,
            ephemeral=True
        )

        # auf Ergebnis warten
        await view.wait()

        if not view.confirmed or not view.selected:
            return  # Abbruch oder Timeout → schon ephemer gemeldet

        moved, failed = [], []
        for mid in view.selected:
            member = ctx.guild.get_member(mid)
            if member and member.voice and member.voice.channel.id == source_channel.id:
                try:
                    await member.move_to(dest_channel)
                    moved.append(member.display_name)
                except Exception:
                    failed.append(member.display_name)

        msg = f"✅ Verschoben: {', '.join(moved)}" if moved else "❌ Niemand verschoben."
        if failed:
            msg += f"\n⚠️ Fehlgeschlagen: {', '.join(failed)}"

        await ctx.interaction.followup.send(msg, ephemeral=True)
