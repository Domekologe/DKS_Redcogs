"""Interactive discord.ui flows for linking guild roster characters (Retail / MoP Classic)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

import discord

from .character_helpers import (
    GAME_LABELS,
    GAME_MOP,
    GAME_RETAIL,
    SUPPORTED_GAMES,
    find_char_owner_guild_wide,
    format_char_line,
    game_label,
    get_linked_list,
    set_linked_list,
    wow_profile_for_game,
)

if TYPE_CHECKING:
    from .wowguild_automation import WowGuildAutomation


class CharMainMenuView(discord.ui.View):
    def __init__(self, cog: "WowGuildAutomation", guild: discord.Guild, member: discord.Member) -> None:
        super().__init__(timeout=600)
        self.cog = cog
        self.guild = guild
        self.member = member

    @discord.ui.button(label="Chars hinzufügen", style=discord.ButtonStyle.primary, row=0)
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Welches Spiel?",
            ephemeral=True,
            view=GamePickView(self.cog, self.guild, self.member, mode="add"),
        )

    @discord.ui.button(label="Main setzen", style=discord.ButtonStyle.secondary, row=0)
    async def main_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        linked = await get_linked_list(self.cog.config.member(self.member))
        if not linked:
            await interaction.response.send_message("Noch keine Chars verknüpft.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Wähle deinen Main-Char:",
            ephemeral=True,
            view=MainCharSelectView(self.cog, self.guild, self.member, linked),
        )

    @discord.ui.button(label="Meine Chars", style=discord.ButtonStyle.secondary, row=1)
    async def list_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        text = await self.cog._format_user_char_list_ephemeral(self.guild, self.member, header_user=False)
        await interaction.followup.send(text, ephemeral=True)

    @discord.ui.button(label="Chars entfernen", style=discord.ButtonStyle.danger, row=1)
    async def remove_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        linked = await get_linked_list(self.cog.config.member(self.member))
        if not linked:
            await interaction.response.send_message("Nichts zum Entfernen.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Wähle Charaktere zum Entfernen (mehrfach möglich):",
            ephemeral=True,
            view=RemoveSelfSelectView(self.cog, self.guild, self.member, linked),
        )


class GamePickView(discord.ui.View):
    def __init__(
        self,
        cog: "WowGuildAutomation",
        guild: discord.Guild,
        member: discord.Member,
        *,
        mode: str,
    ) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.member = member
        self.mode = mode

    @discord.ui.button(label="Retail", style=discord.ButtonStyle.primary, row=0)
    async def retail(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open_roster(interaction, GAME_RETAIL)

    @discord.ui.button(label="MoP Classic", style=discord.ButtonStyle.primary, row=0)
    async def mop(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open_roster(interaction, GAME_MOP)

    async def _open_roster(self, interaction: discord.Interaction, game: str) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        cfg = await self.cog._guild_config(self.guild)
        prof = await wow_profile_for_game(cfg, game)
        if not prof or not prof.get("realm") or not prof.get("guild_name"):
            await interaction.response.send_message(
                f"Für **{game_label(game)}** fehlen Realm/Gildenname im Server-Setup (Web-Dashboard / `wow guildsettings`).",
                ephemeral=True,
            )
            return
        names = await self.cog.blizzard.roster_character_names(
            prof.get("region", "eu"),
            prof.get("version", game),
            prof.get("realm", ""),
            prof.get("guild_name", ""),
        )
        if not names:
            await interaction.response.send_message(
                "Gildenroster leer oder API-Fehler. Prüfe Client-ID/Secret und Profil.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"Roster **{game_label(game)}** – Seite wählen und Charaktere markieren, dann „Übernehmen“.",
            ephemeral=True,
            view=RosterPageView(self.cog, self.guild, self.member, game, names, page=0),
        )


class RosterPageView(discord.ui.View):
    PAGE_SIZE = 24

    def __init__(
        self,
        cog: "WowGuildAutomation",
        guild: discord.Guild,
        member: discord.Member,
        game_type: str,
        all_names: List[str],
        page: int,
    ) -> None:
        super().__init__(timeout=600)
        self.cog = cog
        self.guild = guild
        self.member = member
        self.game_type = game_type
        self.all_names = all_names
        self.page = max(0, page)
        start = self.page * self.PAGE_SIZE
        chunk = all_names[start : start + self.PAGE_SIZE]
        options: List[discord.SelectOption] = []
        for n in chunk[:25]:
            options.append(discord.SelectOption(label=n[:100], value=n[:100]))
        if options:

            async def _select_cb(interaction: discord.Interaction) -> None:
                await RosterPageView._handle_roster_select(
                    interaction, cog, guild, member, game_type, all_names, page, self
                )

            select = discord.ui.Select(
                placeholder="Charaktere auswählen (mehrfach), dann hier bestätigen",
                min_values=1,
                max_values=len(options),
                options=options,
            )
            select.callback = _select_cb
            self.add_item(select)
        if self.page > 0:
            b = discord.ui.Button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
            b.callback = self._prev_page
            self.add_item(b)
        if start + self.PAGE_SIZE < len(all_names):
            b2 = discord.ui.Button(label="Weiter ▶", style=discord.ButtonStyle.secondary, row=1)
            b2.callback = self._next_page
            self.add_item(b2)

    async def _prev_page(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(
            content=f"Roster **{game_label(self.game_type)}** – Seite {self.page}.",
            view=RosterPageView(
                self.cog, self.guild, self.member, self.game_type, self.all_names, self.page - 1
            ),
        )

    async def _next_page(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(
            content=f"Roster **{game_label(self.game_type)}** – Seite {self.page + 2}.",
            view=RosterPageView(
                self.cog, self.guild, self.member, self.game_type, self.all_names, self.page + 1
            ),
        )

    @staticmethod
    async def _handle_roster_select(
        interaction: discord.Interaction,
        cog: "WowGuildAutomation",
        guild: discord.Guild,
        member: discord.Member,
        game_type: str,
        all_names: List[str],
        page: int,
        view: "RosterPageView",
    ) -> None:
        if interaction.user.id != member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        selected = interaction.data.get("values") or []
        if not selected:
            await interaction.response.send_message("Nichts gewählt.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        msg, ok = await cog._try_add_characters_for_member(guild, member, game_type, list(selected))
        await interaction.followup.send(msg, ephemeral=True)
        if ok:
            view.stop()


class MainCharSelectView(discord.ui.View):
    def __init__(
        self,
        cog: "WowGuildAutomation",
        guild: discord.Guild,
        member: discord.Member,
        linked: List[Dict[str, str]],
    ) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.member = member
        opts: List[discord.SelectOption] = []
        for e in linked[:25]:
            label = f"{e['name']} ({game_label(e['game_type'])})"[:100]
            value = f"{e['name']}|{e['game_type']}"
            opts.append(discord.SelectOption(label=label, value=value[:100]))
        s = discord.ui.Select(placeholder="Main-Char", min_values=1, max_values=1, options=opts)
        s.callback = self._pick
        self.add_item(s)

    async def _pick(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        raw = (interaction.data.get("values") or [""])[0]
        if "|" not in raw:
            await interaction.response.send_message("Ungültig.", ephemeral=True)
            return
        name, game = raw.split("|", 1)
        if game not in SUPPORTED_GAMES:
            game = GAME_RETAIL
        await self.cog.config.member(self.member).main_character.set({"name": name.strip(), "game_type": game})
        await self.cog.config.member(self.member).selected_game.set(game)
        await interaction.response.send_message(
            f"Main gesetzt: **{name}** ({game_label(game)}).", ephemeral=True
        )
        self.stop()


class RemoveSelfSelectView(discord.ui.View):
    def __init__(
        self,
        cog: "WowGuildAutomation",
        guild: discord.Guild,
        member: discord.Member,
        linked: List[Dict[str, str]],
    ) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.member = member
        self.linked = linked
        opts: List[discord.SelectOption] = []
        for e in linked[:25]:
            label = f"{e['name']} ({game_label(e['game_type'])})"[:100]
            value = f"{e['name']}|{e['game_type']}"
            opts.append(discord.SelectOption(label=label, value=value[:100]))
        s = discord.ui.Select(
            placeholder="Zu entfernende Chars",
            min_values=1,
            max_values=len(opts),
            options=opts,
        )
        s.callback = self._remove
        self.add_item(s)

    async def _remove(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        vals = interaction.data.get("values") or []
        remove_keys = set()
        for v in vals:
            if "|" not in v:
                continue
            n, g = v.split("|", 1)
            remove_keys.add((n.strip().lower(), g.lower()))
        new_list = [
            x
            for x in self.linked
            if (x["name"].lower(), x["game_type"].lower()) not in remove_keys
        ]
        await set_linked_list(self.cog.config.member(self.member), new_list)
        main = await self.cog.config.member(self.member).main_character()
        if isinstance(main, dict) and main.get("name") and main.get("game_type"):
            if (main["name"].lower(), main["game_type"].lower()) in remove_keys:
                await self.cog.config.member(self.member).main_character.clear()
        await interaction.response.send_message("Ausgewählte Chars entfernt.", ephemeral=True)
        self.stop()


class OfficerRemoveCharView(discord.ui.View):
    """Officer picks multiple linked chars, then opens modal for reason."""

    def __init__(
        self,
        cog: "WowGuildAutomation",
        guild: discord.Guild,
        officer: discord.Member,
        target: discord.Member,
        linked: List[Dict[str, str]],
    ) -> None:
        super().__init__(timeout=600)
        self.cog = cog
        self.guild = guild
        self.officer = officer
        self.target = target
        self.linked = linked
        opts: List[discord.SelectOption] = []
        for e in linked[:25]:
            label = f"{e['name']} ({game_label(e['game_type'])})"[:100]
            value = f"{e['name']}|{e['game_type']}"
            opts.append(discord.SelectOption(label=label, value=value[:100]))
        s = discord.ui.Select(
            placeholder="Chars entfernen",
            min_values=1,
            max_values=len(opts),
            options=opts,
        )
        s.callback = self._picked
        self.add_item(s)

    async def _picked(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.officer.id:
            await interaction.response.send_message("Nur für den ausführenden Offizier.", ephemeral=True)
            return
        vals = interaction.data.get("values") or []
        keys = []
        for v in vals:
            if "|" in v:
                n, g = v.split("|", 1)
                keys.append((n.strip(), g))
        if not keys:
            await interaction.response.send_message("Nichts gewählt.", ephemeral=True)
            return
        await interaction.response.send_modal(
            OfficerRemoveReasonModal(self.cog, self.guild, self.officer, self.target, keys)
        )
        self.stop()


class OfficerRemoveReasonModal(discord.ui.Modal, title="Begründung"):
    reason = discord.ui.TextInput(
        label="Grund (sichtbar für den User)",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True,
    )

    def __init__(
        self,
        cog: "WowGuildAutomation",
        guild: discord.Guild,
        officer: discord.Member,
        target: discord.Member,
        to_remove: List[tuple],
    ) -> None:
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.officer = officer
        self.target = target
        self.to_remove = to_remove

    async def on_submit(self, interaction: discord.Interaction) -> None:
        reason = str(self.reason.value).strip()
        linked = await get_linked_list(self.cog.config.member(self.target))
        rset = {(n.lower(), g.lower()) for n, g in self.to_remove}
        new_list = [x for x in linked if (x["name"].lower(), x["game_type"].lower()) not in rset]
        removed_labels = [f"{n} ({game_label(g)})" for n, g in self.to_remove]
        await set_linked_list(self.cog.config.member(self.target), new_list)
        main = await self.cog.config.member(self.target).main_character()
        if isinstance(main, dict):
            for n, g in self.to_remove:
                if (
                    main.get("name", "").lower() == n.lower()
                    and main.get("game_type", "").lower() == g.lower()
                ):
                    await self.cog.config.member(self.target).main_character.clear()
                    break
        cfg = await self.cog.config.guild(self.guild).all()
        templates = cfg.get("templates", {})
        dm_t = templates.get(
            "admin_removed_char_dm",
            "Ein Offizier hat folgende WoW-Chars von dir entfernt: {chars}\nGrund: {reason}",
        )
        try:
            await self.target.send(
                dm_t.format(
                    chars=", ".join(removed_labels),
                    reason=reason,
                    officer=self.officer.display_name,
                )
            )
        except discord.HTTPException:
            pass
        await interaction.response.send_message(
            f"Entfernt bei {self.target.mention}: {', '.join(removed_labels)}", ephemeral=True
        )


def officer_can_manage_characters(member: discord.Member) -> bool:
    return member.guild_permissions.manage_guild or member.guild_permissions.administrator


class OfficerListMenuView(discord.ui.View):
    """Officer: list character links — all members or pick users (multi)."""

    def __init__(self, cog: "WowGuildAutomation", guild: discord.Guild, officer: discord.Member) -> None:
        super().__init__(timeout=600)
        self.cog = cog
        self.guild = guild
        self.officer = officer

    @discord.ui.button(label="Alle mit verknüpften Chars", style=discord.ButtonStyle.primary, row=0)
    async def all_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.officer.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        text = await self.cog._officer_format_all_linked_chars(self.guild)
        for chunk in [text[i : i + 1900] for i in range(0, len(text), 1900)] or ["Keine Einträge."]:
            await interaction.followup.send(chunk, ephemeral=True)

    @discord.ui.button(label="Bestimmte Mitglieder wählen", style=discord.ButtonStyle.secondary, row=0)
    async def pick_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.officer.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Wähle bis zu 25 Mitglieder:",
            ephemeral=True,
            view=OfficerUserPickView(self.cog, self.guild, self.officer),
        )


class OfficerUserPickView(discord.ui.View):
    def __init__(self, cog: "WowGuildAutomation", guild: discord.Guild, officer: discord.Member) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.officer = officer
        self.user_select = discord.ui.UserSelect(
            placeholder="Mitglieder (mehrfach)",
            min_values=1,
            max_values=25,
            custom_id="officer_user_pick",
        )
        self.user_select.callback = self._on_users
        self.add_item(self.user_select)

    async def _on_users(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.officer.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        users = self.user_select.values
        await interaction.response.defer(ephemeral=True)
        lines: List[str] = []
        for u in users:
            m = self.guild.get_member(u.id)
            if not m:
                continue
            lines.append(await self.cog._format_user_char_list_ephemeral(self.guild, m, header_user=True))
        msg = "\n\n".join(lines) if lines else "Keine gültigen Mitglieder."
        for chunk in [msg[i : i + 1900] for i in range(0, len(msg), 1900)] or ["—"]:
            await interaction.followup.send(chunk, ephemeral=True)
        self.stop()
