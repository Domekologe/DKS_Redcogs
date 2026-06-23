from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import html
import json
import traceback

import discord
from discord import app_commands
from redbot.core import Config, commands
from redbot.core.bot import Red

from .dks_dashboard import (
    dashboard_widget, dashboard_panel, dashboard_list, WidgetData,
    PanelSchema, Field, SubmitResult,
    register_dashboard, unregister_dashboard,
)

try:
    # Late-bound by Dashboard when registering third-party pages.
    from dks_dashboard.rpc.third_parties import dashboard_page as _dashboard_page  # type: ignore
except Exception:
    try:
        from dashboard.rpc.third_parties import dashboard_page as _dashboard_page  # type: ignore
    except Exception:

        def _dashboard_page(*args: Any, **kwargs: Any):  # type: ignore
            def decorator(func: Any) -> Any:
                # Dashboard detects this marker and wraps it with its own decorator.
                func.__dashboard_decorator_params__ = (args, kwargs)
                return func

            return decorator


DEFAULT_GUILD = {
    "notifications": {
        # "<channel_id>": {"enabled": true, "text": "..."}
    }
}


def _render_template(text: str, *, member: discord.Member, channel: discord.abc.GuildChannel) -> str:
    return (
        (text or "")
        .replace("<Username>", member.display_name)
        .replace("<Channelname>", getattr(channel, "name", ""))
    )


def _is_voiceish(channel: discord.abc.GuildChannel) -> bool:
    return isinstance(channel, discord.VoiceChannel)


class _JoinNotificationTextModal(discord.ui.Modal, title="Join Notification Text"):
    def __init__(self, default_text: str = "") -> None:
        super().__init__()
        self.value: Optional[str] = None
        self.text = discord.ui.TextInput(
            label="DM Text",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1900,
            default=default_text[:1900],
            placeholder="Hi <Username>! Du bist in <Channelname> gejoint ...",
        )
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.value = str(self.text.value or "").strip()
        # Keep the setup UX to a single edited message (no extra confirmations).
        await interaction.response.defer()


class JoinNotificationSetupView(discord.ui.View):
    def __init__(self, cog: "ChannelJoinNotification", guild: discord.Guild, user_id: int) -> None:
        super().__init__(timeout=600)
        self.cog = cog
        self.guild = guild
        self.user_id = user_id
        self.channel_id: Optional[int] = None

        self.channel_select = discord.ui.ChannelSelect(
            placeholder="Channel auswählen…",
            channel_types=[discord.ChannelType.voice],
            min_values=1,
            max_values=1,
        )
        self.channel_select.callback = self._on_select  # type: ignore[method-assign]
        self.add_item(self.channel_select)

        self.enable_btn = discord.ui.Button(label="Aktivieren", style=discord.ButtonStyle.success)
        self.enable_btn.callback = self._on_enable  # type: ignore[method-assign]
        self.disable_btn = discord.ui.Button(label="Deaktivieren", style=discord.ButtonStyle.danger)
        self.disable_btn.callback = self._on_disable  # type: ignore[method-assign]

        # Step 2 UI is only added after a channel is selected.

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Dieses Menü ist nicht für dich.", ephemeral=True)
            return False
        if interaction.guild is None or interaction.guild.id != self.guild.id:
            await interaction.response.send_message("Nur auf dem Server nutzbar.", ephemeral=True)
            return False
        return True

    async def _load_channel_state(self, channel_id: int) -> Tuple[bool, str]:
        data = await self.cog.config.guild(self.guild).notifications()
        entry = (data or {}).get(str(channel_id), {}) if isinstance(data, dict) else {}
        enabled = bool(entry.get("enabled", False))
        text = str(entry.get("text", "") or "")
        return enabled, text

    async def _set_channel_state(self, channel_id: int, *, enabled: bool, text: Optional[str] = None) -> None:
        data = await self.cog.config.guild(self.guild).notifications()
        if not isinstance(data, dict):
            data = {}
        entry = dict(data.get(str(channel_id), {}) if isinstance(data.get(str(channel_id), {}), dict) else {})
        entry["enabled"] = bool(enabled)
        if text is not None:
            entry["text"] = str(text)
        data[str(channel_id)] = entry
        await self.cog.config.guild(self.guild).notifications.set(data)

    async def _render(self, *, channel: Optional[discord.abc.GuildChannel]) -> str:
        if channel is None or self.channel_id is None:
            return (
                "**Join Notification Setup**\n"
                "Wähle zuerst einen Voice-Channel.\n\n"
                "Platzhalter im Text:\n"
                "- `<Username>`\n"
                "- `<Channelname>`"
            )
        enabled, text = await self._load_channel_state(self.channel_id)
        status = "✅ aktiv" if enabled else "⛔ deaktiviert"
        preview = text.strip() or "(kein Text gesetzt)"
        preview = preview[:220] + ("…" if len(preview) > 220 else "")
        return (
            f"**Join Notification Setup**\n"
            f"- Channel: {channel.mention}\n"
            f"- Status: **{status}**\n"
            f"- Text (Vorschau): `{preview}`\n\n"
            "Aktion wählen:\n"
            "- **Aktivieren** → Text eingeben/ändern\n"
            "- **Deaktivieren** → wird nicht mehr gesendet"
        )

    async def _ensure_step2(self) -> None:
        # Keep one message: we add/remove step 2 controls dynamically.
        has_enable = any(isinstance(c, discord.ui.Button) and c is self.enable_btn for c in self.children)
        if not has_enable:
            self.add_item(self.enable_btn)
            self.add_item(self.disable_btn)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        channel = self.channel_select.values[0] if self.channel_select.values else None
        if channel is None:
            await interaction.response.send_message("Bitte einen Channel auswählen.", ephemeral=True)
            return
        self.channel_id = channel.id
        await self._ensure_step2()
        await interaction.response.edit_message(content=await self._render(channel=channel), view=self)

    async def _on_enable(self, interaction: discord.Interaction) -> None:
        if self.channel_id is None:
            await interaction.response.send_message("Bitte zuerst einen Channel auswählen.", ephemeral=True)
            return
        channel = self.guild.get_channel(self.channel_id)
        if channel is None:
            await interaction.response.send_message("Channel nicht gefunden.", ephemeral=True)
            return
        _, existing_text = await self._load_channel_state(self.channel_id)
        modal = _JoinNotificationTextModal(default_text=existing_text)
        await interaction.response.send_modal(modal)
        await modal.wait()
        if not modal.value:
            return
        await self._set_channel_state(self.channel_id, enabled=True, text=modal.value)
        try:
            await interaction.followup.edit_message(
                message_id=interaction.message.id,  # type: ignore[union-attr]
                content=await self._render(channel=channel),
                view=self,
            )
        except Exception:
            # Fallback: if editing fails, do nothing (modal already acked).
            pass

    async def _on_disable(self, interaction: discord.Interaction) -> None:
        if self.channel_id is None:
            await interaction.response.send_message("Bitte zuerst einen Channel auswählen.", ephemeral=True)
            return
        channel = self.guild.get_channel(self.channel_id)
        if channel is None:
            await interaction.response.send_message("Channel nicht gefunden.", ephemeral=True)
            return
        await self._set_channel_state(self.channel_id, enabled=False)
        await interaction.response.edit_message(content=await self._render(channel=channel), view=self)


class ChannelJoinNotification(commands.Cog):
    """Notifies users via DM when they join certain voice/stage channels."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=771194222451, force_registration=True)
        self.config.register_guild(**DEFAULT_GUILD)
        self._dashboard_attached = False

    # --------------------
    # Slash UI
    # --------------------
    @app_commands.command(
        name="join-notification",
        description="Setup: DM-Benachrichtigung beim Join bestimmter Voice-/Stage-Channels.",
    )
    @app_commands.guild_only()
    async def join_notification(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Nur auf einem Server nutzbar.", ephemeral=True)
            return
        view = JoinNotificationSetupView(self, interaction.guild, interaction.user.id)
        await interaction.response.send_message(await view._render(channel=None), ephemeral=True, view=view)

    # --------------------
    # Listener
    # --------------------
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.guild is None or member.bot:
            return
        if before.channel == after.channel:
            return
        if after.channel is None:
            return
        if not _is_voiceish(after.channel):
            return

        data = await self.config.guild(member.guild).notifications()
        if not isinstance(data, dict):
            return
        entry = data.get(str(after.channel.id), {})
        if not isinstance(entry, dict) or not entry.get("enabled", False):
            return
        text = str(entry.get("text", "") or "").strip()
        if not text:
            return

        dm_text = _render_template(text, member=member, channel=after.channel)
        try:
            dm = await member.create_dm()
            await dm.send(dm_text)
        except Exception:
            # DM might be disabled; ignore silently.
            return

    # --------------------
    # Dashboard attach helpers (AAA3A dashboard)
    # --------------------
    def _get_dashboard_cog(self) -> Optional[commands.Cog]:
        return self.bot.get_cog("DKS-Dashboard") or self.bot.get_cog("Dashboard")

    def _attach_to_dashboard(self, dashboard_cog: commands.Cog) -> bool:
        try:
            dashboard_cog.rpc.third_parties_handler.add_third_party(self, overwrite=True)  # type: ignore[attr-defined]
            return True
        except Exception:
            try:
                dashboard_cog.rpc.third_parties_handler.add_third_party(self)  # type: ignore[attr-defined]
                return True
            except Exception:
                return False

    async def cog_load(self) -> None:
        dashboard_cog = self._get_dashboard_cog()
        if dashboard_cog is not None:
            self._dashboard_attached = self._attach_to_dashboard(dashboard_cog)
        register_dashboard(self)

    @dashboard_widget("cjn_configured_channels", "Join-Notify Channels", size="sm", permission="guild_member")
    async def cjn_configured_channels_widget(self, ctx):
        try:
            data = await self.config.guild(ctx.guild).notifications()
            if not isinstance(data, dict):
                data = {}
            count = sum(
                1 for v in data.values()
                if isinstance(v, dict) and v.get("enabled")
            )
            return WidgetData.kpi(value=count, label="Join-Notify Channels")
        except Exception:
            return WidgetData.kpi(value="–", label="Join-Notify Channels")

    # --- Guild panel: enable DM per voice channel + text ---------------- #
    @dashboard_panel(
        "notifications", "Join-Benachrichtigungen", mount="guild_settings", permission="guild_admin"
    )
    async def cjn_panel(self, ctx):
        data = await self.config.guild(ctx.guild).notifications()
        if not isinstance(data, dict):
            data = {}
        variables = [
            {"token": "<Username>", "desc": "Nutzer"},
            {"token": "<Channelname>", "desc": "Kanal"},
        ]
        voice = [c for c in ctx.guild.channels if isinstance(c, discord.VoiceChannel)]
        fields = []
        for c in voice:
            entry = data.get(str(c.id), {}) if isinstance(data.get(str(c.id)), dict) else {}
            fields.append(Field.switch(f"{c.id}__enabled", f"🔊 {c.name} – aktiv", value=bool(entry.get("enabled"))))
            fields.append(Field.textarea(f"{c.id}__text", f"🔊 {c.name} – DM-Text",
                                         value=str(entry.get("text", "")), max_length=1500, variables=variables))
        if not fields:
            return PanelSchema(description="Keine Sprachkanäle auf diesem Server.")
        return PanelSchema(description="Pro Sprachkanal: DM beim Beitritt aktivieren und Text festlegen.", fields=fields)

    @cjn_panel.on_submit
    async def _save_cjn(self, ctx, data):
        notifications = await self.config.guild(ctx.guild).notifications()
        if not isinstance(notifications, dict):
            notifications = {}
        voice = [c for c in ctx.guild.channels if isinstance(c, discord.VoiceChannel)]
        for c in voice:
            entry = notifications.get(str(c.id), {}) if isinstance(notifications.get(str(c.id)), dict) else {}
            if f"{c.id}__enabled" in data:
                entry["enabled"] = bool(data[f"{c.id}__enabled"])
            if f"{c.id}__text" in data:
                entry["text"] = str(data[f"{c.id}__text"])[:1500]
            notifications[str(c.id)] = entry
        await self.config.guild(ctx.guild).notifications.set(notifications)
        return SubmitResult.ok("Gespeichert.")

    # --- Guild list: configured join notifications ---------------------- #
    @dashboard_list(
        "cjn_list", "Konfigurierte Benachrichtigungen", mount="guild_settings",
        permission="guild_admin",
        columns=[
            {"key": "channel", "label": "Sprachkanal"},
            {"key": "enabled", "label": "Aktiv"},
            {"key": "text", "label": "DM-Text"},
        ],
    )
    async def cjn_list(self, ctx):
        data = await self.config.guild(ctx.guild).notifications()
        rows = []
        for cid, e in (data or {}).items():
            if not isinstance(e, dict):
                continue
            # Only show entries that are actually configured.
            if not (e.get("enabled") or e.get("text")):
                continue
            ch = ctx.guild.get_channel(int(cid)) if str(cid).isdigit() else None
            txt = str(e.get("text", "") or "")
            rows.append({
                "id": str(cid),
                "cells": {
                    "channel": ("🔊 " + ch.name) if ch else str(cid),
                    "enabled": "✅" if e.get("enabled") else "—",
                    "text": (txt[:60] + "…") if len(txt) > 60 else (txt or "—"),
                },
            })
        return rows

    @cjn_list.edit_form
    async def _cjn_edit_form(self, ctx, item_id):
        data = await self.config.guild(ctx.guild).notifications()
        entry = (data or {}).get(str(item_id)) or {}
        variables = [
            {"token": "<Username>", "desc": "Nutzer"},
            {"token": "<Channelname>", "desc": "Kanal"},
        ]
        return PanelSchema(
            description="Benachrichtigung für diesen Sprachkanal bearbeiten.",
            fields=[
                Field.switch("enabled", "Aktiv", value=bool(entry.get("enabled"))),
                Field.textarea("text", "DM-Text", value=str(entry.get("text", "")),
                               max_length=1500, variables=variables),
            ],
        )

    @cjn_list.on_edit
    async def _cjn_edit(self, ctx, item_id, data):
        async with self.config.guild(ctx.guild).notifications() as notifications:
            entry = notifications.get(str(item_id)) if isinstance(notifications.get(str(item_id)), dict) else {}
            if "enabled" in data:
                entry["enabled"] = bool(data["enabled"])
            if "text" in data:
                entry["text"] = str(data["text"])[:1500]
            notifications[str(item_id)] = entry
        return SubmitResult.ok("Gespeichert.")

    @cjn_list.on_delete
    async def _cjn_delete(self, ctx, item_id):
        async with self.config.guild(ctx.guild).notifications() as notifications:
            if str(item_id) in notifications:
                del notifications[str(item_id)]
            else:
                return SubmitResult.fail("Eintrag nicht gefunden.")
        return SubmitResult.ok("Benachrichtigung entfernt.")

    async def cog_unload(self) -> None:
        unregister_dashboard(self)
        dashboard_cog = self._get_dashboard_cog()
        if dashboard_cog is not None:
            try:
                dashboard_cog.rpc.third_parties_handler.remove_third_party(self)  # type: ignore[attr-defined]
            except Exception:
                pass
        self._dashboard_attached = False

    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
        if self._dashboard_attached:
            return
        self._dashboard_attached = self._attach_to_dashboard(dashboard_cog)

    @commands.Cog.listener()
    async def on_dashboard_cog_remove(self, dashboard_cog: commands.Cog) -> None:
        _ = dashboard_cog
        self._dashboard_attached = False

    # --------------------
    # Dashboard pages
    # --------------------
    @_dashboard_page(name=None, description="Channel Join Notification Dashboard")
    async def dashboard_home(self, **kwargs: Any) -> Dict[str, Any]:
        _ = kwargs
        source = """
<div style="padding: 12px;">
  <h2>Channel Join Notification</h2>
  <p>Dashboard integration is active.</p>
  <p>Use the page <b>channeljoinnotification</b> for guild-specific settings.</p>
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
        name="channeljoinnotification",
        description="Configure join DM notifications for this server.",
        methods=("GET", "POST"),
        context_ids=["user_id", "guild_id"],
        hidden=False,
    )
    async def dashboard_channeljoinnotification(
        self,
        user_id: Optional[int] = None,
        guild_id: Optional[int] = None,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        try:
            _ = data
            if user_id is None or guild_id is None:
                return {
                    "status": 0,
                    "error_code": 400,
                    "message": "Missing context: user_id/guild_id. Open this page from a server context.",
                }
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                return {"status": 1, "message": "Guild not found."}
            member = guild.get_member(user_id)
            if user_id not in self.bot.owner_ids and (
                member is None or not (await self.bot.is_admin(member) or member.guild_permissions.manage_guild)
            ):
                return {"status": 1, "message": "Not allowed."}

            Form = kwargs.get("Form")
            cfg = await self.config.guild(guild).all()
            notifications = cfg.get("notifications", {})
            if not isinstance(notifications, dict):
                notifications = {}
            page_notice = ""
            page_notice_kind = "success"

            voice_choices = [("0", "-- Channel wählen --")]
            for ch in sorted(guild.voice_channels, key=lambda c: (c.position, c.name.lower())):
                voice_choices.append((str(ch.id), f"{ch.name} (voice) ({ch.id})"))

            existing_choices = [("0", "-- none --")]
            for cid in sorted(notifications.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
                ch = guild.get_channel(int(cid)) if str(cid).isdigit() else None
                label = f"{getattr(ch, 'name', 'unknown')} ({cid})"
                existing_choices.append((str(cid), label))

            # UI mode
            if Form is not None:
                import wtforms

                class GuildForm(Form):
                    def __init__(_self) -> None:
                        super().__init__(prefix="cjn_")

                    channel_id = wtforms.SelectField("Voice Channel", choices=voice_choices)
                    enabled = wtforms.BooleanField("Enabled")
                    text = wtforms.TextAreaField(
                        "DM Text (placeholders: <Username>, <Channelname>)",
                        default="Hi <Username>! Willkommen in <Channelname>.",
                    )
                    save = wtforms.SubmitField("Add/Update")

                    remove_channel_id = wtforms.SelectField("Remove Entry", choices=existing_choices)
                    remove = wtforms.SubmitField("Remove")

                form = GuildForm()

                if method.upper() == "GET":
                    form.channel_id.data = "0"
                    form.enabled.data = True

                if method.upper() == "POST":
                    posted = dict((data or {}).get("form", {})) if isinstance(data, dict) else {}
                    remove_clicked = bool(form.remove.data) or ("cjn-remove" in posted) or ("remove" in posted)
                    save_clicked = bool(form.save.data) or ("cjn-save" in posted) or ("save" in posted)

                    if remove_clicked:
                        rid = str(
                            posted.get("cjn-remove_channel_id")
                            or posted.get("remove_channel_id")
                            or form.remove_channel_id.data
                            or "0"
                        )
                        if rid != "0" and rid in notifications:
                            notifications.pop(rid, None)
                            await self.config.guild(guild).notifications.set(notifications)
                            page_notice = "Eintrag entfernt."
                            page_notice_kind = "success"
                        else:
                            page_notice = "Kein gültiger Eintrag zum Entfernen ausgewählt."
                            page_notice_kind = "warning"
                    elif save_clicked:
                        cid = str(posted.get("cjn-channel_id") or posted.get("channel_id") or form.channel_id.data or "0")
                        enabled_raw = posted.get("cjn-enabled", posted.get("enabled", form.enabled.data))
                        enabled = str(enabled_raw).lower() in ("true", "1", "on", "yes") or enabled_raw is True
                        text = str(posted.get("cjn-text") or posted.get("text") or form.text.data or "").strip()
                        if cid == "0":
                            page_notice = "Bitte einen Channel auswählen."
                            page_notice_kind = "warning"
                        else:
                            notifications[cid] = {
                                "enabled": bool(enabled),
                                "text": text,
                            }
                            await self.config.guild(guild).notifications.set(notifications)
                            page_notice = "Eintrag gespeichert."
                            page_notice_kind = "success"

                rows = []
                for cid, entry in sorted(
                    notifications.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0
                ):
                    ch = guild.get_channel(int(cid)) if str(cid).isdigit() else None
                    name = getattr(ch, "name", "unknown")
                    enabled = bool(entry.get("enabled", False))
                    text = str(entry.get("text", "") or "")
                    preview = text.strip() or "(empty)"
                    rows.append(
                        f"<tr>"
                        f"<td><span class='tag'>{html.escape(name)}</span><div class='muted'>{cid}</div></td>"
                        f"<td>{'🟢 ON' if enabled else '⚫ OFF'}</td>"
                        f"<td><textarea class='preview-box' readonly>{html.escape(preview)}</textarea></td>"
                        f"</tr>"
                    )
                table_html = (
                    "<table class='tbl'><thead><tr><th>Channel</th><th>Status</th><th>Text Preview</th></tr></thead>"
                    f"<tbody>{''.join(rows) if rows else '<tr><td colspan=3 class=muted>Keine Einträge</td></tr>'}</tbody></table>"
                )
                notice_html = (
                    f"<div class='notice {'ok' if page_notice_kind == 'success' else 'warn'}'>{html.escape(page_notice)}</div>"
                    if page_notice
                    else ""
                )
                config_obj = {
                    str(k): {
                        "enabled": bool(v.get("enabled", False)),
                        "text": str(v.get("text", "") or ""),
                    }
                    for k, v in notifications.items()
                    if isinstance(v, dict)
                }
                # Keep valid JSON for client-side parsing; only neutralize closing script tag.
                config_json_html = json.dumps(config_obj).replace("</", "<\\/")

                source = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root {{
  --bg0: #070a12;
  --bg1: rgba(10, 14, 28, .72);
  --stroke: rgba(255,255,255,.10);
  --text: #e6edf7;
  --muted: #9aa6b2;
  --accent: #22d3ee;
  --accent2: #a78bfa;
  --danger: #fb7185;
}}
.wrap {{
  font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  color: var(--text);
  padding: 26px;
  background:
    radial-gradient(900px 420px at 14% 10%, rgba(34,211,238,.18), transparent 60%),
    radial-gradient(850px 420px at 86% 0%, rgba(167,139,250,.16), transparent 55%),
    linear-gradient(180deg, rgba(7,10,18,1), rgba(7,10,18,.94));
  border-radius: 18px;
  border: 1px solid var(--stroke);
  box-shadow: 0 18px 60px rgba(0,0,0,.55);
}}
.head {{
  display:flex; align-items:flex-end; justify-content:space-between; gap:16px; flex-wrap:wrap;
  margin-bottom: 18px;
}}
.title {{
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
}}
.subtitle {{
  color: var(--muted);
  margin-top: 6px;
  line-height: 1.5;
}}
.grid {{
  display:grid;
  grid-template-columns: 1.1fr .9fr;
  gap: 16px;
}}
.card {{
  background: var(--bg1);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--stroke);
  border-radius: 14px;
  padding: 16px;
}}
label {{
  display:inline-block;
  font-size: 12.5px;
  font-weight: 600;
  color: rgba(230,237,247,.88);
  margin-bottom: 6px;
}}
input, select, textarea {{
  width: 100%;
  box-sizing: border-box;
  background: rgba(0,0,0,.28);
  border: 1px solid rgba(255,255,255,.12);
  color: var(--text);
  padding: 10px 12px;
  border-radius: 10px;
  outline: none;
  transition: .18s ease;
}}
textarea {{ min-height: 110px; resize: vertical; }}
.toggle {{
  display: inline-flex;
  align-items: center;
  gap: 10px;
  background: rgba(0,0,0,.26);
  border: 1px solid rgba(255,255,255,.12);
  border-radius: 10px;
  padding: 10px 12px;
}}
.toggle input[type="checkbox"] {{
  width: 18px;
  height: 18px;
  margin: 0;
  accent-color: #22d3ee;
}}
.toggle .tlabel {{
  font-size: 13px;
  font-weight: 600;
  color: rgba(230,237,247,.95);
  margin: 0;
}}
input:focus, select:focus, textarea:focus {{
  border-color: rgba(34,211,238,.55);
  box-shadow: 0 0 0 3px rgba(34,211,238,.14);
}}
.row {{ margin-bottom: 12px; }}
.btnrow {{ display:flex; gap:10px; flex-wrap:wrap; }}
.btnrow input {{
  width: auto;
  padding: 10px 14px;
  background: linear-gradient(90deg, rgba(34,211,238,.22), rgba(167,139,250,.18));
  border-color: rgba(34,211,238,.25);
  cursor: pointer;
  font-weight: 700;
}}
.btnrow input[name$="remove"] {{
  background: rgba(251,113,133,.10);
  border-color: rgba(251,113,133,.30);
}}
.muted {{ color: var(--muted); font-size: 12px; }}
.tag {{
  display:inline-block;
  padding: 4px 8px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,.12);
  background: rgba(0,0,0,.24);
}}
.tbl {{
  width: 100%;
  border-collapse: collapse;
  overflow: hidden;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,.10);
}}
.tbl th, .tbl td {{
  padding: 10px 10px;
  border-bottom: 1px solid rgba(255,255,255,.08);
  vertical-align: top;
}}
.tbl th {{
  text-align:left;
  color: rgba(245, 250, 255, .98);
  font-size: 12px;
  letter-spacing: .02em;
  background: rgba(0,0,0,.22);
}}
.tbl td {{
  color: rgba(238, 244, 255, .95);
}}
.code {{
  background: rgba(0,0,0,.25);
  padding: 4px 6px;
  border-radius: 8px;
  border: 1px solid rgba(255,255,255,.10);
  display:inline-block;
}}
.preview-box {{
  width: 100%;
  min-height: 72px;
  max-height: 160px;
  resize: vertical;
  overflow: auto;
  white-space: pre-wrap;
  color: rgba(245, 250, 255, .98);
  background: rgba(5, 9, 18, .76);
  border: 1px solid rgba(255,255,255,.18);
  border-radius: 8px;
  padding: 8px 10px;
  line-height: 1.4;
}}
.preview-box:focus {{
  outline: none;
  border-color: rgba(34,211,238,.45);
  box-shadow: 0 0 0 2px rgba(34,211,238,.12);
}}
.notice {{
  margin-bottom: 12px;
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 13px;
  border: 1px solid rgba(255,255,255,.14);
}}
.notice.ok {{
  background: rgba(16, 185, 129, .12);
  border-color: rgba(16, 185, 129, .4);
}}
.notice.warn {{
  background: rgba(245, 158, 11, .12);
  border-color: rgba(245, 158, 11, .4);
}}
@media (max-width: 980px) {{
  .grid {{ grid-template-columns: 1fr; }}
}}
</style>
<div class="wrap">
  <div class="head">
    <div>
      <div class="title">Channel Join Notification</div>
      <div class="subtitle">
        Bei Join in einen konfigurierten <b>Voice-Channel</b> sendet der Bot eine DM.
        <br>Platzhalter: <code class="code">&lt;Username&gt;</code>, <code class="code">&lt;Channelname&gt;</code>
      </div>
    </div>
    <div class="muted">Server: <b>{html.escape(guild.name)}</b></div>
  </div>
  {notice_html}
  <div class="grid">
    <div class="card">
      <form method="post">
        {form.hidden_tag()}
        <div class="row"><label>Channel</label><br>{form.channel_id()}</div>
        <div class="row">
          <div class="toggle"><span>{form.enabled()}</span><span class="tlabel">Enabled</span></div>
          <div class="muted" style="margin-top: 6px;">Wenn aus: keine DM beim Join.</div>
        </div>
        <div class="row"><label>DM Text</label><br>{form.text()}</div>
        <div class="btnrow">
          {form.save()}
        </div>
      </form>
    </div>
    <div class="card">
      <form method="post">
        {form.hidden_tag()}
        <div class="row"><label>Eintrag entfernen</label><br>{form.remove_channel_id()}</div>
        <div class="btnrow">
          {form.remove()}
        </div>
        <div class="muted" style="margin-top:10px;">
          Tipp: Du kannst einen Channel auch einfach deaktivieren statt zu entfernen.
        </div>
      </form>
    </div>
  </div>
  <div style="height: 14px;"></div>
  <div class="card">
    <div style="font-weight:700; margin-bottom:10px;">Aktuelle Einträge</div>
    {table_html}
  </div>
</div>
<script id="cjn-config" type="application/json">{config_json_html}</script>
<script>
(() => {{
  const cfgNode = document.getElementById("cjn-config");
  if (!cfgNode) return;
  let cfg = {{}};
  try {{
    cfg = JSON.parse(cfgNode.textContent || "{{}}");
  }} catch (_e) {{
    cfg = {{}};
  }}
  const channelSelect =
    document.querySelector("select[name='cjn-channel_id']") ||
    document.querySelector("select[name$='channel_id']:not([name$='remove_channel_id'])");
  const enabledInput = document.querySelector("input[name$='enabled']");
  const textInput = document.querySelector("textarea[name$='text']");
  if (!channelSelect || !enabledInput || !textInput) return;
  const apply = () => {{
    const cid = String(channelSelect.value || "0");
    const entry = cfg[cid];
    if (!entry) {{
      enabledInput.checked = true;
      textInput.value = "Hi <Username>! Willkommen in <Channelname>.";
      return;
    }}
    enabledInput.checked = !!entry.enabled;
    textInput.value = String(entry.text || "");
  }};
  channelSelect.addEventListener("change", apply);
  apply();
}})();
</script>
"""
                return {"status": 0, "web_content": {"source": source, "standalone": True}}

            # API mode (no Form)
            return {
                "status": 0,
                "web_content": {
                    "source": (
                        "<div style='padding:12px;'>"
                        "<h2>Channel Join Notification</h2>"
                        "<p>Use POST on this page endpoint to update values.</p>"
                        "<h3>Current Config</h3>"
                        f"<pre>{html.escape(json.dumps(cfg, indent=2))}</pre>"
                        "</div>"
                    ),
                    "standalone": True,
                },
            }
        except Exception as e:
            return {
                "status": 0,
                "error_code": 500,
                "message": f"Page failed: {e}",
                "error_message": traceback.format_exc(limit=2),
            }

