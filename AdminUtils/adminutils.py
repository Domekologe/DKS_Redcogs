import discord
import asyncio
from discord import app_commands
from datetime import timedelta
from typing import Any, Dict, Optional, List
from redbot.core import commands, Config
from typing import Union
import re
from discord.app_commands import Transform

from .dks_dashboard import (
    dashboard_widget, dashboard_panel, WidgetData,
    PanelSchema, Field, SubmitResult,
    register_dashboard, unregister_dashboard,
    L, tr,
)


def has_perms(**perms):
    return commands.has_permissions(**perms)

ChannelOrThread = Union[discord.TextChannel, discord.Thread]

_MESSAGE_ID_RE = re.compile(r"(\d{15,25})$")

def _parse_message_id(raw: str) -> Optional[int]:
    raw = raw.strip()
    m = _MESSAGE_ID_RE.search(raw)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None

try:
    from dks_dashboard.rpc.third_parties import dashboard_page as _dashboard_page  # type: ignore
except Exception:
    try:
        from dashboard.rpc.third_parties import dashboard_page as _dashboard_page  # type: ignore
    except Exception:
        def _dashboard_page(*args: Any, **kwargs: Any):  # type: ignore
            def decorator(func: Any) -> Any:
                func.__dashboard_decorator_params__ = (args, kwargs)
                return func
            return decorator

class AdminUtils(commands.Cog):
    """Admin utilities as slash/hybrid commands"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=708921553001, force_registration=True)
        self.config.register_guild(
            templates={
                "kick_success": "✅ {member} wurde gekickt. Grund: {reason}",
                "ban_success": "✅ {member} wurde gebannt. Grund: {reason} | Nachrichten: {delete_days} Tage",
                "timeout_success": "✅ {member} ist {minutes} Minuten im Timeout. Grund: {reason}",
                "purge_success": "✅ {deleted} Nachrichten gelöscht. Ausnahmen: {exceptions}",
            }
        )
        self._dashboard_attached = False

    async def cog_load(self) -> None:
        # Register DKS WebDashboard first & independently (no-op if not loaded)
        register_dashboard(self)
        dashboard = self.bot.get_cog("DKS-Dashboard") or self.bot.get_cog("Dashboard")
        if dashboard is None:
            return
        try:
            dashboard.rpc.third_parties_handler.add_third_party(self, overwrite=True)  # type: ignore[attr-defined]
            self._dashboard_attached = True
        except Exception:
            self._dashboard_attached = False

    def cog_unload(self) -> None:
        unregister_dashboard(self)

    @dashboard_widget("adminutils_templates", L("AdminUtils Templates", "AdminUtils Templates"), size="sm", permission="guild_member")
    async def adminutils_templates_widget(self, ctx):
        try:
            templates = await self.config.guild(ctx.guild).templates()
            return WidgetData.kpi(value=len(templates), label="AdminUtils Templates")
        except Exception:
            return WidgetData.kpi(value="–", label="AdminUtils Templates")

    # --- Guild panel: customize moderation messages ------------------- #
    @dashboard_panel(
        "templates", L("Moderations-Nachrichten", "Moderation Messages"), mount="guild_settings", permission="guild_admin"
    )
    async def adminutils_templates_panel(self, ctx):
        t = await self.config.guild(ctx.guild).templates()
        member = {"token": "{member}", "desc": "Member"}
        reason = {"token": "{reason}", "desc": "Reason"}
        return PanelSchema(
            description=tr(ctx, "Erfolgsmeldungen für Kick/Ban/Timeout/Purge.", "Success messages for Kick/Ban/Timeout/Purge."),
            fields=[
                Field.textarea("kick_success", "Kick", value=t.get("kick_success", ""),
                               max_length=500, variables=[member, reason]),
                Field.textarea("ban_success", "Ban", value=t.get("ban_success", ""),
                               max_length=500,
                               variables=[member, reason, {"token": "{delete_days}", "desc": "Days to delete"}]),
                Field.textarea("timeout_success", "Timeout", value=t.get("timeout_success", ""),
                               max_length=500,
                               variables=[member, reason, {"token": "{minutes}", "desc": "Minutes"}]),
                Field.textarea("purge_success", "Purge", value=t.get("purge_success", ""),
                               max_length=500,
                               variables=[{"token": "{deleted}", "desc": "Deleted"},
                                          {"token": "{exceptions}", "desc": "Exceptions"}]),
            ],
        )

    @adminutils_templates_panel.on_submit
    async def _save_adminutils_templates(self, ctx, data):
        cur = await self.config.guild(ctx.guild).templates()
        for k in ("kick_success", "ban_success", "timeout_success", "purge_success"):
            if k in data:
                cur[k] = str(data[k])[:500]
        await self.config.guild(ctx.guild).templates.set(cur)
        return SubmitResult.ok("Vorlagen gespeichert.")

    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
        if self._dashboard_attached:
            return
        try:
            dashboard_cog.rpc.third_parties_handler.add_third_party(self, overwrite=True)  # type: ignore[attr-defined]
            self._dashboard_attached = True
        except Exception:
            self._dashboard_attached = False

    @commands.Cog.listener()
    async def on_cog_add(self, cog: commands.Cog) -> None:
        # Compatibility path for Dashboard variants that do not dispatch `dashboard_cog_add`.
        if self._dashboard_attached:
            return
        if cog.qualified_name not in {"Dashboard", "DKS-Dashboard"}:
            return
        try:
            cog.rpc.third_parties_handler.add_third_party(self, overwrite=True)  # type: ignore[attr-defined]
            self._dashboard_attached = True
        except Exception:
            self._dashboard_attached = False

    # small helper so ephemeral is only used for slash
    async def _reply(self, ctx: commands.Context, content: str, **kwargs):
        if getattr(ctx, "interaction", None) is not None:
            # Slash/Hybrid via Interaction -> always ephemeral
            await ctx.reply(content, ephemeral=True, **kwargs)
        else:
            await ctx.reply(content, **{k: v for k, v in kwargs.items() if k != "ephemeral"})

    # ---- KICK ----
    @commands.hybrid_command(name="kick", description="Kick a member.")
    @commands.bot_has_guild_permissions(kick_members=True)
    @has_perms(kick_members=True)
    @app_commands.describe(member="Member to kick", reason="Reason")
    async def kick(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: Optional[str] = None
    ):
        await member.kick(reason=reason or f"Kicked by {ctx.author}")
        templates = await self.config.guild(ctx.guild).templates()
        await self._reply(
            ctx,
            templates["kick_success"].format(member=member.mention, reason=reason or "—"),
        )

    # ---- BAN ----
    @commands.hybrid_command(name="ban", description="Ban a member.")
    @commands.bot_has_guild_permissions(ban_members=True)
    @has_perms(ban_members=True)
    @app_commands.describe(
        member="Member to ban",
        reason="Reason",
        delete_message_days="Delete messages from the last X days (0-7)"
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
        templates = await self.config.guild(ctx.guild).templates()
        await self._reply(
            ctx,
            templates["ban_success"].format(
                member=member.mention,
                reason=reason or "—",
                delete_days=delete_message_days,
            ),
        )

    # ---- TIMEOUT ----
    @commands.hybrid_command(name="timeout", description="Time out a member (in minutes).")
    @commands.bot_has_guild_permissions(moderate_members=True)
    @has_perms(moderate_members=True)
    @app_commands.describe(
        member="Member",
        minutes="Duration in minutes",
        reason="Reason"
    )
    async def timeout(
        self,
        ctx: commands.Context,
        member: discord.Member,
        minutes: app_commands.Range[int, 1, 40320],  # up to 28 days
        *,
        reason: Optional[str] = None
    ):
        until = discord.utils.utcnow() + timedelta(minutes=minutes)
        await member.timeout(until, reason=reason or f"Timeout by {ctx.author}")
        templates = await self.config.guild(ctx.guild).templates()
        await self._reply(
            ctx,
            templates["timeout_success"].format(
                member=member.mention,
                minutes=minutes,
                reason=reason or "—",
            ),
        )


    # ---- PURGE (with exceptions) ----
    @commands.hybrid_command(name="purge", description="Delete X messages, optionally with exceptions.")
    @commands.bot_has_guild_permissions(manage_messages=True, read_message_history=True)
    @has_perms(manage_messages=True)
    @app_commands.describe(
        amount="Number of messages (1-500)",
        except_users="Users whose messages should not be deleted (mentions or IDs, separated by spaces)."
    )
    async def purge(
        self,
        ctx: commands.Context,
        amount: app_commands.Range[int, 1, 500],
        *,
        except_users: Optional[str] = None
    ):
        # 0) Defer immediately for slash/hybrid so nothing "hangs"
        deferred = False
        if getattr(ctx, "interaction", None) is not None:
            try:
                await ctx.interaction.response.defer(ephemeral=True, thinking=True)
                deferred = True
            except discord.InteractionResponded:
                pass  # already deferred

        # 1) Collect exception IDs
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
                    # Try several sensible matching variants
                    u_lower = u.lower()

                    # 1) Display name exact match
                    m = discord.utils.find(lambda m: m.display_name.lower() == u_lower, ctx.guild.members)
                    if m:
                        uid = m.id
                    else:
                        # 2) Username exact match
                        m = discord.utils.find(lambda m: m.name.lower() == u_lower, ctx.guild.members)
                        if m:
                            uid = m.id
                        else:
                            # 3) Display name contains (fuzzy)
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
                # For hybrid/slash: follow-up message (ephemeral) or edit
                if progress_msg is None:
                    progress_msg = await ctx.send(text)  # sent as a followup
                else:
                    try:
                        await progress_msg.edit(content=text)
                    except discord.HTTPException:
                        pass
            else:
                # For prefix: show typing, don't spam
                await ctx.typing()

        await update_progress()

        # 2) Fast bulk pass (only <14 days)
        try:
            recent_deleted = await ctx.channel.purge(
                limit=amount,
                check=_check,
                bulk=True
            )
        except discord.Forbidden:
            return await self._reply(ctx, "❌ Keine Berechtigung zum Löschen.")
        except discord.HTTPException:
            # Fallback: if purge fails, just continue with single deletion
            recent_deleted = []

        total_deleted += len(recent_deleted)
        await update_progress()

        # 3) If not enough yet: delete older messages individually
        remaining = total_target - total_deleted
        if remaining > 0:
            # We iterate the last `amount * 3` messages (heuristic)
            # to find enough older candidates.
            scanned = 0
            async for msg in ctx.channel.history(limit=amount * 3, oldest_first=False):
                if scanned >= amount:
                    break
                scanned += 1

                if not _check(msg):
                    continue

                # Delete individually everything purge does NOT catch (>=14 days)
                too_old = (discord.utils.utcnow() - msg.created_at) >= timedelta(days=14)
                if too_old:
                    try:
                        await msg.delete()
                        total_deleted += 1
                        remaining -= 1
                    except discord.HTTPException:
                        pass

                    # Release the event loop & update progress
                    if total_deleted % 25 == 0:
                        await update_progress()
                        await asyncio.sleep(0)

                    if remaining <= 0:
                        break

        # 4) Completion
        if progress_msg is not None:
            try:
                await progress_msg.edit(content=f"✅ {total_deleted} Nachrichten gelöscht. Ausnahmen: {len(except_ids)}")
            except discord.HTTPException:
                pass

        # If we never sent a followup message (prefix or no progress_msg):
        if progress_msg is None:
            templates = await self.config.guild(ctx.guild).templates()
            await self._reply(
                ctx,
                templates["purge_success"].format(deleted=total_deleted, exceptions=len(except_ids)),
            )



    # ---- Fast Purge (instant Purge but only for the last 14 days) ----
    @commands.hybrid_command(
        name="purgefast",
        description="Quickly deletes messages from the last 14 days (bulk)."
    )
    @commands.bot_has_guild_permissions(manage_messages=True, read_message_history=True)
    @has_perms(manage_messages=True)
    @app_commands.describe(
        amount="Number of messages (1-500)",
        except_users="Users whose messages should NOT be deleted (mentions or IDs, separated by spaces)."
    )
    async def purgefast(
        self,
        ctx: commands.Context,
        amount: app_commands.Range[int, 1, 500],
        *,
        except_users: Optional[str] = None
    ):
        # Defer slash/hybrid immediately so nothing "hangs"
        if getattr(ctx, "interaction", None) is not None:
            try:
                await ctx.interaction.response.defer(ephemeral=True, thinking=True)
            except discord.InteractionResponded:
                pass

        # Collect exception IDs (same scheme as the normal purge)
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
                    # Try several sensible matching variants
                    u_lower = u.lower()

                    # 1) Display name exact match
                    m = discord.utils.find(lambda m: m.display_name.lower() == u_lower, ctx.guild.members)
                    if m:
                        uid = m.id
                    else:
                        # 2) Username exact match
                        m = discord.utils.find(lambda m: m.name.lower() == u_lower, ctx.guild.members)
                        if m:
                            uid = m.id
                        else:
                            # 3) Display name contains (fuzzy)
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
            # IMPORTANT: Bulk only deletes messages <14 days - older ones are ignored by Discord.
            return True

        try:
            deleted = await ctx.channel.purge(
                limit=amount,
                check=_check,
                bulk=True  # -> very fast (but only <= 14 days)
            )
        except discord.Forbidden:
            return await self._reply(ctx, "❌ Keine Berechtigung zum Löschen.")
        except discord.HTTPException as e:
            return await self._reply(ctx, f"❌ HTTP-Fehler beim Löschen: {e}")

        await self._reply(
            ctx,
            f"✅ {len(deleted)} Nachrichten (≤14 Tage) gelöscht. Ausnahmen: {len(except_ids)}"
        )
        
    # ---- MESSAGE MOVE (copy + optionally delete) ----
    @commands.hybrid_command(
        name="messagemove",
        description="Copies a message to a target channel or thread and optionally deletes the original."
    )
    @commands.bot_has_guild_permissions(manage_messages=True, read_message_history=True)
    @has_perms(manage_messages=True)
    @app_commands.describe(
        message="Message ID or message link",
        destination="Target channel or thread",
        delete_original="Delete the original message after copying?"
    )
    async def messagemove(
        self,
        ctx: commands.Context,
        message: str,
        destination: discord.TextChannel,
        delete_original: Optional[bool] = True
    ):
        mid = _parse_message_id(message)
        if mid is None:
            return await self._reply(ctx, "❌ Ungültige Message-ID oder Message-Link.")

        # Determine channel from message link (or fallback: current channel)
        channel = ctx.channel
        try:
            msg = await channel.fetch_message(mid)
        except discord.NotFound:
            return await self._reply(ctx, "❌ Nachricht nicht gefunden (Channel prüfen!).")
        except discord.Forbidden:
            return await self._reply(ctx, "❌ Keine Berechtigung, die Nachricht zu lesen.")

        content = (
            f"**Nachricht verschoben aus** {channel.mention} "
            f"von {msg.author.mention}:\n{msg.content or ''}"
        )

        files = []
        for a in msg.attachments:
            try:
                files.append(await a.to_file())
            except discord.HTTPException:
                pass

        try:
            await destination.send(content=content, files=files if files else None)
        except discord.Forbidden:
            return await self._reply(ctx, "❌ Keine Berechtigung im Ziel-Channel.")

        if delete_original:
            try:
                await msg.delete()
            except discord.Forbidden:
                return await self._reply(
                    ctx,
                    "⚠️ Nachricht kopiert, aber ich darf das Original nicht löschen."
                )

        await self._reply(
            ctx,
            f"✅ Nachricht nach {destination.mention} kopiert"
            f"{' und Original gelöscht' if delete_original else ''}."
        )



        
    # ---- MOVE MEMBER ALL ----
    @commands.hybrid_command(
        name="move-memberall",
        description="Move all members from one voice channel to another."
    )
    @commands.bot_has_guild_permissions(move_members=True)
    @has_perms(move_members=True)
    @app_commands.describe(
        source_channel="Voice channel to move members from",
        dest_channel="Voice channel to move members to"
    )
    async def move_memberall(
        self,
        ctx: commands.Context,
        source_channel: discord.VoiceChannel,
        dest_channel: discord.VoiceChannel
    ):
        if not ctx.interaction:
            return await self._reply(ctx, "❌ Dieses Kommando nur als Slash möglich.")

        # defer immediately -> Discord satisfied
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


    # ---- MOVE MEMBER (select menu + confirmation) ----
    @commands.hybrid_command(
        name="move-member",
        description="Move selected members from one voice channel to another."
    )
    @commands.bot_has_guild_permissions(move_members=True)
    @has_perms(move_members=True)
    @app_commands.describe(
        source_channel="Voice channel to move members from",
        dest_channel="Voice channel to move members to"
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

        # defer immediately
        await ctx.interaction.response.defer(ephemeral=True, thinking=True)

        # Options (max. 25 due to Discord limit)
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

                # Add the menu directly here (that's enough!)
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
                # No edit possible on ephemeral messages, so just stop
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
                # No edit possible on ephemeral messages, so just stop
                try:
                    await interaction.message.edit(view=self)
                except discord.NotFound:
                    pass

                await interaction.response.send_message("❌ Abgebrochen.", ephemeral=True)


        # Send the view via followup (since we already deferred)
        view = MemberSelect(ctx, options)
        await ctx.interaction.followup.send(
            "➡️ Wähle die Mitglieder und bestätige oder breche ab:",
            view=view,
            ephemeral=True
        )

        # wait for the result
        await view.wait()

        if not view.confirmed or not view.selected:
            return  # cancel or timeout -> already reported ephemerally

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


    async def _copy_role_channel_overwrites(
        self,
        guild: discord.Guild,
        source_role: discord.Role,
        dest_role: discord.Role,
    ) -> tuple[int, List[str], bool]:
        copied = 0
        failed: List[str] = []
        had_overwrites = False
        for channel in guild.channels:
            overwrite = channel.overwrites.get(source_role)
            if overwrite is None:
                continue
            had_overwrites = True
            try:
                await channel.set_permissions(dest_role, overwrite=overwrite)
                copied += 1
            except (discord.Forbidden, discord.HTTPException):
                failed.append(channel.mention)
        return copied, failed, had_overwrites

    # ---- COPY CHANNEL ROLE PERMISSIONS ----
    @app_commands.command(
        name="copy-channelrole",
        description="Copy a role's channel permissions to another role."
    )
    @commands.bot_has_guild_permissions(manage_roles=True)
    @has_perms(manage_roles=True)
    @app_commands.describe(
        channel="The channel whose permissions should be copied",
        source_role="Role to copy from",
        dest_role="Role to copy to"
    )
    async def copy_channelrole(
        self,
        interaction: discord.Interaction,
        channel: discord.abc.GuildChannel,
        source_role: discord.Role,
        dest_role: discord.Role
    ):
        await interaction.response.defer(ephemeral=True)

        overwrites = channel.overwrites.get(source_role)
        if overwrites is None:
            return await interaction.followup.send(
                f"❌ Die Rolle {source_role.mention} hat **keine spezifischen Overwrites** in {channel.mention}.",
                ephemeral=True
            )

        try:
            await channel.set_permissions(dest_role, overwrite=overwrites)
        except discord.Forbidden:
            return await interaction.followup.send(
                "❌ Ich habe nicht genügend Berechtigungen, um diese Permissions zu setzen.",
                ephemeral=True
            )
        except discord.HTTPException as e:
            return await interaction.followup.send(
                f"❌ Fehler von Discord: `{e}`",
                ephemeral=True
            )

        await interaction.followup.send(
            f"✅ Rechte von {source_role.mention} wurden für {channel.mention} → {dest_role.mention} kopiert.",
            ephemeral=True
        )

    # ---- COPY GUILD ROLE ----
    @app_commands.command(
        name="copy-role",
        description="Create a new role with all the server and channel permissions of an existing role."
    )
    @commands.bot_has_guild_permissions(manage_roles=True)
    @has_perms(manage_roles=True)
    @app_commands.describe(
        source_role="Role to copy the permissions from",
        target_role_name="Name of the new role"
    )
    async def copy_role(
        self,
        interaction: discord.Interaction,
        source_role: discord.Role,
        target_role_name: str,
    ):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if guild is None:
            return await interaction.followup.send("❌ Nur auf einem Server nutzbar.", ephemeral=True)

        name = target_role_name.strip()
        if not name or len(name) > 100:
            return await interaction.followup.send(
                "❌ Der Rollenname muss zwischen 1 und 100 Zeichen lang sein.",
                ephemeral=True
            )

        if discord.utils.get(guild.roles, name=name):
            return await interaction.followup.send(
                f"❌ Eine Rolle mit dem Namen `{name}` existiert bereits.",
                ephemeral=True
            )

        create_kwargs: Dict[str, Any] = {
            "name": name,
            "permissions": source_role.permissions,
            "colour": source_role.colour,
            "hoist": source_role.hoist,
            "mentionable": source_role.mentionable,
            "reason": f"copy-role from {source_role.name} by {interaction.user}",
        }
        if source_role.display_icon is not None:
            try:
                create_kwargs["display_icon"] = await source_role.display_icon.read()
            except (discord.HTTPException, discord.NotFound):
                pass

        try:
            new_role = await guild.create_role(**create_kwargs)
        except discord.Forbidden:
            return await interaction.followup.send(
                "❌ Ich habe nicht genügend Berechtigungen, um diese Rolle zu erstellen "
                "(Rolle des Bots muss über der Quellrolle liegen).",
                ephemeral=True
            )
        except discord.HTTPException as e:
            return await interaction.followup.send(
                f"❌ Fehler von Discord: `{e}`",
                ephemeral=True
            )

        copied_channels, failed_channels, had_channel_overwrites = (
            await self._copy_role_channel_overwrites(guild, source_role, new_role)
        )

        position_ok = True
        if new_role.position != source_role.position:
            try:
                await new_role.edit(
                    position=source_role.position,
                    reason=f"copy-role position from {source_role.name} by {interaction.user}",
                )
            except (discord.Forbidden, discord.HTTPException):
                position_ok = False

        msg = (
            f"✅ Rolle {new_role.mention} wurde mit den Rechten von {source_role.mention} erstellt."
        )
        if copied_channels:
            msg += f"\n📁 Channel-Rechte in **{copied_channels}** Channel(s) kopiert."
        elif not had_channel_overwrites:
            msg += "\nℹ️ Keine Channel-spezifischen Rechte zum Kopieren gefunden."
        if failed_channels:
            shown = ", ".join(failed_channels[:15])
            if len(failed_channels) > 15:
                shown += f" (+{len(failed_channels) - 15} weitere)"
            msg += f"\n⚠️ Channel-Rechte fehlgeschlagen: {shown}"
        if not position_ok:
            msg += "\n⚠️ Rollenposition konnte nicht übernommen werden."

        await interaction.followup.send(msg, ephemeral=True)

    @_dashboard_page(name=None, description="AdminUtils Dashboard")
    async def dashboard_home(self, **kwargs: Any) -> Dict[str, Any]:
        _ = kwargs
        source = """
<div style="padding: 12px;">
  <h2>AdminUtils</h2>
  <p>Dashboard integration is active.</p>
  <p>Use the page <b>adminutils</b> for guild-specific settings.</p>
</div>
"""
        return {
            "status": 0,
            "web_content": {
                "source": source,
                "standalone": True,
            },
        }

    @_dashboard_page(
        name="adminutils",
        description="Guild-side AdminUtils templates and quick settings.",
        methods=("GET", "POST"),
        context_ids=["user_id", "guild_id"],
        hidden=False,
    )
    async def dashboard_adminutils(
        self,
        user_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if user_id is None or guild_id is None:
            return {"status": 0, "error_code": 400, "message": "Missing context user_id/guild_id."}
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return {"status": 1, "message": "Guild not found."}
        member = guild.get_member(user_id)
        if member is None or not member.guild_permissions.manage_guild:
            if user_id not in self.bot.owner_ids:
                return {"status": 1, "message": "Not allowed."}

        templates = await self.config.guild(guild).templates()
        if method.upper() == "POST" and data:
            form = dict(data.get("form", {}))
            for key in list(templates.keys()):
                templates[key] = str(form.get(key, templates[key]))
            await self.config.guild(guild).templates.set(templates)
            return {
                "status": 0,
                "notifications": [{"message": "AdminUtils dashboard settings saved.", "category": "success"}],
                "redirect_url": kwargs.get("request_url"),
            }

        source = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
* {{ font-family: 'Inter', sans-serif; box-sizing: border-box; }}
.dks-dashboard .card {{ background: rgba(18, 23, 33, 0.6); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3); border-radius: 12px; padding: 24px; color: #e8eefc; transition: all 0.3s ease; }}
.dks-dashboard .card:hover {{ box-shadow: 0 12px 40px 0 rgba(0, 0, 0, 0.4); border-color: rgba(255, 255, 255, 0.12); }}
.dks-dashboard h2, .dks-dashboard h3 {{ color: #ffffff; font-weight: 600; margin-top: 0; margin-bottom: 16px; letter-spacing: -0.02em; }}
.dks-dashboard p {{ color: #a0aec0; font-size: 14px; line-height: 1.5; margin-top: 0; margin-bottom: 16px; }}
.dks-dashboard code {{ background: rgba(255, 255, 255, 0.1); padding: 4px 8px; border-radius: 6px; font-size: 13px; color: #63b3ed; font-family: monospace; }}
.dks-dashboard label {{ font-size: 13.5px; font-weight: 500; color: #cbd5e0; margin-bottom: 8px; display: inline-block; }}
.dks-dashboard input, .dks-dashboard textarea, .dks-dashboard select {{ width: 100%; padding: 12px 16px; border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.1); background: rgba(0, 0, 0, 0.25); color: #fff; font-size: 14px; transition: all 0.2s ease; margin-bottom: 16px; }}
.dks-dashboard input:focus, .dks-dashboard textarea:focus, .dks-dashboard select:focus {{ outline: none; border-color: #4299e1; box-shadow: 0 0 0 3px rgba(66, 153, 225, 0.25); background: rgba(0, 0, 0, 0.35); }}
.dks-dashboard button {{ padding: 12px 24px; border-radius: 8px; border: none; background: linear-gradient(135deg, #4299e1 0%, #3182ce 100%); color: #fff; font-weight: 600; cursor: pointer; transition: all 0.2s ease; box-shadow: 0 4px 6px rgba(50, 50, 93, 0.11), 0 1px 3px rgba(0, 0, 0, 0.08); font-size: 14px; }}
.dks-dashboard button:hover {{ transform: translateY(-1px); box-shadow: 0 7px 14px rgba(50, 50, 93, 0.15), 0 3px 6px rgba(0, 0, 0, 0.1); background: linear-gradient(135deg, #3182ce 0%, #2b6cb0 100%); }}
.dks-dashboard button:active {{ transform: translateY(1px); }}
</style>
<div class='dks-dashboard'>
<div class='card'>
<h2>AdminUtils - Guild Dashboard</h2>
<p><b>Variables:</b> <code>{{member}}</code> <code>{{reason}}</code> <code>{{minutes}}</code> <code>{{delete_days}}</code> <code>{{deleted}}</code> <code>{{exceptions}}</code></p>
<form method='post'>
<label>kick_success</label><textarea rows='2' name='kick_success'>{templates.get("kick_success","")}</textarea><br>
<label>ban_success</label><textarea rows='2' name='ban_success'>{templates.get("ban_success","")}</textarea><br>
<label>timeout_success</label><textarea rows='2' name='timeout_success'>{templates.get("timeout_success","")}</textarea><br>
<label>purge_success</label><textarea rows='2' name='purge_success'>{templates.get("purge_success","")}</textarea><br><br>
<button type='submit'>Save</button>
</form>
</div>
</div>
"""
        return {"status": 0, "web_content": {"source": source, "standalone": True}}