from typing import Dict, Optional, List

import discord
from discord.ext import commands

from ..functions.automations import RankSyncService

TEXTS: Dict[str, Dict[str, str]] = {
    "de-DE": {
        "lang_prompt": "Willkommen! Bitte waehle deine Sprache.",
        "lang_timeout": "Onboarding abgebrochen (Zeit abgelaufen).",
        "role_prompt": "Bist du Gast oder neues Gildenmitglied?",
        "guest_done": "Du wurdest als Gast markiert.",
        "rules_channel_hint": "Bitte gehe jetzt zu {rules_channel} und bestaetige die Regeln mit {emoji}.",
        "mainchar_prompt": "Bitte gib deinen Mainchar ein (Button -> Popup).",
        "game_prompt": "Fuer welches WoW-Spiel meldest du dich an?",
        "mainchar_timeout": "Kein Mainchar erhalten, Onboarding beendet.",
        "verified": "Verifizierung erfolgreich. Mainchar `{main}` gefunden, Ingame-Rang `{rank}`.",
        "manual": "Automatische Verifizierung nicht moeglich. Das Team wurde fuer manuelle Pruefung benachrichtigt.",
        "rules": "Wichtig: Bitte lies die Serverregeln und bestaetige sie mit dem vorgegebenen Emoji.",
        "rules_confirm": "Regeln bestaetigen",
    },
    "en-US": {
        "lang_prompt": "Welcome! Please choose your language.",
        "lang_timeout": "Onboarding cancelled (timeout).",
        "role_prompt": "Are you a guest or a new guild member?",
        "guest_done": "You are marked as a guest.",
        "rules_channel_hint": "Please go to {rules_channel} and confirm the rules with {emoji}.",
        "mainchar_prompt": "Please enter your main character (button -> popup).",
        "game_prompt": "Which WoW game are you signing up for?",
        "mainchar_timeout": "No main character received, onboarding cancelled.",
        "verified": "Verification successful. Main character `{main}` found, ingame rank `{rank}`.",
        "manual": "Automatic verification failed. The team was notified for manual review.",
        "rules": "Important: Please read the server rules and confirm with the required emoji.",
        "rules_confirm": "Confirm rules",
    },
}


class ChoiceView(discord.ui.View):
    def __init__(self, user_id: int, options: List[tuple[str, str]], timeout: int = 180) -> None:
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.value: Optional[str] = None
        for label, value in options[:5]:
            self.add_item(ChoiceButton(label=label, value=value))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This interaction is not for you.", ephemeral=True)
            return False
        return True


class ChoiceButton(discord.ui.Button):
    def __init__(self, label: str, value: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.choice_value = value

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, ChoiceView):
            view.value = self.choice_value
            for child in view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            await interaction.response.edit_message(view=view)
            view.stop()


class MainCharModal(discord.ui.Modal, title="Main Character"):
    char_name = discord.ui.TextInput(label="Main Character Name", max_length=40, required=True)

    def __init__(self) -> None:
        super().__init__()
        self.value: Optional[str] = None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.value = str(self.char_name.value).strip()
        await interaction.response.send_message("Character received.", ephemeral=True)


class MainCharView(discord.ui.View):
    def __init__(self, user_id: int, timeout: int = 300) -> None:
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.value: Optional[str] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This interaction is not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Open Input", style=discord.ButtonStyle.success)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        _ = button
        modal = MainCharModal()
        await interaction.response.send_modal(modal)
        await modal.wait()
        if modal.value:
            self.value = modal.value
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
            self.stop()


class RulesConfirmView(ChoiceView):
    def __init__(self, user_id: int, label: str, timeout: int = 300) -> None:
        super().__init__(user_id=user_id, options=[(label, "confirmed")], timeout=timeout)


async def handle_new_member_onboarding(
    bot: commands.Bot,
    member: discord.Member,
    guild_config: dict,
    rank_sync: RankSyncService,
    manual_channel: Optional[discord.TextChannel],
    onboarding_channel: Optional[discord.TextChannel] = None,
) -> dict:
    destination: discord.abc.Messageable
    if onboarding_channel is not None:
        try:
            thread = await onboarding_channel.create_thread(
                name=f"onboarding-{member.display_name[:60]}",
                type=discord.ChannelType.private_thread,
                invitable=False,
                reason="Private onboarding thread",
            )
            await thread.add_user(member)
            await thread.send(f"{member.mention} onboarding started. Use the buttons below.")
            destination = thread
        except Exception:
            destination = await member.create_dm()
    else:
        destination = await member.create_dm()

    onboarding_cfg = guild_config.get("onboarding", {})
    if onboarding_cfg.get("welcome_text_de") or onboarding_cfg.get("welcome_text_en"):
        await destination.send(
            (onboarding_cfg.get("welcome_text_de", "") + "\n" + onboarding_cfg.get("welcome_text_en", "")).strip()
        )

    lang_view = ChoiceView(member.id, [("Deutsch", "de-DE"), ("English (US)", "en-US")], timeout=180)
    await destination.send(TEXTS["de-DE"]["lang_prompt"] + "\n" + TEXTS["en-US"]["lang_prompt"], view=lang_view)
    if await lang_view.wait() or not lang_view.value:
        await destination.send(TEXTS["de-DE"]["lang_timeout"])
        return {
            "language": "de-DE",
            "selected_game": "retail",
            "registration": {
                "type": "unknown",
                "char_name": "",
                "verified": False,
                "requires_manual_verification": False,
                "rules_confirmed": False,
            },
        }
    lang = lang_view.value
    t = TEXTS[lang]

    role_view = ChoiceView(
        member.id,
        [("Gast" if lang == "de-DE" else "Guest", "guest"), ("Mitglied" if lang == "de-DE" else "Member", "member")],
        timeout=180,
    )
    await destination.send(t["role_prompt"], view=role_view)
    if await role_view.wait() or not role_view.value:
        await destination.send(t["lang_timeout"])
        return {
            "language": lang,
            "selected_game": "retail",
            "registration": {
                "type": "unknown",
                "char_name": "",
                "verified": False,
                "requires_manual_verification": False,
                "rules_confirmed": False,
            },
        }

    roles = guild_config.get("roles", {})
    guest_role = member.guild.get_role(roles.get("guest_role_id", 0))
    member_role = member.guild.get_role(roles.get("member_role_id", 0))
    rules_cfg = guild_config.get("rules", {})
    rule_channel = member.guild.get_channel(rules_cfg.get("rule_channel_id", 0))
    rule_emoji = str(rules_cfg.get("rule_emoji", "✅"))

    async def confirm_rules() -> bool:
        await destination.send(t["rules"])
        if rule_channel is not None:
            await destination.send(
                t["rules_channel_hint"].format(rules_channel=rule_channel.mention, emoji=rule_emoji)
            )
            try:
                rules_msg = await rule_channel.send(
                    f"{member.mention} - bitte bestaetige die Regeln mit {rule_emoji}."
                )
                await rules_msg.add_reaction(rule_emoji)

                def reaction_check(payload: discord.RawReactionActionEvent) -> bool:
                    return (
                        payload.guild_id == member.guild.id
                        and payload.channel_id == rule_channel.id
                        and payload.message_id == rules_msg.id
                        and payload.user_id == member.id
                        and str(payload.emoji) == rule_emoji
                    )

                await bot.wait_for("raw_reaction_add", check=reaction_check, timeout=300)
                return True
            except Exception:
                pass
        confirm_view = RulesConfirmView(member.id, f"{t['rules_confirm']} {rule_emoji}")
        await destination.send("Click to finish onboarding:", view=confirm_view)
        return (not await confirm_view.wait()) and confirm_view.value == "confirmed"

    if role_view.value == "guest":
        if guest_role:
            await member.add_roles(guest_role, reason="WoW onboarding: guest")
        await destination.send(t["guest_done"])
        rules_confirmed = await confirm_rules()
        return {
            "language": lang,
            "selected_game": "retail",
            "registration": {
                "type": "guest",
                "char_name": "",
                "verified": False,
                "requires_manual_verification": False,
                "rules_confirmed": rules_confirmed,
            },
        }

    wow_profiles = guild_config.get("wow_profiles", {})
    if not wow_profiles:
        wow_single = guild_config.get("wow", {})
        wow_profiles = {wow_single.get("version", "retail"): wow_single}
    game_keys = list(wow_profiles.keys())
    selected_game = game_keys[0] if game_keys else "retail"
    game_view = ChoiceView(member.id, [(k, k) for k in game_keys], timeout=180)
    await destination.send(t["game_prompt"], view=game_view)
    _ = await game_view.wait()
    if game_view.value:
        selected_game = game_view.value

    modal_view = MainCharView(member.id, timeout=300)
    await destination.send(t["mainchar_prompt"], view=modal_view)
    if await modal_view.wait() or not modal_view.value:
        await destination.send(t["mainchar_timeout"])
        return {
            "language": lang,
            "selected_game": selected_game,
            "registration": {
                "type": "member",
                "char_name": "",
                "verified": False,
                "requires_manual_verification": True,
                "rules_confirmed": False,
            },
        }

    main_char = modal_view.value.strip()
    selected_cfg = dict(guild_config)
    selected_cfg["wow"] = wow_profiles.get(selected_game, {})
    rank = await rank_sync.sync_member_rank(member, selected_cfg, main_char)
    if rank:
        if member_role and member_role not in member.roles:
            await member.add_roles(member_role, reason="WoW onboarding: verified guild member")
        await destination.send(t["verified"].format(main=main_char, rank=rank))
        if manual_channel:
            await manual_channel.send(
                f"User {member.display_name} ({member.name}) hat sich angemeldet als {main_char}. "
                f"Automatisch verifiziert (Rang: {rank})."
            )
    else:
        template = guild_config.get("templates", {}).get(
            "manual_verification",
            "Manuelle Verifizierung nötig! User {username} hat sich gemeldet als Char {charname}.",
        )
        if manual_channel:
            await manual_channel.send(template.format(username=member.display_name, charname=main_char))
            await manual_channel.send(
                f"User {member.display_name} ({member.name}) hat sich angemeldet als {main_char}. "
                "Char nicht gefunden - manuelle Verifizierung noetig."
            )
        await destination.send(t["manual"])

    rules_confirmed = await confirm_rules()
    return {
        "language": lang,
        "selected_game": selected_game,
        "registration": {
            "type": "member",
            "char_name": main_char,
            "verified": bool(rank),
            "requires_manual_verification": not bool(rank),
            "rules_confirmed": rules_confirmed,
        },
    }

