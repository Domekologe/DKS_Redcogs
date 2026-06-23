"""Modals and small views for /wow-masteradmin (keeps wowguild_automation.py smaller)."""

from __future__ import annotations

from typing import TYPE_CHECKING, List

import discord

if TYPE_CHECKING:
    from .wowguild_automation import WowGuildAutomation


class GuildSettingsModal(discord.ui.Modal, title="WoW-Gildenprofil (aktives Profil)"):
    region = discord.ui.TextInput(label="Region", placeholder="eu", default="eu", max_length=8, required=True)
    version = discord.ui.TextInput(
        label="Version",
        placeholder="retail oder mop_classic",
        default="retail",
        max_length=32,
        required=True,
    )
    realm = discord.ui.TextInput(label="Realm (Slug)", placeholder="tarren-mill", max_length=64, required=True)
    guild_name = discord.ui.TextInput(label="Gildenname (exakt)", max_length=64, required=True)
    language = discord.ui.TextInput(
        label="Bot-Sprache",
        placeholder="de-DE oder en-US",
        default="de-DE",
        max_length=8,
        required=True,
    )

    def __init__(self, cog: "WowGuildAutomation", guild: discord.Guild) -> None:
        super().__init__()
        self.cog = cog
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        lang = str(self.language.value).strip()
        if lang not in ("de-DE", "en-US"):
            lang = "de-DE"
        version_key = str(self.version.value).lower().strip().replace("-", "_")
        if version_key in ("mop", "classic_mop"):
            version_key = "mop_classic"
        profile = {
            "region": str(self.region.value).lower().strip(),
            "version": version_key,
            "realm": str(self.realm.value).strip(),
            "guild_name": str(self.guild_name.value).strip(),
        }
        cfg = await self.cog._guild_config(self.guild)
        cfg["language"] = lang
        cfg.setdefault("wow_profiles", {})
        cfg["wow_profiles"][version_key] = profile
        cfg["wow"] = profile
        cfg["active_profile_key"] = version_key
        await self.cog.config.guild(self.guild).set(cfg)
        await interaction.response.send_message("Gildenprofil gespeichert.", ephemeral=True)


class BotSetupModal(discord.ui.Modal, title="Blizzard API (Bot-Besitzer)"):
    client_id = discord.ui.TextInput(label="Client ID", max_length=128, required=True)
    client_secret = discord.ui.TextInput(
        label="Client Secret",
        style=discord.TextStyle.short,
        max_length=128,
        required=True,
    )

    def __init__(self, cog: "WowGuildAutomation") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id not in self.cog.bot.owner_ids:
            await interaction.response.send_message("Nur Bot-Besitzer.", ephemeral=True)
            return
        data = await self.cog.config.bot_setup()
        owners = set(data.get("owner_ids", []))
        owners.add(interaction.user.id)
        data["owner_ids"] = list(owners)
        data["client_id"] = str(self.client_id.value).strip()
        data["client_secret"] = str(self.client_secret.value).strip()
        await self.cog.config.bot_setup.set(data)
        self.cog.blizzard.client_id = data["client_id"]
        self.cog.blizzard.client_secret = data["client_secret"]
        await interaction.response.send_message("Blizzard API gespeichert.", ephemeral=True)


class MasterSetupModal(discord.ui.Modal, title="Globale Defaults"):
    default_language = discord.ui.TextInput(label="Sprache", default="de-DE", max_length=8, required=True)
    default_region = discord.ui.TextInput(label="Region", default="eu", max_length=8, required=True)
    default_version = discord.ui.TextInput(label="Version", default="retail", max_length=32, required=True)
    dashboard_enabled = discord.ui.TextInput(
        label="Dashboard an (ja/nein)",
        placeholder="ja",
        default="ja",
        max_length=4,
        required=True,
    )

    def __init__(self, cog: "WowGuildAutomation") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id not in self.cog.bot.owner_ids:
            await interaction.response.send_message("Nur Bot-Besitzer.", ephemeral=True)
            return
        lang = str(self.default_language.value).strip()
        if lang not in ("de-DE", "en-US"):
            lang = "de-DE"
        en = str(self.dashboard_enabled.value).lower().strip() in ("ja", "yes", "true", "1", "on")
        data = await self.cog.config.bot_setup()
        data["default_language"] = lang
        data["default_region"] = str(self.default_region.value).strip().lower()
        data["default_version"] = str(self.default_version.value).strip().lower()
        data["dashboard_enabled"] = en
        await self.cog.config.bot_setup.set(data)
        await interaction.response.send_message("Master-Defaults gespeichert.", ephemeral=True)


class SetRankTitleModal(discord.ui.Modal, title="Rangtitel (Index 0–9)"):
    rank_index = discord.ui.TextInput(label="Index", placeholder="0", max_length=2, required=True)
    title = discord.ui.TextInput(label="Anzeigetitel", max_length=64, required=True)

    def __init__(self, cog: "WowGuildAutomation", guild: discord.Guild) -> None:
        super().__init__()
        self.cog = cog
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        try:
            idx = int(str(self.rank_index.value).strip())
        except ValueError:
            await interaction.response.send_message("Ungültiger Index.", ephemeral=True)
            return
        if idx < 0 or idx > 9:
            await interaction.response.send_message("Index 0–9.", ephemeral=True)
            return
        cfg = await self.cog._guild_config(self.guild)
        pk = cfg.get("active_profile_key", "retail") or "retail"
        titles = cfg.get("rank_titles_by_profile", {}).get(pk, {})
        if not isinstance(titles, dict):
            titles = {}
        titles[str(idx)] = str(self.title.value).strip()
        cfg.setdefault("rank_titles_by_profile", {})[pk] = titles
        await self.cog.config.guild(self.guild).set(cfg)
        await interaction.response.send_message(f"Rang {idx}: `{self.title.value}` gespeichert.", ephemeral=True)


class MapRankModal(discord.ui.Modal, title="Rang → Discord-Rolle"):
    rank_name = discord.ui.TextInput(label="Rangname (wie Mapping)", max_length=64, required=True)
    role_id = discord.ui.TextInput(label="Rollen-ID", placeholder="1234567890", max_length=22, required=True)

    def __init__(self, cog: "WowGuildAutomation", guild: discord.Guild) -> None:
        super().__init__()
        self.cog = cog
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        try:
            rid = int(str(self.role_id.value).strip())
        except ValueError:
            await interaction.response.send_message("Ungültige Rollen-ID.", ephemeral=True)
            return
        role = self.guild.get_role(rid)
        if not role:
            await interaction.response.send_message("Rolle nicht gefunden.", ephemeral=True)
            return
        cfg = await self.cog._guild_config(self.guild)
        pk = cfg.get("active_profile_key", "retail") or "retail"
        m = cfg.get("rank_mapping_by_profile", {}).get(pk, {})
        if not isinstance(m, dict):
            m = {}
        m[str(self.rank_name.value).strip()] = rid
        cfg.setdefault("rank_mapping_by_profile", {})[pk] = m
        await self.cog.config.guild(self.guild).set(cfg)
        await interaction.response.send_message(f"Mapping: `{self.rank_name.value}` → {role.mention}", ephemeral=True)


class SyncIntervalModal(discord.ui.Modal, title="Auto Rang-Sync Intervall"):
    minutes = discord.ui.TextInput(
        label="Minuten (0 = aus)",
        placeholder="60",
        default="0",
        max_length=5,
        required=True,
    )

    def __init__(self, cog: "WowGuildAutomation", guild: discord.Guild) -> None:
        super().__init__()
        self.cog = cog
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        try:
            m = int(str(self.minutes.value).strip())
        except ValueError:
            await interaction.response.send_message("Ungültige Zahl.", ephemeral=True)
            return
        if m < 0:
            m = 0
        cfg = await self.cog._guild_config(self.guild)
        cfg["rank_sync_interval_minutes"] = m
        await self.cog.config.guild(self.guild).set(cfg)
        await interaction.response.send_message(
            f"Intervall: **{m}** Min. (0 = kein automatischer Sync).",
            ephemeral=True,
        )


class OnboardingSetupModal(discord.ui.Modal, title="Onboarding: Kanal & Rollen"):
    channel_id = discord.ui.TextInput(
        label="Onboarding-Channel-ID (0 = unverändert)",
        placeholder="0",
        default="0",
        max_length=22,
        required=True,
    )
    new_role_id = discord.ui.TextInput(
        label="Rolle „onboarding-new“ ID",
        placeholder="0",
        default="0",
        max_length=22,
        required=True,
    )
    complete_role_id = discord.ui.TextInput(
        label="Rolle „onboarding-complete“ ID",
        placeholder="0",
        default="0",
        max_length=22,
        required=True,
    )

    def __init__(self, cog: "WowGuildAutomation", guild: discord.Guild) -> None:
        super().__init__()
        self.cog = cog
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return

        def _parse_id(raw: str) -> int:
            s = str(raw).strip()
            if not s or s == "0":
                return 0
            try:
                return int(s)
            except ValueError:
                return -1

        ch = _parse_id(self.channel_id.value)
        nr = _parse_id(self.new_role_id.value)
        cr = _parse_id(self.complete_role_id.value)
        if -1 in (ch, nr, cr):
            await interaction.response.send_message("Ungültige IDs.", ephemeral=True)
            return
        cfg = await self.cog._guild_config(self.guild)
        channels = dict(cfg.get("channels") or {})
        roles = dict(cfg.get("roles") or {})
        if ch > 0:
            channels["onboarding_channel_id"] = ch
        if nr > 0:
            roles["onboarding_new_role_id"] = nr
        if cr > 0:
            roles["onboarding_complete_role_id"] = cr
        cfg["channels"] = channels
        cfg["roles"] = roles
        await self.cog.config.guild(self.guild).set(cfg)
        await self.cog._apply_onboarding_channel_permissions(self.guild)
        await interaction.response.send_message(
            "Onboarding-IDs gespeichert und Kanalrechte angewendet (soweit möglich).",
            ephemeral=True,
        )


class AdminPickOneMemberView(discord.ui.View):
    """Pick a single member — e.g. simulate-join, delete registration, single rank sync."""

    def __init__(
        self,
        cog: "WowGuildAutomation",
        guild: discord.Guild,
        officer: discord.Member,
        *,
        mode: str,
    ) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild
        self.officer = officer
        self.mode = mode

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Mitglied wählen", min_values=1, max_values=1)
    async def pick(self, interaction: discord.Interaction, select: discord.ui.UserSelect) -> None:
        if interaction.user.id != self.officer.id:
            await interaction.response.send_message("Nur für dich.", ephemeral=True)
            return
        u = select.values[0]
        member = self.guild.get_member(u.id)
        if member is None:
            await interaction.response.send_message("Mitglied nicht auf dem Server.", ephemeral=True)
            return
        if self.mode == "simulate_join":
            await interaction.response.defer(ephemeral=True)
            await self.cog._run_onboarding_flow(member, simulated=True)
            await interaction.followup.send(f"Onboarding-Simulation für {member.mention} fertig.", ephemeral=True)
            self.stop()
            return
        if self.mode == "remove_registration":
            await self.cog.config.member(member).registration.clear()
            await self.cog.config.member(member).selected_game.clear()
            await interaction.response.send_message(
                f"Registrierung von {member.mention} gelöscht.",
                ephemeral=True,
            )
            self.stop()
            return
        if self.mode == "sync_rank_member":
            await interaction.response.defer(ephemeral=True)
            text = await self.cog._slash_admin_sync_report_for_member(self.guild, member)
            await interaction.followup.send(text[:1900], ephemeral=True)
            self.stop()
            return
        await interaction.response.send_message("Unbekannt.", ephemeral=True)


class RankLockAddModal(discord.ui.Modal, title="Rank-Lock: Rang sperren"):
    line = discord.ui.TextInput(
        label="Rangname oder Index (0–9), wie in der WebUI",
        placeholder="z.B. Kriegsfürst oder 3",
        max_length=64,
        required=True,
    )

    def __init__(self, cog: "WowGuildAutomation", guild: discord.Guild) -> None:
        super().__init__()
        self.cog = cog
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        new_l = str(self.line.value).strip()
        if not new_l:
            await interaction.response.send_message("Leer.", ephemeral=True)
            return
        cfg = await self.cog._guild_config(self.guild)
        pk = str(cfg.get("active_profile_key") or "retail")
        lr = dict(cfg.get("locked_rank_titles_by_profile") or {})
        cur = lr.get(pk)
        lines: List[str]
        if cur is None:
            lines = []
        elif isinstance(cur, str):
            lines = [cur]
        elif isinstance(cur, (list, tuple)):
            lines = [str(x).strip() for x in cur if str(x).strip()]
        else:
            lines = []
        low = {x.lower() for x in lines}
        if new_l.lower() not in low:
            lines.append(new_l)
        lr[pk] = lines
        cfg["locked_rank_titles_by_profile"] = lr
        await self.cog.config.guild(self.guild).set(cfg)
        await interaction.response.send_message(
            f"Rank-Lock für **{new_l}** gespeichert (aktives Profil `{pk}`).",
            ephemeral=True,
        )


class RankLockRemoveModal(discord.ui.Modal, title="Rank-Lock: Eintrag entfernen"):
    line = discord.ui.TextInput(
        label="Exakt oder Teil des Eintrags (Groß/Klein egal)",
        placeholder="z.B. Kriegsfürst",
        max_length=64,
        required=True,
    )

    def __init__(self, cog: "WowGuildAutomation", guild: discord.Guild) -> None:
        super().__init__()
        self.cog = cog
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        needle = str(self.line.value).strip().lower()
        if not needle:
            await interaction.response.send_message("Leer.", ephemeral=True)
            return
        cfg = await self.cog._guild_config(self.guild)
        pk = str(cfg.get("active_profile_key") or "retail")
        lr = dict(cfg.get("locked_rank_titles_by_profile") or {})
        cur = lr.get(pk)
        if isinstance(cur, str):
            lines = [cur] if cur.strip() else []
        elif isinstance(cur, (list, tuple)):
            lines = [str(x).strip() for x in cur if str(x).strip()]
        else:
            lines = []
        before = len(lines)
        lines = [x for x in lines if needle not in x.lower()]
        removed = before - len(lines)
        if removed == 0:
            await interaction.response.send_message(
                f"Kein Treffer in der Rank-Lock-Liste für Profil `{pk}`.",
                ephemeral=True,
            )
            return
        lr[pk] = lines
        cfg["locked_rank_titles_by_profile"] = lr
        await self.cog.config.guild(self.guild).set(cfg)
        await interaction.response.send_message(
            f"**{removed}** Eintrag/Einträge aus Rank-Lock entfernt (`{pk}`).",
            ephemeral=True,
        )
