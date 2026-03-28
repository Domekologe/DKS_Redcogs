"""Interactive discord.ui flows for linking guild roster characters (Retail / MoP Classic)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

import discord

from .character_helpers import (
    GAME_MOP,
    GAME_RETAIL,
    SUPPORTED_GAMES,
    char_tuple_key,
    clear_main_for_game,
    game_label,
    get_linked_list,
    get_main_characters,
    set_linked_list,
    set_main_for_game,
    wow_profile_for_game,
)

if TYPE_CHECKING:
    from .wowguild_automation import WowGuildAutomation

PANEL_INTRO = (
    "Verknüpfe nur Charaktere, die auf eurer **Gildenroster**-API stehen.\n"
    "Alles läuft in **dieser einen** Nachricht (ephemeral)."
)

LINKED_PAGE_SIZE = 24


def _menu_view(cog: "WowGuildAutomation", guild: discord.Guild, member: discord.Member) -> CharMainMenuView:
    return CharMainMenuView(cog, guild, member)


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
        await interaction.response.edit_message(
            content="Welches Spiel?",
            view=GamePickView(self.cog, self.guild, self.member, mode="add"),
        )

    @discord.ui.button(label="Main setzen", style=discord.ButtonStyle.secondary, row=0)
    async def main_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        linked = await get_linked_list(self.cog.config.member(self.member))
        if not linked:
            await interaction.response.edit_message(
                content="Noch keine Chars verknüpft.",
                view=_menu_view(self.cog, self.guild, self.member),
            )
            return
        await interaction.response.edit_message(
            content="**Main pro Spiel** — zuerst Version wählen:",
            view=MainGamePickView(self.cog, self.guild, self.member),
        )

    @discord.ui.button(label="Meine Chars", style=discord.ButtonStyle.secondary, row=1)
    async def list_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        text = await self.cog._format_user_char_list_ephemeral(self.guild, self.member, header_user=False)
        await interaction.response.edit_message(
            content=text,
            view=_menu_view(self.cog, self.guild, self.member),
        )

    @discord.ui.button(label="Chars entfernen", style=discord.ButtonStyle.danger, row=1)
    async def remove_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        linked = await get_linked_list(self.cog.config.member(self.member))
        if not linked:
            await interaction.response.edit_message(
                content="Nichts zum Entfernen.",
                view=_menu_view(self.cog, self.guild, self.member),
            )
            return
        ordered = sorted(linked, key=lambda e: (e["game_type"], e["name"].lower()))
        await interaction.response.edit_message(
            content=self._remove_caption(ordered, 0),
            view=LinkedRemovePageView(
                self.cog, self.guild, self.member, ordered, page=0, officer_mode=False
            ),
        )

    @staticmethod
    def _remove_caption(ordered: List[Dict[str, str]], page: int) -> str:
        total_pages = max(1, (len(ordered) + LINKED_PAGE_SIZE - 1) // LINKED_PAGE_SIZE)
        return (
            f"**Chars entfernen** — Seite **{page + 1}/{total_pages}** "
            f"({len(ordered)} gesamt). Wähle im Dropdown (max. {LINKED_PAGE_SIZE} pro Seite)."
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

    @discord.ui.button(label="◀ Menü", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        await interaction.response.edit_message(content=PANEL_INTRO, view=_menu_view(self.cog, self.guild, self.member))

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
            await interaction.response.edit_message(
                content=(
                    f"Für **{game_label(game)}** fehlen Realm/Gildenname im Server-Setup "
                    "(Web-Dashboard / `wow guildsettings`)."
                ),
                view=_menu_view(self.cog, self.guild, self.member),
            )
            return
        names = await self.cog.blizzard.roster_character_names(
            prof.get("region", "eu"),
            prof.get("version", game),
            prof.get("realm", ""),
            prof.get("guild_name", ""),
        )
        if not names:
            await interaction.response.edit_message(
                content="Gildenroster leer oder API-Fehler. Prüfe Client-ID/Secret und Profil.",
                view=_menu_view(self.cog, self.guild, self.member),
            )
            return
        total_pages = max(1, (len(names) + LINKED_PAGE_SIZE - 1) // LINKED_PAGE_SIZE)
        await interaction.response.edit_message(
            content=(
                f"Roster **{game_label(game)}** — Seite **1/{total_pages}**. "
                "Mehrfachauswahl im Dropdown bestätigt den Eintrag."
            ),
            view=RosterPageView(self.cog, self.guild, self.member, game, names, page=0),
        )


class RosterPageView(discord.ui.View):
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
        start = self.page * LINKED_PAGE_SIZE
        chunk = all_names[start : start + LINKED_PAGE_SIZE]
        options: List[discord.SelectOption] = []
        for n in chunk[:25]:
            options.append(discord.SelectOption(label=n[:100], value=n[:100]))
        if options:

            async def _select_cb(interaction: discord.Interaction) -> None:
                await RosterPageView._handle_roster_select(
                    interaction, cog, guild, member, game_type, all_names, page, self
                )

            select = discord.ui.Select(
                placeholder="Charaktere wählen → Auswahl übernimmt",
                min_values=1,
                max_values=len(options),
                options=options,
            )
            select.callback = _select_cb
            self.add_item(select)
        b_back = discord.ui.Button(label="◀ Menü", style=discord.ButtonStyle.secondary, row=2)
        b_back.callback = self._back_menu
        self.add_item(b_back)
        if self.page > 0:
            b = discord.ui.Button(label="◀ Seite", style=discord.ButtonStyle.secondary, row=1)
            b.callback = self._prev_page
            self.add_item(b)
        if start + LINKED_PAGE_SIZE < len(all_names):
            b2 = discord.ui.Button(label="Seite ▶", style=discord.ButtonStyle.secondary, row=1)
            b2.callback = self._next_page
            self.add_item(b2)

    async def _back_menu(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(content=PANEL_INTRO, view=_menu_view(self.cog, self.guild, self.member))

    async def _prev_page(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        self.stop()
        tp = max(1, (len(self.all_names) + LINKED_PAGE_SIZE - 1) // LINKED_PAGE_SIZE)
        new_page = self.page - 1
        await interaction.response.edit_message(
            content=(
                f"Roster **{game_label(self.game_type)}** — Seite **{new_page + 1}/{tp}**."
            ),
            view=RosterPageView(
                self.cog, self.guild, self.member, self.game_type, self.all_names, new_page
            ),
        )

    async def _next_page(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        self.stop()
        tp = max(1, (len(self.all_names) + LINKED_PAGE_SIZE - 1) // LINKED_PAGE_SIZE)
        new_page = self.page + 1
        await interaction.response.edit_message(
            content=(
                f"Roster **{game_label(self.game_type)}** — Seite **{new_page + 1}/{tp}**."
            ),
            view=RosterPageView(
                self.cog, self.guild, self.member, self.game_type, self.all_names, new_page
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
        msg, ok = await cog._try_add_characters_for_member(guild, member, game_type, list(selected))
        view.stop()
        await interaction.response.edit_message(
            content=f"{msg}\n\n{PANEL_INTRO}",
            view=_menu_view(cog, guild, member),
        )


class MainGamePickView(discord.ui.View):
    def __init__(self, cog: "WowGuildAutomation", guild: discord.Guild, member: discord.Member) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.member = member

    @discord.ui.button(label="◀ Menü", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        await interaction.response.edit_message(content=PANEL_INTRO, view=_menu_view(self.cog, self.guild, self.member))

    @discord.ui.button(label="Retail", style=discord.ButtonStyle.primary, row=0)
    async def retail(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, GAME_RETAIL)

    @discord.ui.button(label="MoP Classic", style=discord.ButtonStyle.primary, row=0)
    async def mop(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, GAME_MOP)

    async def _open(self, interaction: discord.Interaction, game: str) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        linked = await get_linked_list(self.cog.config.member(self.member))
        subset = [e for e in linked if e["game_type"] == game]
        if not subset:
            await interaction.response.edit_message(
                content=f"Keine verknüpften Chars für **{game_label(game)}**.",
                view=_menu_view(self.cog, self.guild, self.member),
            )
            return
        ordered = sorted(subset, key=lambda e: e["name"].lower())
        tp = max(1, (len(ordered) + LINKED_PAGE_SIZE - 1) // LINKED_PAGE_SIZE)
        await interaction.response.edit_message(
            content=(
                f"**Main für {game_label(game)}** — Seite **1/{tp}**. "
                "Oder „Nach Namen suchen“."
            ),
            view=LinkedMainPageView(self.cog, self.guild, self.member, game, ordered, page=0),
        )


class LinkedMainPageView(discord.ui.View):
    def __init__(
        self,
        cog: "WowGuildAutomation",
        guild: discord.Guild,
        member: discord.Member,
        game_type: str,
        ordered: List[Dict[str, str]],
        page: int,
    ) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.member = member
        self.game_type = game_type
        self.ordered = ordered
        self.page = max(0, page)
        start = self.page * LINKED_PAGE_SIZE
        chunk = ordered[start : start + LINKED_PAGE_SIZE]
        opts: List[discord.SelectOption] = []
        for e in chunk[:25]:
            label = f"{e['name']}"[:100]
            value = f"{e['name']}|{e['game_type']}"
            opts.append(discord.SelectOption(label=label, value=value[:100]))
        if opts:
            s = discord.ui.Select(placeholder="Main-Char wählen", min_values=1, max_values=1, options=opts)
            s.callback = self._pick
            self.add_item(s)
        row_nav = 1
        if self.page > 0:
            b = discord.ui.Button(label="◀ Seite", style=discord.ButtonStyle.secondary, row=row_nav)
            b.callback = self._prev
            self.add_item(b)
        if start + LINKED_PAGE_SIZE < len(ordered):
            b2 = discord.ui.Button(label="Seite ▶", style=discord.ButtonStyle.secondary, row=row_nav)
            b2.callback = self._next
            self.add_item(b2)
        b_menu = discord.ui.Button(label="◀ Menü", style=discord.ButtonStyle.secondary, row=2)
        b_menu.callback = self._back_menu
        self.add_item(b_menu)
        b_search = discord.ui.Button(label="Nach Namen suchen", style=discord.ButtonStyle.secondary, row=2)
        b_search.callback = self._search
        self.add_item(b_search)

    def _caption(self) -> str:
        tp = max(1, (len(self.ordered) + LINKED_PAGE_SIZE - 1) // LINKED_PAGE_SIZE)
        return f"**Main für {game_label(self.game_type)}** — Seite **{self.page + 1}/{tp}**."

    async def _back_menu(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        await interaction.response.edit_message(content=PANEL_INTRO, view=_menu_view(self.cog, self.guild, self.member))

    async def _search(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        await interaction.response.send_modal(MainCharSearchModal(self.cog, self.guild, self.member, self.game_type))

    async def _prev(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        np = self.page - 1
        nv = LinkedMainPageView(self.cog, self.guild, self.member, self.game_type, self.ordered, np)
        await interaction.response.edit_message(content=nv._caption(), view=nv)

    async def _next(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        np = self.page + 1
        nv = LinkedMainPageView(self.cog, self.guild, self.member, self.game_type, self.ordered, np)
        await interaction.response.edit_message(content=nv._caption(), view=nv)

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
        await set_main_for_game(self.cog.config.member(self.member), game, name.strip())
        await self.cog.config.member(self.member).selected_game.set(game)
        self.stop()
        await interaction.response.edit_message(
            content=f"Main **{game_label(game)}** gesetzt: **{name.strip()}**.\n\n{PANEL_INTRO}",
            view=_menu_view(self.cog, self.guild, self.member),
        )


class MainCharSearchModal(discord.ui.Modal, title="Charakter suchen"):
    query = discord.ui.TextInput(
        label="Name (Teilstring, Groß/Klein egal)",
        placeholder="z.B. ann",
        max_length=32,
        required=True,
    )

    def __init__(
        self,
        cog: "WowGuildAutomation",
        guild: discord.Guild,
        member: discord.Member,
        game_type: str,
    ) -> None:
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.member = member
        self.game_type = game_type

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        q = str(self.query.value).strip().lower()
        linked = await get_linked_list(self.cog.config.member(self.member))
        subset = [e for e in linked if e["game_type"] == self.game_type and q in e["name"].lower()]
        if not subset:
            await interaction.response.edit_message(
                content=f"Kein Treffer für „{self.query.value}“ in **{game_label(self.game_type)}**.\n\n{PANEL_INTRO}",
                view=_menu_view(self.cog, self.guild, self.member),
            )
            return
        if len(subset) == 1:
            e = subset[0]
            await set_main_for_game(self.cog.config.member(self.member), e["game_type"], e["name"])
            await self.cog.config.member(self.member).selected_game.set(e["game_type"])
            await interaction.response.edit_message(
                content=(
                    f"Main **{game_label(e['game_type'])}** gesetzt: **{e['name']}**.\n\n{PANEL_INTRO}"
                ),
                view=_menu_view(self.cog, self.guild, self.member),
            )
            return
        ordered = sorted(subset, key=lambda e: e["name"].lower())[:25]
        opts: List[discord.SelectOption] = []
        for e in ordered:
            value = f"{e['name']}|{e['game_type']}"
            opts.append(discord.SelectOption(label=e["name"][:100], value=value[:100]))
        view = MainSearchDisambigView(self.cog, self.guild, self.member, opts)
        await interaction.response.edit_message(
            content=f"Mehrere Treffer — bitte einen wählen:",
            view=view,
        )


class MainSearchDisambigView(discord.ui.View):
    def __init__(
        self,
        cog: "WowGuildAutomation",
        guild: discord.Guild,
        member: discord.Member,
        options: List[discord.SelectOption],
    ) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.member = member
        s = discord.ui.Select(placeholder="Main wählen", min_values=1, max_values=1, options=options)
        s.callback = self._pick
        self.add_item(s)
        b = discord.ui.Button(label="◀ Menü", style=discord.ButtonStyle.secondary, row=1)
        b.callback = self._menu
        self.add_item(b)

    async def _menu(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        await interaction.response.edit_message(content=PANEL_INTRO, view=_menu_view(self.cog, self.guild, self.member))

    async def _pick(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        raw = (interaction.data.get("values") or [""])[0]
        if "|" not in raw:
            await interaction.response.send_message("Ungültig.", ephemeral=True)
            return
        name, game = raw.split("|", 1)
        await set_main_for_game(self.cog.config.member(self.member), game, name.strip())
        await self.cog.config.member(self.member).selected_game.set(game)
        await interaction.response.edit_message(
            content=f"Main **{game_label(game)}** gesetzt: **{name.strip()}**.\n\n{PANEL_INTRO}",
            view=_menu_view(self.cog, self.guild, self.member),
        )


class LinkedRemovePageView(discord.ui.View):
    """Remove linked chars; paged multi-select. officer_mode uses officer/target."""

    def __init__(
        self,
        cog: "WowGuildAutomation",
        guild: discord.Guild,
        actor: discord.Member,
        ordered: List[Dict[str, str]],
        page: int,
        *,
        officer_mode: bool,
        officer: Optional[discord.Member] = None,
        target: Optional[discord.Member] = None,
        accumulated: Optional[Set[Tuple[str, str]]] = None,
    ) -> None:
        super().__init__(timeout=600)
        self.cog = cog
        self.guild = guild
        self.actor = actor
        self.ordered = ordered
        self.page = max(0, page)
        self.officer_mode = officer_mode
        self.officer = officer
        self.target = target
        self.accumulated: Set[Tuple[str, str]] = accumulated or set()
        start = self.page * LINKED_PAGE_SIZE
        chunk = ordered[start : start + LINKED_PAGE_SIZE]
        opts: List[discord.SelectOption] = []
        for e in chunk[:25]:
            label = f"{e['name']} ({game_label(e['game_type'])})"[:100]
            value = f"{e['name']}|{e['game_type']}"
            opts.append(discord.SelectOption(label=label, value=value[:100]))
        if opts:
            s = discord.ui.Select(
                placeholder="Zur Entfernen-Markierung wählen",
                min_values=1,
                max_values=len(opts),
                options=opts,
            )
            s.callback = self._mark
            self.add_item(s)
        if officer_mode:
            b_done = discord.ui.Button(label="Grund eingeben …", style=discord.ButtonStyle.danger, row=2)
            b_done.callback = self._finish_officer
            self.add_item(b_done)
        else:
            b_apply = discord.ui.Button(label="Ausgewählte entfernen", style=discord.ButtonStyle.danger, row=2)
            b_apply.callback = self._apply_self_btn
            self.add_item(b_apply)
        b_menu = discord.ui.Button(label="◀ Abbrechen / Menü", style=discord.ButtonStyle.secondary, row=2)
        b_menu.callback = self._to_menu
        self.add_item(b_menu)
        if self.page > 0:
            b = discord.ui.Button(label="◀ Seite", style=discord.ButtonStyle.secondary, row=1)
            b.callback = self._prev
            self.add_item(b)
        if start + LINKED_PAGE_SIZE < len(ordered):
            b2 = discord.ui.Button(label="Seite ▶", style=discord.ButtonStyle.secondary, row=1)
            b2.callback = self._next
            self.add_item(b2)

    def _cap_self(self) -> str:
        tp = max(1, (len(self.ordered) + LINKED_PAGE_SIZE - 1) // LINKED_PAGE_SIZE)
        acc = len(self.accumulated)
        return (
            f"**Chars entfernen** — Seite **{self.page + 1}/{tp}** "
            f"({len(self.ordered)} gesamt). Markiert für Entfernen: **{acc}**."
        )

    def _cap_officer(self) -> str:
        assert self.target is not None
        tp = max(1, (len(self.ordered) + LINKED_PAGE_SIZE - 1) // LINKED_PAGE_SIZE)
        acc = len(self.accumulated)
        return (
            f"**Officer:** Charaktere von {self.target.mention} entfernen.\n"
            f"Seite **{self.page + 1}/{tp}**. Markiert: **{acc}**."
        )

    def _caption(self) -> str:
        return self._cap_officer() if self.officer_mode else self._cap_self()

    async def _to_menu(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.actor.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        if self.officer_mode:
            await interaction.response.edit_message(content="Abgebrochen.", view=None)
            return
        await interaction.response.edit_message(content=PANEL_INTRO, view=_menu_view(self.cog, self.guild, self.actor))

    async def _prev(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.actor.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        nv = LinkedRemovePageView(
            self.cog,
            self.guild,
            self.actor,
            self.ordered,
            self.page - 1,
            officer_mode=self.officer_mode,
            officer=self.officer,
            target=self.target,
            accumulated=self.accumulated,
        )
        await interaction.response.edit_message(content=nv._caption(), view=nv)

    async def _next(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.actor.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        nv = LinkedRemovePageView(
            self.cog,
            self.guild,
            self.actor,
            self.ordered,
            self.page + 1,
            officer_mode=self.officer_mode,
            officer=self.officer,
            target=self.target,
            accumulated=self.accumulated,
        )
        await interaction.response.edit_message(content=nv._caption(), view=nv)

    async def _mark(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.actor.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        vals = interaction.data.get("values") or []
        for v in vals:
            if "|" not in v:
                continue
            n, g = v.split("|", 1)
            self.accumulated.add((n.strip(), g.strip()))
        nv = self._rebuild_view()
        await interaction.response.edit_message(content=nv._caption(), view=nv)

    async def _apply_self_btn(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.actor.id or self.officer_mode:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        if not self.accumulated:
            await interaction.response.send_message("Noch nichts markiert.", ephemeral=True)
            return
        await self._apply_self_removal(interaction)

    def _rebuild_view(self) -> "LinkedRemovePageView":
        return LinkedRemovePageView(
            self.cog,
            self.guild,
            self.actor,
            self.ordered,
            self.page,
            officer_mode=True,
            officer=self.officer,
            target=self.target,
            accumulated=self.accumulated,
        )

    async def _apply_self_removal(self, interaction: discord.Interaction) -> None:
        keys = {(n.lower(), g.lower()) for n, g in self.accumulated}
        linked = await get_linked_list(self.cog.config.member(self.actor))
        new_list = [x for x in linked if (x["name"].lower(), x["game_type"].lower()) not in keys]
        await set_linked_list(self.cog.config.member(self.actor), new_list)
        for n, g in list(self.accumulated):
            m = await get_main_characters(self.cog.config.member(self.actor))
            cur = m.get(g)
            if cur and char_tuple_key(cur["name"], g) == char_tuple_key(n, g):
                await clear_main_for_game(self.cog.config.member(self.actor), g)
        self.accumulated.clear()
        linked2 = await get_linked_list(self.cog.config.member(self.actor))
        if not linked2:
            await interaction.response.edit_message(
                content="Ausgewählte Chars entfernt. Keine Chars mehr verknüpft.\n\n" + PANEL_INTRO,
                view=_menu_view(self.cog, self.guild, self.actor),
            )
            return
        ordered = sorted(linked2, key=lambda e: (e["game_type"], e["name"].lower()))
        new_page = min(self.page, max(0, (len(ordered) - 1) // LINKED_PAGE_SIZE))
        await interaction.response.edit_message(
            content=CharMainMenuView._remove_caption(ordered, new_page),
            view=LinkedRemovePageView(
                self.cog, self.guild, self.actor, ordered, new_page, officer_mode=False
            ),
        )

    async def _finish_officer(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.actor.id or not self.officer_mode or self.target is None:
            await interaction.response.send_message("Ungültig.", ephemeral=True)
            return
        if not self.accumulated:
            await interaction.response.send_message(
                "Noch nichts markiert — nutze das Dropdown pro Seite.",
                ephemeral=True,
            )
            return
        keys = [(n, g) for n, g in self.accumulated]
        await interaction.response.send_modal(
            OfficerRemoveReasonModal(self.cog, self.guild, self.officer or self.actor, self.target, keys)
        )


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
        to_remove: List[Tuple[str, str]],
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
        for n, g in self.to_remove:
            m = await get_main_characters(self.cog.config.member(self.target))
            cur = m.get(g)
            if cur and char_tuple_key(cur["name"], g) == char_tuple_key(n, g):
                await clear_main_for_game(self.cog.config.member(self.target), g)
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
        await interaction.response.edit_message(
            content="Wähle bis zu 25 Mitglieder:",
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
        b = discord.ui.Button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
        b.callback = self._back
        self.add_item(b)

    async def _back(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.officer.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        await interaction.response.edit_message(
            content="Wähle eine Option:",
            view=OfficerListMenuView(self.cog, self.guild, self.officer),
        )

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
